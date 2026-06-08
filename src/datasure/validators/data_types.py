from __future__ import annotations

from typing import Any

from .base import BaseValidator, Severity, ValidationResult

_NUMERIC_AGG_FUNCTIONS = {
    "sum", "avg", "min", "max", "count", "stdev", "median", "fractile",
    "mode", "kurtosis", "skew", "correl",
}

_DATE_FUNCTIONS = {
    "date", "time", "timestamp", "year", "month", "day", "hour", "minute",
    "second", "weekday", "week", "quarter", "monthname", "dayname",
    "makedate", "maketime", "maketimestamp",
}


class DataTypeValidator(BaseValidator):
    """Validates data type consistency in field definitions and expressions."""

    name = "data_types"

    def validate(self, obj: dict[str, Any]) -> list[ValidationResult]:
        issues = []
        obj_type = obj.get("type", "unknown")
        obj_id = obj.get("id", "")

        if obj_type == "measure":
            issues.extend(self._validate_measure_types(obj))
        elif obj_type == "dimension":
            issues.extend(self._validate_dimension_types(obj))
        elif obj_type == "data_model":
            issues.extend(self._validate_data_model(obj))

        passed = not any(i.severity == Severity.ERROR for i in issues)
        return [ValidationResult(
            validator_name=self.name,
            object_type=obj_type,
            object_id=obj_id,
            passed=passed,
            issues=issues,
        )]

    def _validate_measure_types(self, obj: dict[str, Any]) -> list:
        issues = []
        expr = (obj.get("expression") or "").lower()
        expected_type = obj.get("expected_type", "")

        is_numeric = any(f"({expr}".find(fn + "(") >= 0 for fn in _NUMERIC_AGG_FUNCTIONS)
        is_date = any(f"({expr}".find(fn + "(") >= 0 for fn in _DATE_FUNCTIONS)

        if expected_type == "numeric" and is_date and not is_numeric:
            issues.append(self._issue(
                "DT001", Severity.WARNING,
                "Measure declared as numeric but expression appears date-oriented",
                obj, {"expression": obj.get("expression")},
            ))
        if expected_type == "date" and is_numeric and not is_date:
            issues.append(self._issue(
                "DT002", Severity.WARNING,
                "Measure declared as date but expression appears numeric",
                obj, {"expression": obj.get("expression")},
            ))

        format_str = obj.get("number_format", {}).get("fmt", "")
        if is_date and format_str and not any(
            c in format_str for c in ("Y", "M", "D", "h", "m", "s")
        ):
            issues.append(self._issue(
                "DT003", Severity.WARNING,
                "Date-like expression uses a non-date number format",
                obj, {"format": format_str},
            ))
        return issues

    def _validate_dimension_types(self, obj: dict[str, Any]) -> list:
        issues = []
        field_def = (obj.get("field_def") or "").strip()
        tags = obj.get("tags", [])

        if "$numeric" in tags and any(
            fn in field_def.lower() for fn in _DATE_FUNCTIONS
        ):
            issues.append(self._issue(
                "DT010", Severity.WARNING,
                "Dimension tagged as numeric but field definition references date functions",
                obj,
            ))
        return issues

    def _validate_data_model(self, obj: dict[str, Any]) -> list:
        issues = []
        tables = obj.get("tables", [])
        for table in tables:
            for field in table.get("fields", []):
                tags = field.get("tags", [])
                name: str = field.get("name", "")
                if "$date" in tags and "$numeric" in tags:
                    issues.append(self._issue(
                        "DT020", Severity.INFO,
                        f"Field '{name}' is tagged both $date and $numeric — verify dual classification is intentional",
                        obj, {"table": table.get("name"), "field": name},
                    ))
                if not tags:
                    issues.append(self._issue(
                        "DT021", Severity.INFO,
                        f"Field '{name}' has no type tags — Qlik may not have inferred its type",
                        obj, {"table": table.get("name"), "field": name},
                    ))
        return issues
