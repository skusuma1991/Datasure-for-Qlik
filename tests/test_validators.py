from datasure.validators.syntax import SyntaxValidator
from datasure.validators.data_types import DataTypeValidator
from datasure.validators.base import Severity


class TestSyntaxValidator:
    def setup_method(self):
        self.v = SyntaxValidator()

    def test_app_no_name_is_error(self):
        results = self.v.validate({"type": "app", "id": "a1", "name": ""})
        assert not results[0].passed
        assert any(i.rule_id == "SYN001" for i in results[0].issues)

    def test_app_no_description_is_warning(self):
        results = self.v.validate({"type": "app", "id": "a1", "name": "My App"})
        assert results[0].passed
        assert any(i.severity == Severity.WARNING for i in results[0].issues)

    def test_app_with_name_and_description_passes(self):
        results = self.v.validate({"type": "app", "id": "a1", "name": "My App", "description": "desc"})
        assert results[0].passed
        assert results[0].error_count == 0

    def test_measure_empty_expression_is_error(self):
        results = self.v.validate({"type": "measure", "id": "m1", "expression": "  ", "label": "Rev"})
        assert not results[0].passed
        assert any(i.rule_id == "SYN030" for i in results[0].issues)

    def test_measure_no_label_is_warning(self):
        results = self.v.validate({"type": "measure", "id": "m1", "expression": "Sum(Sales)", "label": ""})
        assert results[0].passed
        assert any(i.rule_id == "SYN032" for i in results[0].issues)

    def test_dimension_empty_field_def_is_error(self):
        results = self.v.validate({"type": "dimension", "id": "d1", "field_def": ""})
        assert not results[0].passed

    def test_sheet_no_cells_is_warning(self):
        results = self.v.validate({"type": "sheet", "id": "s1", "title": "Overview", "cells": []})
        assert any(i.rule_id == "SYN011" for i in results[0].issues)

    def test_visualization_no_type_is_error(self):
        results = self.v.validate({"type": "visualization", "id": "v1", "visualization_type": "", "properties": {}})
        assert not results[0].passed


class TestDataTypeValidator:
    def setup_method(self):
        self.v = DataTypeValidator()

    def test_numeric_measure_with_date_expression_warns(self):
        results = self.v.validate({
            "type": "measure",
            "id": "m1",
            "expression": "Date(OrderDate)",
            "expected_type": "numeric",
        })
        assert any(i.rule_id == "DT001" for i in results[0].issues)

    def test_date_measure_with_numeric_expression_warns(self):
        results = self.v.validate({
            "type": "measure",
            "id": "m2",
            "expression": "Sum(Sales)",
            "expected_type": "date",
        })
        assert any(i.rule_id == "DT002" for i in results[0].issues)

    def test_data_model_dual_tagged_field_emits_info(self):
        results = self.v.validate({
            "type": "data_model",
            "id": "dm1",
            "tables": [
                {
                    "name": "Orders",
                    "fields": [{"name": "OrderDate", "tags": ["$date", "$numeric"]}],
                }
            ],
        })
        assert any(i.rule_id == "DT020" for i in results[0].issues)

    def test_data_model_no_issues_on_clean_model(self):
        results = self.v.validate({
            "type": "data_model",
            "id": "dm2",
            "tables": [
                {
                    "name": "Sales",
                    "fields": [
                        {"name": "Amount", "tags": ["$numeric"]},
                        {"name": "Region", "tags": ["$ascii"]},
                    ],
                }
            ],
        })
        assert results[0].passed
        assert results[0].error_count == 0
