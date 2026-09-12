"""Small client for the Remote Two/3 REST Core-API."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class CoreApiError(RuntimeError):
    """Raised for Core-API communication and response errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CoreClient:
    """Access configured entities and execute entity commands."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 8.0) -> None:
        normalized = base_url.strip().rstrip("/")
        if normalized.endswith("/api"):
            normalized = normalized[:-4]
        self._base_url = normalized
        self._api_key = api_key.strip()
        self._timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def test(self) -> None:
        """Validate URL, connectivity and token."""
        await self.list_entities("media_player,macro")

    async def list_entities(self, entity_types: str = "") -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"page": 1, "limit": 100}
        if entity_types:
            params["entity_types"] = entity_types
        response = await self._request("GET", "/api/entities", params=params)
        data = response.json()
        if not isinstance(data, list):
            raise CoreApiError("Unexpected entity list response")
        return data

    async def get_entity(self, entity_id: str) -> dict[str, Any]:
        safe_id = quote(entity_id, safe="")
        response = await self._request("GET", f"/api/entities/{safe_id}")
        data = response.json()
        if not isinstance(data, dict):
            raise CoreApiError("Unexpected entity response")
        return data

    async def execute(self, entity_id: str, command_id: str) -> None:
        """Execute a command and retry the short macro command for old firmware."""
        safe_id = quote(entity_id, safe="")
        path = f"/api/entities/{safe_id}/command"
        try:
            await self._request("PUT", path, json={"cmd_id": command_id})
        except CoreApiError as error:
            if command_id == "macro.start" and error.status_code in {400, 422}:
                await self._request("PUT", path, json={"cmd_id": "start"})
                return
            raise

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self._base_url or not self._api_key:
            raise CoreApiError("Core-API is not configured")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=self.headers,
                    **kwargs,
                )
        except httpx.TimeoutException as error:
            raise CoreApiError("Core-API request timed out") from error
        except httpx.HTTPError as error:
            raise CoreApiError(f"Core-API connection failed: {error}") from error
        if response.is_error:
            raise CoreApiError(
                f"Core-API returned HTTP {response.status_code}", response.status_code
            )
        return response
