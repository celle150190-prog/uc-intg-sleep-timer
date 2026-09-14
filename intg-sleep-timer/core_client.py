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
        await self.list_entities()

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

    async def get_activity(self, entity_id: str) -> dict[str, Any]:
        """Load a complete activity including its current sequence state."""
        safe_id = quote(entity_id, safe="")
        response = await self._request("GET", f"/api/activities/{safe_id}")
        data = response.json()
        if not isinstance(data, dict):
            raise CoreApiError("Unexpected activity response")
        return data

    async def list_active_activities(self) -> list[dict[str, Any]]:
        """Return activities which are currently on and can be switched off."""
        overviews = await self.list_entities("activity")
        active: list[dict[str, Any]] = []
        for overview in overviews:
            entity_id = str(overview.get("entity_id", "")).strip()
            if not entity_id:
                continue
            activity = overview
            if not self._sequence_state(activity):
                activity = await self.get_activity(entity_id)
            features = {
                str(feature).casefold()
                for feature in activity.get("features", [])
                if feature
            }
            if self._sequence_state(activity) == "ON" and "on_off" in features:
                active.append(activity)
        return active

    @staticmethod
    def _sequence_state(entity: dict[str, Any]) -> str:
        attributes = entity.get("attributes")
        if isinstance(attributes, dict):
            state = attributes.get("state")
            if state:
                return str(state).strip().upper()
        return str(entity.get("state", "")).strip().upper()

    async def find_configured_entity(
        self, local_entity_id: str, entity_type: str
    ) -> str:
        """Resolve an integration-local entity identifier to its Core identifier."""
        entities = await self.list_entities(entity_type)
        suffix = f".{local_entity_id}"
        matches = [
            str(item.get("entity_id", ""))
            for item in entities
            if item.get("entity_type") == entity_type
            and (
                item.get("entity_id") == local_entity_id
                or str(item.get("entity_id", "")).endswith(suffix)
            )
        ]
        if len(matches) != 1:
            raise CoreApiError(
                f"Configured {entity_type} entity not found: {local_entity_id}"
            )
        return matches[0]

    async def upsert_remote_ui_page(self, entity_id: str, page: dict[str, Any]) -> str:
        """Create or replace one embedded UI page of a remote entity."""
        safe_id = quote(entity_id, safe="")
        path = f"/api/remotes/{safe_id}/ui/pages"
        response = await self._request("GET", path)
        pages = response.json()
        if not isinstance(pages, list):
            raise CoreApiError("Unexpected remote UI response")

        desired_page_id = str(page.get("page_id", ""))
        desired_name = str(page.get("name", ""))
        payload = {key: value for key, value in page.items() if key != "page_id"}
        current = next(
            (
                item
                for item in pages
                if item.get("page_id") == desired_page_id
                or (desired_name and item.get("name") == desired_name)
            ),
            None,
        )
        if current:
            current_page_id = str(current.get("page_id", ""))
            if not current_page_id:
                raise CoreApiError("Remote UI page has no identifier")
            safe_page_id = quote(current_page_id, safe="")
            await self._request("PATCH", f"{path}/{safe_page_id}", json=payload)
            return current_page_id

        response = await self._request("POST", path, json=payload)
        result = response.json()
        if not isinstance(result, dict) or not result.get("page_id"):
            raise CoreApiError("Unexpected create remote UI page response")
        return str(result["page_id"])

    async def execute(self, entity_id: str, command_id: str) -> None:
        """Execute a Core command, with a compatibility fallback for old firmware."""
        safe_id = quote(entity_id, safe="")
        path = f"/api/entities/{safe_id}/command"
        try:
            await self._request("PUT", path, json={"cmd_id": command_id})
        except CoreApiError as error:
            short_command = command_id.rsplit(".", 1)[-1]
            if short_command != command_id and error.status_code in {400, 404, 422}:
                await self._request("PUT", path, json={"cmd_id": short_command})
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
