"""
Outbound port (ABC) for the API Endpoint Self-Test module.

The runner talks to the running service's real HTTP endpoints only through
this interface, so unit tests can inject a fake (dict-backed) implementation
without bringing up the server or PyTorch.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from app.modules.apitest.domain.entities import SelfTestStatus


class ApiHttpPort(ABC):
    """HTTP verbs required by the self-test runner."""

    @abstractmethod
    async def post_multipart(
        self,
        path: str,
        files: Optional[Dict[str, tuple]],
        data: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
    ) -> Tuple[int, Optional[Any]]:
        """POST multipart/form-data. Returns (http_status, parsed_body)."""

    @abstractmethod
    async def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
    ) -> Tuple[int, Optional[Any]]:
        """GET. Returns (http_status, parsed_body) where body may be a dict,
        a list, or a plain text string (e.g. exported transcripts)."""

    @abstractmethod
    async def delete(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
    ) -> Tuple[int, Optional[Any]]:
        """DELETE. Returns (http_status, parsed_body)."""


class SelfTestStatusRepository(ABC):
    """Persistence of per-card / per-suite pass-fail verification status.

    Only pass/fail + timestamps are stored — no detailed test results.
    """

    @abstractmethod
    def upsert_test(self, suite: str, test_order: int, test_label: str,
                    status: str) -> None:
        """Record the pass/fail verdict of one test card of a suite."""

    @abstractmethod
    def get_tests(self, suite: str) -> Dict[int, SelfTestStatus]:
        """All persisted test cards of a suite, keyed by test order."""

    @abstractmethod
    def upsert_suite(self, suite: str, status: str) -> None:
        """Record the aggregate pass/fail verdict of a whole suite."""

    @abstractmethod
    def get_suite_statuses(self) -> Dict[str, str]:
        """Aggregate status per suite ('passed' | 'failed')."""

    @abstractmethod
    def clear_all(self) -> None:
        """Reset all persisted statuses (used on a new build)."""

    @abstractmethod
    def get_build_stamp(self) -> Optional[str]:
        """Stored build fingerprint, if any."""

    @abstractmethod
    def set_build_stamp(self, stamp: str) -> None:
        """Persist the current build fingerprint."""