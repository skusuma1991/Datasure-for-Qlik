from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .base import BaseValidator, Severity, ValidationResult, ValidationIssue

_WHITESPACE = re.compile(r"\s+")
_VARIABLE_EXPANSION = re.compile(r"\$\(([^)]+)\)")


def _normalise(expr: str, variables: dict[str, str] | None = None) -> str:
    """Return a canonical form of an expression for duplicate comparison."""
    text = expr.strip()
    # Expand variables one level
    if variables:
        def _expand(m: re.Match) -> str:
            return variables.get(m.group(1).strip().lower(), m.group(0))
        text = _VARIABLE_EXPANSION.sub(_expand, text)
    # Lowercase, collapse whitespace, remove outer whitespace
    text = _WHITESPACE.sub(" ", text.lower()).strip()
    return text


class DuplicateExpressionValidator(BaseValidator):
    """
    Detects repeated expressions across measures and dimensions.
    Expressions that appear 2+ times are flagged as candidates for
    consolidation into Master Items.

    This validator is stateful: it must be run across the full set of
    app objects at once via `validate_all()`, not object-by-object.
    """

    name = "duplicates"

    def __init__(self) -> None:
        self._variables: dict[str, str] = {}

    def prime(self, variables: list[dict]) -> None:
        for v in variables:
            self._variables[v.get("name", "").lower()] = v.get("definition", "")

    def validate(self, obj: dict[str, Any]) -> list[ValidationResult]:
        # Single-object validation is a no-op — use validate_all() instead.
        return []

    def validate_all(self, objects: list[dict[str, Any]]) -> list[ValidationResult]:
        """Run duplicate detection across the entire object list."""
        # Collect all expressions with their source objects
        expr_sources: dict[str, list[dict]] = defaultdict(list)

        for obj in objects:
            obj_type = obj.get("type", "")
            if obj_type == "measure":
                expr = obj.get("expression", "")
                if expr.strip():
                    key = _normalise(expr, self._variables)
                    expr_sources[key].append(obj)
            elif obj_type == "dimension":
                expr = obj.get("field_def", "")
                if expr.strip():
                    key = _normalise(expr, self._variables)
                    expr_sources[key].append(obj)
            elif obj_type == "visualization":
                for m in obj.get("measures", []):
                    expr = m.get("expression", "")
                    if expr.strip():
                        key = _normalise(expr, self._variables)
                        expr_sources[key].append({**m, "id": obj.get("id"), "type": "measure"})

        results: list[ValidationResult] = []
        for normalised, sources in expr_sources.items():
            if len(sources) < 2:
                continue
            source_ids = [s.get("id", "?") for s in sources]
            source_names = [s.get("name") or s.get("label") or s.get("id", "?") for s in sources]
            original_expr = sources[0].get("expression") or sources[0].get("field_def", "")
            issue = ValidationIssue(
                rule_id="DUP001",
                severity=Severity.WARNING,
                message=(
                    f"Expression appears {len(sources)} times — consider converting to a Master Item"
                ),
                object_type="duplicate_group",
                object_id=source_ids[0],
                object_name=source_names[0],
                detail={
                    "expression": original_expr,
                    "normalised": normalised,
                    "occurrences": len(sources),
                    "source_ids": source_ids,
                    "source_names": source_names,
                },
            )
            results.append(ValidationResult(
                validator_name=self.name,
                object_type="duplicate_group",
                object_id=f"dup:{normalised[:40]}",
                passed=True,  # not a blocking error — advisory
                issues=[issue],
            ))

        return results
