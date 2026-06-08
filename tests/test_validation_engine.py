from unittest.mock import MagicMock

from datasure.config.settings import Settings
from datasure.core.validation_engine import ValidationEngine
from datasure.validators.base import Severity, ValidationIssue, ValidationResult


def _make_settings(**kwargs) -> Settings:
    return Settings(**kwargs)


def test_engine_runs_enabled_validators():
    settings = _make_settings()
    engine = ValidationEngine(settings)
    objects = [
        {"type": "app", "id": "app1", "name": "Test App", "description": "desc"},
        {"type": "measure", "id": "m1", "expression": "Sum(Sales)", "label": "Revenue"},
    ]
    results = engine.run(objects)
    assert len(results) > 0


def test_summary_counts_correctly():
    settings = _make_settings()
    engine = ValidationEngine(settings)

    r1 = ValidationResult("syntax", "app", "a1", passed=True)
    r2 = ValidationResult("syntax", "measure", "m1", passed=False, issues=[
        ValidationIssue("SYN030", Severity.ERROR, "Empty expr", "measure", "m1"),
    ])
    r3 = ValidationResult("data_types", "measure", "m1", passed=True, issues=[
        ValidationIssue("DT001", Severity.WARNING, "type mismatch", "measure", "m1"),
    ])

    summary = engine.summary([r1, r2, r3])
    assert summary["total_objects"] == 3
    assert summary["passed"] == 2
    assert summary["failed"] == 1
    assert summary["total_errors"] == 1
    assert summary["total_warnings"] == 1


def test_engine_ignores_unknown_validator_module():
    settings = _make_settings()
    settings.validation.enabled_modules = ["syntax", "nonexistent_module"]
    engine = ValidationEngine(settings)
    assert len(engine._validators) == 1
