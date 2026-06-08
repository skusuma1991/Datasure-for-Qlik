from __future__ import annotations

from collections import defaultdict
from typing import Any

from .base import BaseValidator, Severity, ValidationResult


class DataModelHealthValidator(BaseValidator):
    """
    Analyses the Qlik data model for structural health issues:
    synthetic keys, circular references, unused fields/tables,
    and field usage coverage.
    """

    name = "data_model_health"

    def validate(self, obj: dict[str, Any]) -> list[ValidationResult]:
        if obj.get("type") != "data_model":
            return []

        issues = []
        issues.extend(self._check_synthetic_keys(obj))
        issues.extend(self._check_circular_references(obj))
        issues.extend(self._check_unused_tables(obj))
        issues.extend(self._check_field_coverage(obj))

        passed = not any(i.severity == Severity.ERROR for i in issues)
        return [ValidationResult(
            validator_name=self.name,
            object_type="data_model",
            object_id=obj.get("id", ""),
            passed=passed,
            issues=issues,
        )]

    # ------------------------------------------------------------------
    # Synthetic key detection
    # Qlik generates synthetic tables named "$Syn1", "$Syn2" etc when two
    # or more tables share more than one common field.
    # ------------------------------------------------------------------
    def _check_synthetic_keys(self, obj: dict[str, Any]) -> list:
        issues = []
        tables = obj.get("tables", [])
        syn_tables = [t for t in tables if t.get("name", "").startswith("$Syn")]
        for st in syn_tables:
            issues.append(self._issue(
                "DM001", Severity.ERROR,
                f"Synthetic key table detected: '{st['name']}' — multiple tables share more than one common field",
                obj,
                {"synthetic_table": st["name"], "fields": [f["name"] for f in st.get("fields", [])]},
            ))
        # Also detect shared multi-field associations without a named syn table
        field_to_tables: dict[str, list[str]] = defaultdict(list)
        for table in tables:
            for field in table.get("fields", []):
                fname = field.get("name", "").lower()
                if not fname.startswith("$"):
                    field_to_tables[fname].append(table.get("name", ""))

        # Find pairs of tables that share 2+ fields
        table_pairs: dict[tuple, list[str]] = defaultdict(list)
        for fname, tnames in field_to_tables.items():
            if len(tnames) >= 2:
                key = tuple(sorted(set(tnames)))
                table_pairs[key].append(fname)

        for tables_key, shared in table_pairs.items():
            if len(shared) >= 2 and not any(t.get("name", "").startswith("$Syn") for t in tables):
                label = " & ".join(f"'{t}'" for t in tables_key)
                issues.append(self._issue(
                    "DM002", Severity.WARNING,
                    f"Tables {label} share {len(shared)} common fields {shared} — may cause a synthetic key",
                    obj,
                    {"tables": list(tables_key), "shared_fields": shared},
                ))
        return issues

    # ------------------------------------------------------------------
    # Circular reference detection
    # Walk the association graph; if any table links back to itself via
    # a path of joins, it's a circular reference.
    # ------------------------------------------------------------------
    def _check_circular_references(self, obj: dict[str, Any]) -> list:
        issues = []
        tables = obj.get("tables", [])

        # Build undirected adjacency via shared key fields
        field_to_tables: dict[str, list[str]] = defaultdict(list)
        for table in tables:
            for field in table.get("fields", []):
                if field.get("is_key"):
                    fname = field.get("name", "").lower()
                    field_to_tables[fname].append(table.get("name", ""))

        adjacency: dict[str, set[str]] = defaultdict(set)
        for tnames in field_to_tables.values():
            for i, t1 in enumerate(tnames):
                for t2 in tnames[i + 1:]:
                    adjacency[t1].add(t2)
                    adjacency[t2].add(t1)

        # DFS cycle detection
        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycle_reported: set[str] = set()

        def dfs(node: str, parent: str | None) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbour in adjacency.get(node, set()):
                if neighbour == parent:
                    continue
                if neighbour not in visited:
                    if dfs(neighbour, node):
                        return True
                elif neighbour in rec_stack:
                    key = tuple(sorted([node, neighbour]))
                    if key not in cycle_reported:
                        cycle_reported.add(key)
                        issues.append(self._issue(
                            "DM010", Severity.ERROR,
                            f"Circular reference detected between tables '{node}' and '{neighbour}'",
                            obj, {"tables": list(key)},
                        ))
                    return True
            rec_stack.discard(node)
            return False

        for table in tables:
            name = table.get("name", "")
            if name not in visited:
                dfs(name, None)

        return issues

    # ------------------------------------------------------------------
    # Unused tables
    # ------------------------------------------------------------------
    def _check_unused_tables(self, obj: dict[str, Any]) -> list:
        issues = []
        tables = obj.get("tables", [])
        used_fields = obj.get("used_fields", set())  # populated by engine if available

        if not used_fields:
            return issues

        for table in tables:
            table_fields = {f.get("name", "").lower() for f in table.get("fields", [])}
            if not table_fields & used_fields:
                issues.append(self._issue(
                    "DM020", Severity.WARNING,
                    f"Table '{table['name']}' has no fields referenced in any app object — consider dropping it",
                    obj, {"table": table["name"], "field_count": len(table_fields)},
                ))
        return issues

    # ------------------------------------------------------------------
    # Field coverage — unused fields
    # ------------------------------------------------------------------
    def _check_field_coverage(self, obj: dict[str, Any]) -> list:
        issues = []
        tables = obj.get("tables", [])
        used_fields = obj.get("used_fields", set())

        if not used_fields:
            return issues

        for table in tables:
            for field in table.get("fields", []):
                fname = field.get("name", "")
                if fname.lower() not in used_fields and not fname.startswith("$") and not field.get("is_key"):
                    issues.append(self._issue(
                        "DM021", Severity.INFO,
                        f"Field '{fname}' in table '{table['name']}' is not used in any expression, dimension, or measure",
                        obj,
                        {"table": table["name"], "field": fname},
                    ))
        return issues
