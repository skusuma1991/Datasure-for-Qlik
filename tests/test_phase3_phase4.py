"""Tests for Phase 3 (performance, load_script, resource_optimization)
and Phase 4 (plugin system)."""

import tempfile
import textwrap
from pathlib import Path

from datasure.validators.base import Severity
from datasure.validators.performance import PerformanceValidator
from datasure.validators.load_script import LoadScriptValidator
from datasure.validators.resource_optimization import ResourceOptimizationValidator


# ── PerformanceValidator ──────────────────────────────────────────────────────

class TestPerformanceValidator:
    def setup_method(self):
        self.v = PerformanceValidator()

    def test_crowded_sheet_warns(self):
        sheet = {"type": "sheet", "id": "s1", "title": "Big", "cells": [{}] * 16}
        results = self.v.validate(sheet)
        assert any(i.rule_id == "PERF001" for r in results for i in r.issues)

    def test_crowded_sheet_errors_above_threshold(self):
        sheet = {"type": "sheet", "id": "s1", "title": "Huge", "cells": [{}] * 26}
        results = self.v.validate(sheet)
        issues = [i for r in results for i in r.issues if i.rule_id == "PERF001"]
        assert issues and issues[0].severity == Severity.ERROR

    def test_small_sheet_passes(self):
        sheet = {"type": "sheet", "id": "s1", "title": "OK", "cells": [{}] * 5}
        results = self.v.validate(sheet)
        assert all(r.passed for r in results)
        assert not any(i.rule_id == "PERF001" for r in results for i in r.issues)

    def test_nested_aggr_warns(self):
        # Two Aggr() calls in one expression — triggers PERF002
        m = {"type": "measure", "id": "m1",
             "expression": "Aggr(Sum(Revenue), Region) + Aggr(Sum(Cost), Region)"}
        results = self.v.validate(m)
        assert any(i.rule_id == "PERF002" for r in results for i in r.issues)

    def test_single_aggr_is_fine(self):
        m = {"type": "measure", "id": "m1", "expression": "Aggr(Sum(Revenue), Region)"}
        results = self.v.validate(m)
        assert not any(i.rule_id == "PERF002" for r in results for i in r.issues)

    def test_p_function_is_error(self):
        m = {"type": "measure", "id": "m1",
             "expression": "Sum({<CustomerID=P({<Region={'North'}>}CustomerID)>}Revenue)"}
        results = self.v.validate(m)
        assert any(i.rule_id == "PERF004" for r in results for i in r.issues)

    def test_app_large_sheet_count_warns(self):
        app = {"type": "app", "id": "app1", "name": "Big App", "sheet_count": 35}
        results = self.v.validate(app)
        assert any(i.rule_id == "PERF005" for r in results for i in r.issues)


# ── LoadScriptValidator ───────────────────────────────────────────────────────

class TestLoadScriptValidator:
    def setup_method(self):
        self.v = LoadScriptValidator()
        # prime with known data model tables
        self.v.prime_context(
            objects=[],
            data_model={"tables": [
                {"name": "FactSales", "fields": []},
                {"name": "DimCustomer", "fields": []},
            ]},
            master_items=[],
            variables=[],
        )

    def test_sql_load_warns(self):
        app = {"type": "app", "id": "a1",
               "load_script": "FactSales: SQL SELECT * FROM sales_table;"}
        results = self.v.validate(app)
        assert any(i.rule_id == "LS002" for r in results for i in r.issues)

    def test_star_load_warns(self):
        app = {"type": "app", "id": "a1",
               "load_script": "// comment\nFactSales: LOAD * FROM [lib://x.qvd] (qvd);"}
        results = self.v.validate(app)
        assert any(i.rule_id == "LS004" for r in results for i in r.issues)

    def test_inline_data_info(self):
        app = {"type": "app", "id": "a1",
               "load_script": "LookupTable:\nLOAD * INLINE [\nID, Name\n1, Alpha\n2, Beta\n];"}
        results = self.v.validate(app)
        assert any(i.rule_id == "LS003" for r in results for i in r.issues)

    def test_orphaned_table_warns(self):
        app = {"type": "app", "id": "a1",
               "load_script": "OrphanedTable:\nLOAD * FROM [x.qvd] (qvd);"}
        results = self.v.validate(app)
        issues = [i for r in results for i in r.issues if i.rule_id == "LS001"]
        assert issues
        assert "orphanedtable" in issues[0].detail.get("table", "")

    def test_known_table_no_orphan_flag(self):
        app = {"type": "app", "id": "a1",
               "load_script": "FactSales:\nLOAD OrderID FROM [x.qvd] (qvd);"}
        results = self.v.validate(app)
        assert not any(i.rule_id == "LS001" for r in results for i in r.issues)

    def test_non_app_object_skipped(self):
        m = {"type": "measure", "id": "m1", "expression": "Sum(Revenue)"}
        assert self.v.validate(m) == []

    def test_app_without_script_skipped(self):
        app = {"type": "app", "id": "a1"}
        assert self.v.validate(app) == []


# ── ResourceOptimizationValidator ────────────────────────────────────────────

class TestResourceOptimizationValidator:
    def setup_method(self):
        self.v = ResourceOptimizationValidator()

    def _run(self, objects):
        dm = next((o for o in objects if o.get("type") == "data_model"), {})
        masters = [o for o in objects if o.get("type") in ("measure","dimension") and o.get("is_master")]
        variables = [o for o in objects if o.get("type") == "variable"]
        self.v.prime_context(objects, dm, masters, variables)
        return self.v.validate_all(objects)

    def test_no_master_measures_warns(self):
        objs = [
            {"type": "measure", "id": f"m{i}", "expression": f"Sum(Field{i})"} for i in range(5)
        ]
        results = self._run(objs)
        assert any(i.rule_id == "RO001" for r in results for i in r.issues)

    def test_with_master_measures_no_ro001(self):
        objs = [
            {"type": "measure", "id": "master", "expression": "Sum(Rev)", "is_master": True},
            {"type": "measure", "id": "m1", "expression": "Sum(Rev)"},
        ]
        results = self._run(objs)
        assert not any(i.rule_id == "RO001" for r in results for i in r.issues)

    def test_unused_variable_flagged(self):
        objs = [
            {"type": "variable", "id": "v1", "name": "vUnused", "definition": "Sum(Revenue)"},
            {"type": "measure",  "id": "m1", "expression": "Count(Region)"},
        ]
        results = self._run(objs)
        assert any(i.rule_id == "RO003" for r in results for i in r.issues)

    def test_used_variable_not_flagged(self):
        objs = [
            {"type": "variable", "id": "v1", "name": "vRev", "definition": "Sum(Revenue)"},
            {"type": "measure",  "id": "m1", "expression": "$(vRev)"},
        ]
        results = self._run(objs)
        assert not any(i.rule_id == "RO003" for r in results for i in r.issues)


# ── Plugin system ─────────────────────────────────────────────────────────────

class TestPluginSystem:
    def test_datasure_plugin_decorator_sets_flag(self):
        from datasure.plugins import datasure_plugin, BaseValidator

        @datasure_plugin
        class MyValidator(BaseValidator):
            name = "test_plugin"
            def validate(self, obj):
                return []

        assert MyValidator._is_datasure_plugin is True

    def test_local_plugin_loads_into_registry(self):
        from datasure.plugins.loader import load_plugins

        plugin_code = textwrap.dedent("""\
            from datasure.plugins import datasure_plugin
            from datasure.validators.base import BaseValidator

            @datasure_plugin
            class DummyPlugin(BaseValidator):
                name = "dummy_plugin_test"
                def validate(self, obj):
                    return []
        """)

        registry = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_path = Path(tmpdir) / "dummy_plugin.py"
            plugin_path.write_text(plugin_code)
            load_plugins(registry, Path(tmpdir))

        assert "dummy_plugin_test" in registry

    def test_naming_convention_example_plugin(self):
        from datasure.plugins.examples.naming_convention import NamingConventionValidator
        v = NamingConventionValidator()
        results = v.validate({"type": "measure", "id": "m1", "name": "TotalRevenue"})
        assert any(i.rule_id == "NC001" for r in results for i in r.issues)

    def test_naming_convention_pass_with_prefix(self):
        from datasure.plugins.examples.naming_convention import NamingConventionValidator
        v = NamingConventionValidator()
        results = v.validate({"type": "measure", "id": "m1", "name": "m_TotalRevenue"})
        assert all(r.passed for r in results)
        assert not any(i.rule_id == "NC001" for r in results for i in r.issues)
