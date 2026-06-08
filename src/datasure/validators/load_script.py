from __future__ import annotations

import re
from typing import Any

from .base import BaseValidator, Severity, ValidationResult

# Table name definitions: "TableName:" at start of logical line
_TABLE_DEF = re.compile(r"^\s*([A-Za-z_]\w*)\s*:", re.MULTILINE)
# Direct SQL without QVD layer
_SQL_SELECT = re.compile(r"\bSQL\s+SELECT\b", re.IGNORECASE)
# INLINE data blocks
_INLINE = re.compile(r"\bINLINE\s*\[", re.IGNORECASE)
# Count rows inside an INLINE block
_INLINE_BLOCK = re.compile(r"\bINLINE\s*\[(.*?)\]", re.IGNORECASE | re.DOTALL)
# LOAD * FROM — star load (fragile, loads all columns)
_STAR_LOAD = re.compile(r"\bLOAD\s+\*\s+FROM\b", re.IGNORECASE)
# Resident load
_RESIDENT = re.compile(r"\bLOAD\b.+?\bRESIDENT\s+(\w+)\b", re.IGNORECASE | re.DOTALL)
# Any comment line
_COMMENT = re.compile(r"^\s*//", re.MULTILINE)
# Script section separator (tab sheets in Qlik)
_SECTION = re.compile(r"^//\s*\$tab\b", re.MULTILINE | re.IGNORECASE)

_INLINE_ROW_WARN = 20


def _strip_comments(script: str) -> str:
    return re.sub(r"//.*", "", script)


def _count_inline_rows(block: str) -> int:
    lines = [l for l in block.strip().splitlines() if l.strip()]
    return max(0, len(lines) - 1)  # first line is header


class LoadScriptValidator(BaseValidator):
    """
    Analyses the Qlik load script for common anti-patterns:
    direct SQL loads, INLINE data in production, star LOADs, and
    tables that are defined but never appear in the data model.

    Runs on 'app' objects that carry a 'load_script' field.
    The validator is primed with data model table names so it can
    detect orphaned (never-linked) script tables.
    """

    name = "load_script"

    def __init__(self) -> None:
        self._model_tables: set[str] = set()

    def prime_context(self, objects, data_model, master_items, variables) -> None:
        for table in data_model.get("tables", []):
            self._model_tables.add(table.get("name", "").lower())

    def validate(self, obj: dict[str, Any]) -> list[ValidationResult]:
        if obj.get("type") != "app":
            return []

        script = obj.get("load_script", "")
        if not script or not script.strip():
            return []

        issues = []
        issues.extend(self._check_sql_loads(obj, script))
        issues.extend(self._check_inline_data(obj, script))
        issues.extend(self._check_star_loads(obj, script))
        issues.extend(self._check_orphaned_tables(obj, script))
        issues.extend(self._check_documentation(obj, script))

        passed = not any(i.severity == Severity.ERROR for i in issues)
        return [ValidationResult(
            validator_name=self.name,
            object_type="app",
            object_id=obj.get("id", ""),
            passed=passed,
            issues=issues,
        )]

    # ── checks ────────────────────────────────────────────────────────────────

    def _check_sql_loads(self, obj: dict, script: str) -> list:
        issues = []
        clean = _strip_comments(script)
        matches = list(_SQL_SELECT.finditer(clean))
        if matches:
            issues.append(self._issue(
                "LS002", Severity.WARNING,
                f"Load script contains {len(matches)} direct SQL SELECT statement(s) — "
                "direct DB loads skip the QVD layer and reload from source every time; "
                "consider loading to QVD first then LOAD from QVD",
                obj, {"count": len(matches)},
            ))
        return issues

    def _check_inline_data(self, obj: dict, script: str) -> list:
        issues = []
        clean = _strip_comments(script)
        for m in _INLINE_BLOCK.finditer(clean):
            rows = _count_inline_rows(m.group(1))
            if rows > _INLINE_ROW_WARN:
                issues.append(self._issue(
                    "LS003", Severity.WARNING,
                    f"INLINE data block has {rows} rows — large INLINE blocks are not scalable; "
                    "move data to a QVD or file",
                    obj, {"rows": rows},
                ))
            elif rows > 0:
                issues.append(self._issue(
                    "LS003", Severity.INFO,
                    f"INLINE data block detected ({rows} rows) — acceptable for lookup tables "
                    "but consider externalising if data changes frequently",
                    obj, {"rows": rows},
                ))
        return issues

    def _check_star_loads(self, obj: dict, script: str) -> list:
        issues = []
        clean = _strip_comments(script)
        matches = list(_STAR_LOAD.finditer(clean))
        if matches:
            issues.append(self._issue(
                "LS004", Severity.WARNING,
                f"Load script uses LOAD * FROM in {len(matches)} place(s) — star loads are "
                "fragile (schema changes break the app silently); explicitly list fields",
                obj, {"count": len(matches)},
            ))
        return issues

    def _check_orphaned_tables(self, obj: dict, script: str) -> list:
        issues = []
        if not self._model_tables:
            return issues
        clean = _strip_comments(script)
        script_tables = {m.group(1).lower() for m in _TABLE_DEF.finditer(clean)}
        # Filter out Qlik reserved keywords that look like table definitions
        _KEYWORDS = {"set", "let", "if", "end", "sub", "call", "exit", "for", "next", "do", "loop"}
        script_tables -= _KEYWORDS
        orphaned = script_tables - self._model_tables
        for table in sorted(orphaned):
            issues.append(self._issue(
                "LS001", Severity.WARNING,
                f"Table '{table}' is defined in the load script but does not appear in the "
                "data model — it may be an orphaned staging table consuming memory",
                obj, {"table": table},
            ))
        return issues

    def _check_documentation(self, obj: dict, script: str) -> list:
        issues = []
        sections = _SECTION.split(script)
        undocumented = 0
        for section in sections:
            lines = [l for l in section.splitlines() if l.strip()]
            if lines and not _COMMENT.search(section):
                undocumented += 1
        if undocumented > 0:
            issues.append(self._issue(
                "LS005", Severity.INFO,
                f"{undocumented} load script section(s) have no comments — "
                "add // comments to explain data sources and transformation logic",
                obj, {"undocumented_sections": undocumented},
            ))
        return issues
