from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from datasure.config.settings import Settings
from datasure.validators.base import BaseValidator, ValidationResult

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type[BaseValidator]] = {}


def register_validator(cls: type[BaseValidator]) -> type[BaseValidator]:
    _REGISTRY[cls.name] = cls
    return cls


def _load_builtin_validators() -> None:
    from datasure.validators.data_model_health import DataModelHealthValidator
    from datasure.validators.data_types import DataTypeValidator
    from datasure.validators.duplicates import DuplicateExpressionValidator
    from datasure.validators.field_integrity import FieldIntegrityValidator
    from datasure.validators.load_script import LoadScriptValidator
    from datasure.validators.performance import PerformanceValidator
    from datasure.validators.resource_optimization import ResourceOptimizationValidator
    from datasure.validators.syntax import SyntaxValidator

    for cls in (
        SyntaxValidator,
        DataTypeValidator,
        FieldIntegrityValidator,
        DataModelHealthValidator,
        DuplicateExpressionValidator,
        PerformanceValidator,
        LoadScriptValidator,
        ResourceOptimizationValidator,
    ):
        register_validator(cls)


class ValidationEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        _load_builtin_validators()
        self._load_plugins()
        self._validators: list[BaseValidator] = self._build_validators()

    def _load_plugins(self) -> None:
        from datasure.plugins.loader import load_plugins
        plugins_dir = getattr(self.settings.validation, "plugins_dir", None)
        load_plugins(_REGISTRY, Path(plugins_dir) if plugins_dir else None)

    def _build_validators(self) -> list[BaseValidator]:
        enabled = self.settings.validation.enabled_modules
        validators = []
        for name in enabled:
            cls = _REGISTRY.get(name)
            if cls is None:
                log.warning("Unknown validator module '%s' — skipping", name)
                continue
            validators.append(cls())
            log.debug("Loaded validator: %s", name)
        return validators

    def _prime_all(self, objects: list[dict[str, Any]]) -> None:
        data_model   = next((o for o in objects if o.get("type") == "data_model"), {})
        master_items = [o for o in objects if o.get("type") in ("measure", "dimension") and o.get("is_master")]
        variables    = [o for o in objects if o.get("type") == "variable"]
        for v in self._validators:
            v.prime_context(objects, data_model, master_items, variables)

    def run(self, objects: list[dict[str, Any]]) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        fail_fast   = self.settings.validation.fail_fast
        max_workers = self.settings.validation.max_workers

        self._prime_all(objects)

        per_object = [v for v in self._validators if not v.is_stateful]
        stateful   = [v for v in self._validators if v.is_stateful]

        def _validate_one(obj: dict[str, Any]) -> list[ValidationResult]:
            obj_results = []
            for validator in per_object:
                try:
                    obj_results.extend(validator.validate(obj))
                except Exception:
                    log.exception(
                        "Validator '%s' raised on object %s", validator.name, obj.get("id")
                    )
            return obj_results

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_validate_one, obj): obj for obj in objects}
            for future in as_completed(futures):
                batch = future.result()
                results.extend(batch)
                if fail_fast and any(r.error_count > 0 for r in batch):
                    log.warning("fail_fast enabled — aborting after first error batch")
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

        for v in stateful:
            try:
                results.extend(v.validate_all(objects))
            except Exception:
                log.exception("Stateful validator '%s' raised", v.name)

        return results

    def summary(self, results: list[ValidationResult]) -> dict[str, Any]:
        total   = len(results)
        passed  = sum(1 for r in results if r.passed)
        errors  = sum(r.error_count for r in results)
        warnings = sum(r.warning_count for r in results)
        return {
            "total_objects": total,
            "passed": passed,
            "failed": total - passed,
            "total_errors": errors,
            "total_warnings": warnings,
        }
