"""
DataSure Plugin System
======================

To create a custom validator plugin:

    from datasure.plugins import datasure_plugin
    from datasure.validators.base import BaseValidator, Severity, ValidationResult

    @datasure_plugin
    class MyValidator(BaseValidator):
        name = "my_validator"

        def validate(self, obj):
            ...

Distribution options:
  1. Drop the .py file into your configured `plugins_dir` directory.
  2. Package as a Python package and register via setuptools entry_points:

        [options.entry_points]
        datasure.validators =
            my_validator = mypackage.validator:MyValidator
"""

from datasure.validators.base import (  # re-export for plugin authors
    BaseValidator,
    Severity,
    ValidationIssue,
    ValidationResult,
)

__all__ = ["datasure_plugin", "BaseValidator", "Severity", "ValidationIssue", "ValidationResult"]


def datasure_plugin(cls: type) -> type:
    """Decorator that marks a class as a DataSure validator plugin."""
    cls._is_datasure_plugin = True
    return cls
