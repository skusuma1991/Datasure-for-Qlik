from __future__ import annotations

import re
from typing import Any

from .base import BaseValidator, Severity, ValidationResult, ValidationIssue

_VAR_REF = re.compile(r"\$\(([^)]+)\)")
_MASTER_THRESHOLD_MEASURES = 3   # if >= this many inline measures, recommend master items
_MASTER_THRESHOLD_DIMS = 2


class ResourceOptimizationValidator(BaseValidator):
    """
    Cross-object optimisation advisor.

    Checks that run after all objects are collected:
      RO001 — no master measures defined despite many inline measures
      RO002 — no master dimensions defined despite many inline dimensions
      RO003 — variable is defined but never referenced in any expression
      RO004 — app has both inline and master measures; master items underused
    """

    name = "resource_optimization"
    is_stateful = True

    def __init__(self) -> None:
        self._variables: dict[str, str] = {}

    def prime_context(self, objects, data_model, master_items, variables) -> None:
        self._variables = {v.get("name", "").lower(): v.get("definition", "") for v in variables}

    def validate(self, obj: dict[str, Any]) -> list[ValidationResult]:
        return []

    def validate_all(self, objects: list[dict[str, Any]]) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        measures    = [o for o in objects if o.get("type") == "measure"]
        dimensions  = [o for o in objects if o.get("type") == "dimension"]
        variables   = [o for o in objects if o.get("type") == "variable"]

        master_measures = [m for m in measures if m.get("is_master")]
        master_dims     = [d for d in dimensions if d.get("is_master")]
        inline_measures = [m for m in measures if not m.get("is_master")]
        inline_dims     = [d for d in dimensions if not d.get("is_master")]

        results.extend(self._check_no_master_measures(objects, inline_measures, master_measures))
        results.extend(self._check_no_master_dimensions(objects, inline_dims, master_dims))
        results.extend(self._check_unused_variables(objects, variables))
        results.extend(self._check_master_item_adoption(objects, inline_measures, master_measures))

        return results

    # ── checks ────────────────────────────────────────────────────────────────

    def _check_no_master_measures(self, objects, inline_measures, master_measures) -> list:
        if master_measures or len(inline_measures) < _MASTER_THRESHOLD_MEASURES:
            return []
        issue = ValidationIssue(
            rule_id="RO001",
            severity=Severity.WARNING,
            message=(
                f"App has {len(inline_measures)} inline measures but no Master Measures — "
                "master measures enable reuse, centralised editing, and colouring"
            ),
            object_type="app",
            object_id="app",
            object_name="App",
            detail={"inline_measure_count": len(inline_measures)},
        )
        return [ValidationResult(
            validator_name=self.name,
            object_type="app",
            object_id="ro:master-measures",
            passed=True,
            issues=[issue],
        )]

    def _check_no_master_dimensions(self, objects, inline_dims, master_dims) -> list:
        if master_dims or len(inline_dims) < _MASTER_THRESHOLD_DIMS:
            return []
        issue = ValidationIssue(
            rule_id="RO002",
            severity=Severity.WARNING,
            message=(
                f"App has {len(inline_dims)} inline dimensions but no Master Dimensions — "
                "master dimensions ensure consistent field definitions and drill-down paths"
            ),
            object_type="app",
            object_id="app",
            object_name="App",
            detail={"inline_dim_count": len(inline_dims)},
        )
        return [ValidationResult(
            validator_name=self.name,
            object_type="app",
            object_id="ro:master-dimensions",
            passed=True,
            issues=[issue],
        )]

    def _check_unused_variables(self, objects, variables) -> list:
        if not variables:
            return []

        # Collect all expressions across the app
        all_exprs: list[str] = []
        for obj in objects:
            obj_type = obj.get("type", "")
            if obj_type == "measure":
                all_exprs.append(obj.get("expression", ""))
            elif obj_type == "dimension":
                all_exprs.append(obj.get("field_def", ""))
            elif obj_type == "visualization":
                for m in obj.get("measures", []):
                    all_exprs.append(m.get("expression", ""))
        combined = " ".join(all_exprs).lower()

        results = []
        for var in variables:
            name = var.get("name", "")
            # A variable is "used" if $(varName) appears anywhere in expressions
            pattern = f"$({name.lower()})"
            if pattern not in combined:
                issue = ValidationIssue(
                    rule_id="RO003",
                    severity=Severity.INFO,
                    message=(
                        f"Variable '{name}' is defined but never referenced in any expression — "
                        "unused variables add clutter; remove or document their purpose"
                    ),
                    object_type="variable",
                    object_id=var.get("id", ""),
                    object_name=name,
                    detail={"definition": var.get("definition", "")},
                )
                results.append(ValidationResult(
                    validator_name=self.name,
                    object_type="variable",
                    object_id=var.get("id", ""),
                    passed=True,
                    issues=[issue],
                ))
        return results

    def _check_master_item_adoption(self, objects, inline_measures, master_measures) -> list:
        """Warn when master measures exist but most measures are still inline."""
        if not master_measures or not inline_measures:
            return []
        total = len(master_measures) + len(inline_measures)
        adoption_rate = len(master_measures) / total
        if adoption_rate < 0.3:
            issue = ValidationIssue(
                rule_id="RO004",
                severity=Severity.INFO,
                message=(
                    f"Only {len(master_measures)} of {total} measures are Master Items "
                    f"({adoption_rate:.0%} adoption) — migrate inline measures to master items "
                    "for easier governance"
                ),
                object_type="app",
                object_id="app",
                object_name="App",
                detail={
                    "master_count": len(master_measures),
                    "inline_count": len(inline_measures),
                    "adoption_pct": round(adoption_rate * 100),
                },
            )
            return [ValidationResult(
                validator_name=self.name,
                object_type="app",
                object_id="ro:master-adoption",
                passed=True,
                issues=[issue],
            )]
        return []
