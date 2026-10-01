"""Diagnostics for the MCP Bridge."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .registry import all_tools


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics, with client identifiers redacted."""
    runtime = hass.data.get(DOMAIN)
    tools = all_tools()
    payload: dict[str, Any] = {
        "options": dict(entry.options),
        "tool_count": len(tools),
        "tools_by_group": {},
    }
    for tool in tools.values():
        payload["tools_by_group"].setdefault(tool.group, []).append(tool.name)

    if runtime is None:
        payload["loaded"] = False
        return payload

    payload["loaded"] = runtime.loaded
    payload["sessions"] = len(runtime.sessions)
    payload["registered_clients"] = [
        {
            "client_name": client.client_name,
            "dynamic": client.dynamic,
            "redirect_uri_count": len(client.redirect_uris),
            "created_at": client.created_at,
        }
        for client in runtime.store.clients.values()
    ]
    payload["active_tokens"] = [
        {
            "client_name": record.client_name,
            "scopes": record.scopes,
            "created_at": record.created_at,
            "last_used": record.last_used,
        }
        for record in runtime.store.tokens.values()
    ]
    return payload
