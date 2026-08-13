"""
Outbound port (ABC) for the API Endpoint Self-Test module.

The runner talks to the running service's real HTTP endpoints only through
this interface, so unit tests can inject a fake (dict-backed) implementation
without bringing up the server or PyTorch.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


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