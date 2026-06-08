from __future__ import annotations

import re
from typing import Any

from .base import BaseValidator, Severity, ValidationResult

# Matches bare field names, [Quoted Field Names], and set modifiers like {<Field={'value'}>}
_FIELD_REF = re.compile(r"\[([^\]]+)\]|(?<!['\"\w])([A-Za-z_]\w*(?:\s+\w+)*)(?!['\"\w(])")
_SET_FIELD = re.compile(r"<\s*([A-Za-z_\[][^\]>=,\s]*\]?)\s*[=,{>]")
_VARIABLE_EXPANSION = re.compile(r"\$\(([^)]+)\)")

# Qlik built-in field names that should not be flagged as missing
_QLIK_BUILTINS = {
    "qrowno", "qno", "rowno", "_qrowno", "tableno", "fieldno",
    "fieldname", "fieldvalue", "nooftables", "nooffields", "noofrows",
}

# Common Qlik aggregation/function names — not field refs
_QLIK_FUNCTIONS = {
    "sum", "avg", "min", "max", "count", "only", "concat", "firstvalue",
    "lastvalue", "minstring", "maxstring", "mode", "stdev", "median",
    "fractile", "skew", "kurtosis", "correl", "date", "time", "timestamp",
    "year", "month", "day", "hour", "minute", "second", "week", "weekday",
    "if", "pick", "match", "wildmatch", "mixmatch", "isnull", "isnum",
    "istext", "len", "left", "right", "mid", "upper", "lower", "trim",
    "num", "text", "dual", "chr", "ord", "index", "keepchar", "purgechar",
    "subfield", "substringcount", "fieldvalue", "fieldindex", "getfieldselections",
    "getselectedcount", "getpossiblecount", "getexcludedcount", "getnotselectedcount",
    "aggr", "total", "above", "below", "top", "bottom", "before", "after",
    "rowno", "columnno", "dimensionality", "secondarydimensionality",
    "class", "interval", "floor", "ceil", "round", "fabs", "sign",
    "sqrt", "log", "log10", "exp", "pow", "sin", "cos", "tan",
    "p", "e", "pi", "null", "true", "false",
    "p", "e", "today", "now", "localtime", "maketime", "makedate",
    "addmonths", "addyears", "networkdays", "yeartodate", "lunarweek",
    "set", "let", "load", "select", "from", "where", "group", "by",
    "order", "asc", "desc", "as", "and", "or", "not", "in",
}


def _extract_field_refs(expr: str) -> set[str]:
    """Extract candidate field names from an expression."""
    refs: set[str] = set()
    # Quoted field names are always field refs
    for match in re.finditer(r"\[([^\]]+)\]", expr):
        refs.add(match.group(1).lower())
    # Unquoted identifiers: must be a complete word (followed by non-word or end)
    # and NOT immediately followed by optional whitespace + '(' (which would be a function call).
    # The (?=\W|$) anchor prevents partial backtracking matches like 'su' from 'Sum('.
    for match in re.finditer(r"(?<!['\"\w.\[])([A-Za-z_]\w*)(?=\W|$)(?!\s*\()", expr):
        name = match.group(1).lower()
        if name not in _QLIK_FUNCTIONS and name not in _QLIK_BUILTINS and len(name) > 1:
            refs.add(name)
    return refs


def _extract_set_fields(expr: str) -> set[str]:
    """Extract field names used inside set modifiers."""
    refs: set[str] = set()
    for match in _SET_FIELD.finditer(expr):
        raw = match.group(1).strip().strip("[]").lower()
        if raw:
            refs.add(raw)
    return refs


class FieldIntegrityValidator(BaseValidator):
    """
    Validates that expressions reference fields that actually exist in the data model.
    Also checks for key fields used in expressions, set analysis field refs, and
    variable-expanded expression references.
    """

    name = "field_integrity"

    def __init__(self) -> None:
        self._known_fields: set[str] = set()
        self._key_fields: set[str] = set()
        self._master_items: dict[str, str] = {}  # id -> name
        self._variables: dict[str, str] = {}     # name -> expression

    def prime_context(self, objects, data_model, master_items, variables) -> None:
        self.prime(data_model, master_items, variables)

    def prime(self, data_model: dict[str, Any], master_items: list[dict], variables: list[dict]) -> None:
        """Supply the app's data model context before validate() calls."""
        for table in data_model.get("tables", []):
            for field in table.get("fields", []):
                name = field.get("name", "").lower()
                self._known_fields.add(name)
                if field.get("is_key"):
                    self._key_fields.add(name)
        for mi in master_items:
            self._master_items[mi.get("id", "")] = mi.get("name", "")
        for v in variables:
            self._variables[v.get("name", "").lower()] = v.get("definition", "")

    def validate(self, obj: dict[str, Any]) -> list[ValidationResult]:
        issues = []
        obj_type = obj.get("type", "unknown")
        obj_id = obj.get("id", "")

        if obj_type in ("measure", "dimension"):
            issues.extend(self._check_expression(obj))
        elif obj_type == "visualization":
            for measure in obj.get("measures", []):
                issues.extend(self._check_expression({**measure, "id": obj_id, "type": "measure"}))
            for dim in obj.get("dimensions", []):
                issues.extend(self._check_expression({**dim, "id": obj_id, "type": "dimension"}))

        passed = not any(i.severity == Severity.ERROR for i in issues)
        return [ValidationResult(
            validator_name=self.name,
            object_type=obj_type,
            object_id=obj_id,
            passed=passed,
            issues=issues,
        )]

    def _check_expression(self, obj: dict[str, Any]) -> list:
        issues = []
        raw_expr = obj.get("expression") or obj.get("field_def") or ""
        if not raw_expr.strip():
            return issues

        # Resolve variable expansions
        expr = self._expand_variables(raw_expr)

        if self._known_fields:
            # Check for missing field refs
            refs = _extract_field_refs(expr)
            for ref in refs:
                if ref not in self._known_fields and ref not in _QLIK_FUNCTIONS:
                    issues.append(self._issue(
                        "FI001", Severity.ERROR,
                        f"Expression references unknown field '{ref}'",
                        obj, {"expression": raw_expr, "field": ref},
                    ))

            # Check for key fields in expressions
            set_fields = _extract_set_fields(expr)
            for ref in refs - set_fields:
                if ref in self._key_fields:
                    issues.append(self._issue(
                        "FI002", Severity.WARNING,
                        f"Expression uses key field '{ref}' directly — prefer a descriptive field",
                        obj, {"expression": raw_expr, "field": ref},
                    ))

            # Check set modifier field references
            for ref in set_fields:
                if ref not in self._known_fields:
                    issues.append(self._issue(
                        "FI003", Severity.ERROR,
                        f"Set modifier references unknown field '{ref}'",
                        obj, {"expression": raw_expr, "field": ref},
                    ))

        # Check broken master item reference
        master_ref = obj.get("master_item_id")
        if master_ref and master_ref not in self._master_items:
            issues.append(self._issue(
                "FI010", Severity.ERROR,
                f"References deleted or missing master item (id={master_ref})",
                obj,
            ))

        return issues

    def _expand_variables(self, expr: str) -> str:
        """Replace $(varName) with the variable's definition (one level deep)."""
        def replacer(m: re.Match) -> str:
            var_name = m.group(1).strip().lower()
            return self._variables.get(var_name, m.group(0))
        return _VARIABLE_EXPANSION.sub(replacer, expr)
