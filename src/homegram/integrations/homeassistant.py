"""Minimal async client for the Home Assistant REST API (long-lived access token)."""

from __future__ import annotations

from typing import Any

import httpx


class HomeAssistantError(Exception):
    """Home Assistant is unreachable or returned an error."""


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

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HomeAssistantError(str(exc) or exc.__class__.__name__) from exc
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
