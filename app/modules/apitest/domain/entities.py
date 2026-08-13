"""
Pure-Python domain dataclasses for the API Endpoint Self-Test module.

No framework imports here: these are plain data carriers used by the
reporting surface (FastAPI router) and the unit tests alike.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class InputParam:
    """A single piece of input sent to an endpoint under test."""

    name: str
    value: Any = None
    kind: str = "field"  # 'field' | 'file' | 'header'


@dataclass
class FieldCheck:
    """Pass/fail verdict for a single response field."""

    name: str
    expected_type: str
    present: bool
    passed: bool
    actual_value: Any = None
    note: str = ""


@dataclass
class EndpointTest:
    """Result of exercising one API endpoint (or one step of an async flow)."""

    method: str
    path: str
    name_th: str
    status_code: int
    passed: bool
    elapsed_sec: float = 0.0
    inputs: List[InputParam] = field(default_factory=list)
    field_checks: List[FieldCheck] = field(default_factory=list)
    error_msg: str = ""
    order: int = 0

    @property
    def failed_field_count(self) -> int:
        return sum(1 for c in self.field_checks if not c.passed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order": self.order,
            "method": self.method,
            "path": self.path,
            "name_th": self.name_th,
            "status_code": self.status_code,
            "passed": self.passed,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "inputs": [
                {"name": i.name, "kind": i.kind, "value": i.value} for i in self.inputs
            ],
            "field_checks": [
                {
                    "name": c.name,
                    "type": c.expected_type,
                    "present": c.present,
                    "passed": c.passed,
                    "value": c.actual_value,
                    "note": c.note,
                }
                for c in self.field_checks
            ],
            "error_msg": self.error_msg,
        }


@dataclass
class ApiTestReport:
    """Aggregate of all EndpointTest results produced by a single run."""

    tests: List[EndpointTest] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    @property
    def total(self) -> int:
        return len(self.tests)

    @property
    def passed_count(self) -> int:
        return sum(1 for t in self.tests if t.passed)

    @property
    def failed_count(self) -> int:
        return self.total - self.passed_count

    @property
    def overall_passed(self) -> bool:
        return self.total > 0 and self.failed_count == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "overall_passed": self.overall_passed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "tests": [t.to_dict() for t in self.tests],
        }