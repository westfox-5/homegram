"""Minimal async client for the Home Assistant REST API (long-lived access token)."""

from __future__ import annotations

from typing import Any

import httpx

# Config flows may fetch remote resources to validate them (e.g. scrape): allow more time.
FLOW_TIMEOUT = 45.0


class HomeAssistantError(Exception):
    """Home Assistant is unreachable or returned an error."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def forbidden(self) -> bool:
        """The token is valid but lacks permissions (e.g. not an administrator)."""
        return self.status in (401, 403)


class HomeAssistantClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, raw: bool = False, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HomeAssistantError(str(exc), status=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise HomeAssistantError(str(exc) or exc.__class__.__name__) from exc
        if raw:
            return response.text
        return response.json() if response.content else None

    async def ping(self) -> bool:
        data = await self._request("GET", "/api/")
        return isinstance(data, dict) and "message" in data

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        return_response: bool = False,
    ) -> Any:
        path = f"/api/services/{domain}/{service}"
        if return_response:
            path += "?return_response"
        return await self._request("POST", path, json=data)

    # --- todo lists -------------------------------------------------------

    async def todo_items(
        self, entity_id: str, status: str = "needs_action"
    ) -> list[dict[str, Any]]:
        data = await self.call_service(
            "todo",
            "get_items",
            {"entity_id": entity_id, "status": [status]},
            return_response=True,
        )
        try:
            return list(data["service_response"][entity_id]["items"])
        except (KeyError, TypeError) as exc:
            raise HomeAssistantError(f"Unexpected todo.get_items response: {data!r}") from exc

    async def todo_add(self, entity_id: str, item: str) -> None:
        await self.call_service("todo", "add_item", {"entity_id": entity_id, "item": item})

    async def todo_complete(self, entity_id: str, item: str) -> None:
        await self.call_service(
            "todo", "update_item", {"entity_id": entity_id, "item": item, "status": "completed"}
        )

    async def todo_remove_completed(self, entity_id: str) -> None:
        await self.call_service("todo", "remove_completed_items", {"entity_id": entity_id})

    async def services(self) -> list[dict[str, Any]]:
        """Available services, grouped by domain."""
        return await self._request("GET", "/api/services")

    # --- templates ----------------------------------------------------------

    async def render_template(self, template: str) -> str:
        return await self._request("POST", "/api/template", raw=True, json={"template": template})

    # --- config entries (require an administrator token) --------------------

    async def config_flow(self, handler: str, data: dict[str, Any]) -> dict[str, Any]:
        """Start a config flow and submit its first step. Returns the final flow result."""
        flow = await self._request(
            "POST", "/api/config/config_entries/flow", json={"handler": handler}
        )
        return await self._request(
            "POST",
            f"/api/config/config_entries/flow/{flow['flow_id']}",
            json=data,
            timeout=FLOW_TIMEOUT,
        )

    async def subentry_flow(
        self, entry_id: str, subentry_type: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Add a subentry (e.g. a scrape sensor) to a config entry."""
        flow = await self._request(
            "POST",
            "/api/config/config_entries/subentries/flow",
            json={"handler": [entry_id, subentry_type]},
        )
        return await self._request(
            "POST",
            f"/api/config/config_entries/subentries/flow/{flow['flow_id']}",
            json=data,
            timeout=FLOW_TIMEOUT,
        )

    async def delete_config_entry(self, entry_id: str) -> None:
        await self._request("DELETE", f"/api/config/config_entries/entry/{entry_id}")

    # --- automations ----------------------------------------------------------

    async def automation_config(self, automation_id: str) -> dict[str, Any] | None:
        """Config of a UI automation, or None if it does not exist."""
        try:
            return await self._request("GET", f"/api/config/automation/config/{automation_id}")
        except HomeAssistantError as exc:
            if exc.status == 404:
                return None
            raise

    async def save_automation_config(self, automation_id: str, config: dict[str, Any]) -> None:
        await self._request("POST", f"/api/config/automation/config/{automation_id}", json=config)
