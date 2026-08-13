"""
HttpxSelfClient — outbound adapter that calls the running service's own HTTP API.

Performs real HTTP round-trips against `http://127.0.0.1:{PORT}` so the full
request stack is exercised: the upload-rejection middleware, multipart parsing,
file validation, response-model serialization, and auth dependencies.

The API key is injected as the `x-api-key` header on every request the runner
makes, mirroring exactly what an external API consumer would send.
"""

from typing import Any, Dict, Optional, Tuple

import httpx

from app.modules.apitest.domain.ports import ApiHttpPort


class HttpxSelfClient(ApiHttpPort):
    """ApiHttpPort adapter backed by httpx.AsyncClient."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def _headers(self, headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        merged = dict(headers or {})
        if self._api_key:
            merged.setdefault("x-api-key", self._api_key)
        return merged

    @staticmethod
    def _maybe_json(response: httpx.Response) -> Any:
        ctype = response.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                return response.json()
            except ValueError:
                return response.text
        return response.text

    async def post_multipart(
        self,
        path: str,
        files: Optional[Dict[str, tuple]] = None,
        data: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
    ) -> Tuple[int, Optional[Any]]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=timeout) as client:
            resp = await client.post(path, files=files, data=data, headers=self._headers(headers))
            return resp.status_code, self._maybe_json(resp)

    async def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
    ) -> Tuple[int, Optional[Any]]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=timeout) as client:
            resp = await client.get(path, headers=self._headers(headers))
            return resp.status_code, self._maybe_json(resp)

    async def delete(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
    ) -> Tuple[int, Optional[Any]]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=timeout) as client:
            resp = await client.delete(path, headers=self._headers(headers))
            return resp.status_code, self._maybe_json(resp)