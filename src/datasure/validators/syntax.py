from __future__ import annotations

import re
from typing import Any

from .base import BaseValidator, Severity, ValidationResult


class SyntaxValidator(BaseValidator):
    """Validates naming conventions, field presence, and structural rules."""

    name = "syntax"

    # Qlik expression patterns that indicate common mistakes
    _UNBALANCED_BRACKET = re.compile(r"\[(?:[^\[\]]|\[[^\[\]]*\])*$")
    _DOLLAR_SIGN_EXPANSION = re.compile(r"\$\([^)]+\)")
    _EMPTY_EXPRESSION = re.compile(r"^\s*$")

    def validate(self, obj: dict[str, Any]) -> list[ValidationResult]:
        issues = []
        obj_type = obj.get("type", "unknown")
        obj_id = obj.get("id", "")

        if obj_type == "app":
            issues.extend(self._validate_app(obj))
        elif obj_type == "sheet":
            issues.extend(self._validate_sheet(obj))
        elif obj_type == "visualization":
            issues.extend(self._validate_visualization(obj))
        elif obj_type == "measure":
            issues.extend(self._validate_measure(obj))
        elif obj_type == "dimension":
            issues.extend(self._validate_dimension(obj))

        passed = not any(i.severity == Severity.ERROR for i in issues)
        return [ValidationResult(
            validator_name=self.name,
            object_type=obj_type,
            object_id=obj_id,
            passed=passed,
            issues=issues,
        )]

    def _validate_app(self, obj: dict[str, Any]) -> list:
        issues = []
        if not obj.get("name", "").strip():
            issues.append(self._issue(
                "SYN001", Severity.ERROR, "App has no name", obj
            ))
        if not obj.get("description"):
            issues.append(self._issue(
                "SYN002", Severity.WARNING, "App has no description", obj
            ))
        return issues

    def _validate_sheet(self, obj: dict[str, Any]) -> list:
        issues = []
        if not obj.get("title", "").strip():
            issues.append(self._issue(
                "SYN010", Severity.WARNING, "Sheet has no title", obj
            ))
        cells = obj.get("cells", [])
        if not cells:
            issues.append(self._issue(
                "SYN011", Severity.WARNING, "Sheet contains no visualizations", obj
            ))
        return issues

    def _validate_visualization(self, obj: dict[str, Any]) -> list:
        issues = []
        viz_type = obj.get("visualization_type", "")
        if not viz_type:
            issues.append(self._issue(
                "SYN020", Severity.ERROR, "Visualization has no type set", obj
            ))
        props = obj.get("properties", {})
        title = props.get("title", "") or ""
        if not title.strip():
            issues.append(self._issue(
                "SYN021", Severity.WARNING, "Visualization has no title", obj
            ))
        return issues

    def _validate_measure(self, obj: dict[str, Any]) -> list:
        issues = []
        expr = obj.get("expression", "")
        if self._EMPTY_EXPRESSION.match(expr):
            issues.append(self._issue(
                "SYN030", Severity.ERROR, "Measure has an empty expression", obj
            ))
        elif self._UNBALANCED_BRACKET.search(expr):
            issues.append(self._issue(
                "SYN031", Severity.ERROR,
                "Measure expression appears to have unbalanced brackets", obj,
                {"expression": expr},
            ))
        label = obj.get("label", "")
        if not label.strip():
            issues.append(self._issue(
                "SYN032", Severity.WARNING, "Measure has no label", obj
            ))
        return issues

    def _validate_dimension(self, obj: dict[str, Any]) -> list:
        issues = []
        field_def = obj.get("field_def", "")
        if not field_def.strip():
            issues.append(self._issue(
                "SYN040", Severity.ERROR, "Dimension has no field definition", obj
            ))
        return issues
