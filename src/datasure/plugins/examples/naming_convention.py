"""
Example DataSure plugin: naming convention validator.

This plugin checks that measures, dimensions, and variables follow
a naming convention with known prefixes. It is provided as a starter
template — edit the prefix rules to match your team's conventions.

To activate:
  1. Copy this file to your plugins_dir (set in config.yaml).
  2. Add "naming_convention" to enabled_modules in your config.yaml.

Or package it:
  [options.entry_points]
  datasure.validators =
      naming_convention = datasure.plugins.examples.naming_convention:NamingConventionValidator
"""

from datasure.plugins import datasure_plugin
from datasure.validators.base import BaseValidator, Severity, ValidationResult

_RULES: dict[str, tuple[str, ...]] = {
    "measure":   ("m_", "meas_", "kpi_", "calc_"),
    "dimension": ("d_", "dim_", "hier_"),
    "variable":  ("v_", "var_", "cfg_"),
}


@datasure_plugin
class NamingConventionValidator(BaseValidator):
    """
    Enforces naming prefix conventions on measures, dimensions, and variables.
    Rule NC001 fires as INFO so it never blocks a pipeline but shows in reports.
    """

    name = "naming_convention"

    def validate(self, obj):
        obj_type = obj.get("type", "")
        if obj_type not in _RULES:
            return []

        name = obj.get("name", "")
        prefixes = _RULES[obj_type]
        if any(name.lower().startswith(p) for p in prefixes):
            return [ValidationResult(
                validator_name=self.name,
                object_type=obj_type,
                object_id=obj.get("id", ""),
                passed=True,
                issues=[],
            )]

        issue = self._issue(
            "NC001",
            Severity.INFO,
            f"{obj_type.title()} '{name}' does not follow naming conventions — "
            f"expected one of: {', '.join(prefixes)}",
            obj,
            {"expected_prefixes": list(prefixes)},
        )
        return [ValidationResult(
            validator_name=self.name,
            object_type=obj_type,
            object_id=obj.get("id", ""),
            passed=True,
            issues=[issue],
        )]
