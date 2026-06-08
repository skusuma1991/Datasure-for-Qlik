from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    rule_id: str
    severity: Severity
    message: str
    object_type: str
    object_id: str
    object_name: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    validator_name: str
    object_type: str
    object_id: str
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)


class BaseValidator(ABC):
    name: str = "base"

    @abstractmethod
    def validate(self, obj: dict[str, Any]) -> list[ValidationResult]:
        """Run validation against a platform object dict and return results."""

    def _issue(
        self,
        rule_id: str,
        severity: Severity,
        message: str,
        obj: dict[str, Any],
        detail: dict[str, Any] | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            rule_id=rule_id,
            severity=severity,
            message=message,
            object_type=obj.get("type", "unknown"),
            object_id=obj.get("id", ""),
            object_name=obj.get("name", ""),
            detail=detail or {},
        )
