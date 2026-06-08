from __future__ import annotations

import re
from typing import Any

from .base import BaseValidator, Severity, ValidationResult

_AGGR_RE = re.compile(r"\bAggr\s*\(", re.IGNORECASE)
_SET_RE = re.compile(r"\{<", re.IGNORECASE)
_EXPENSIVE_RE = re.compile(r"\b(P|E)\s*\((?!\s*\))", re.IGNORECASE)

_SHEET_WARN_THRESHOLD = 15
_SHEET_ERROR_THRESHOLD = 25
_APP_SHEET_WARN = 30


class PerformanceValidator(BaseValidator):
    """
    Detects expressions and layouts that are known to cause slow render times
    in Qlik Sense: overcrowded sheets, nested Aggr(), P()/E() set functions,
    and multiply-nested set analysis modifiers.
    """

    name = "performance"

    def validate(self, obj: dict[str, Any]) -> list[ValidationResult]:
        obj_type = obj.get("type", "")
        issues = []

        if obj_type == "sheet":
            issues.extend(self._check_sheet_density(obj))
        elif obj_type == "app":
            issues.extend(self._check_app_scale(obj))
        elif obj_type == "measure":
            issues.extend(self._check_expression_complexity(obj))
        elif obj_type == "visualization":
            for m in obj.get("measures", []):
                issues.extend(self._check_expression_complexity(
                    {**m, "id": obj.get("id"), "type": "measure", "name": m.get("label", obj.get("name", ""))}
                ))

        passed = not any(i.severity == Severity.ERROR for i in issues)
        return [ValidationResult(
            validator_name=self.name,
            object_type=obj_type,
            object_id=obj.get("id", ""),
            passed=passed,
            issues=issues,
        )]

    # ── sheet density ─────────────────────────────────────────────────────────

    def _check_sheet_density(self, obj: dict) -> list:
        issues = []
        count = len(obj.get("cells", []))
        if count >= _SHEET_ERROR_THRESHOLD:
            issues.append(self._issue(
                "PERF001", Severity.ERROR,
                f"Sheet has {count} visualizations — this many objects severely impact render time "
                f"(threshold: {_SHEET_ERROR_THRESHOLD})",
                obj, {"viz_count": count},
            ))
        elif count >= _SHEET_WARN_THRESHOLD:
            issues.append(self._issue(
                "PERF001", Severity.WARNING,
                f"Sheet has {count} visualizations — consider splitting into multiple sheets "
                f"(recommended max: {_SHEET_WARN_THRESHOLD})",
                obj, {"viz_count": count},
            ))
        return issues

    # ── app scale ─────────────────────────────────────────────────────────────

    def _check_app_scale(self, obj: dict) -> list:
        issues = []
        sheet_count = obj.get("sheet_count", 0)
        if sheet_count >= _APP_SHEET_WARN:
            issues.append(self._issue(
                "PERF005", Severity.WARNING,
                f"App has {sheet_count} sheets — large apps take longer to open and reload",
                obj, {"sheet_count": sheet_count},
            ))
        return issues

    # ── expression complexity ─────────────────────────────────────────────────

    def _check_expression_complexity(self, obj: dict) -> list:
        issues = []
        expr = obj.get("expression", "")
        if not expr.strip():
            return issues

        aggr_count = len(_AGGR_RE.findall(expr))
        if aggr_count >= 2:
            issues.append(self._issue(
                "PERF002", Severity.WARNING,
                f"Expression contains {aggr_count} Aggr() calls — nested Aggr() is expensive; "
                "consider pre-calculating with a resident load",
                obj, {"expression": expr, "aggr_count": aggr_count},
            ))

        set_count = len(_SET_RE.findall(expr))
        if set_count >= 3:
            issues.append(self._issue(
                "PERF003", Severity.WARNING,
                f"Expression has {set_count} set analysis modifiers — multiple set modifiers "
                "multiply evaluation cost",
                obj, {"expression": expr, "set_count": set_count},
            ))

        if _EXPENSIVE_RE.search(expr):
            issues.append(self._issue(
                "PERF004", Severity.ERROR,
                "Expression uses P() or E() (possible/excluded set functions) — these scan the "
                "full data model and cause severe performance degradation on large datasets",
                obj, {"expression": expr},
            ))

        return issues
