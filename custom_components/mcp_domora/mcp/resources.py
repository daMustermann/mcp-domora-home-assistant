"""MCP resources: read-only snapshots of the instance."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

from homeassistant.helpers import area_registry as ar, device_registry as dr, floor_registry as fr

from ..context import ToolContext
from ..errors import InvalidInput

RESOURCES = [
    {
        "uri": "homeassistant://overview",
        "name": "Home overview",
        "title": "Home overview",
        "description": "Areas, floors and the entities in them, as a compact tree.",
        "mimeType": "application/json",
    },
    {
        "uri": "homeassistant://entities",
        "name": "Entities",
        "title": "All exposed entities",
        "description": "Every entity exposed to MCP clients with its current state.",
        "mimeType": "application/json",
    },
    {
        "uri": "homeassistant://services",
        "name": "Services",
        "title": "Service catalog",
        "description": "Every callable service with its parameter schema.",
        "mimeType": "application/json",
    },
    {
        "uri": "homeassistant://config",
        "name": "Configuration",
        "title": "Core configuration",
        "description": "Location, unit system, version and loaded components.",
        "mimeType": "application/json",
    },
]

TEMPLATES = [
    {
        "uriTemplate": "homeassistant://entity/{entity_id}",
        "name": "Entity",
        "title": "A single entity",
        "description": "State, attributes and registry details for one entity.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "homeassistant://area/{area_id}",
        "name": "Area",
        "title": "A single area",
        "description": "An area with its devices and entities.",
        "mimeType": "application/json",
    },
]


def list_resources() -> list[dict[str, Any]]:
    """Static resources."""
    return RESOURCES


def list_templates() -> list[dict[str, Any]]:
    """Resource templates."""
    return TEMPLATES


async def async_read(context: ToolContext, uri: str) -> dict[str, Any]:
    """Read a resource."""
    if not uri.startswith("homeassistant://"):
        raise InvalidInput(f"Unsupported resource URI: {uri!r}")
    path = uri.removeprefix("homeassistant://")

    from ..tools import states as states_tools  # noqa: PLC0415
    from ..tools import services as services_tools  # noqa: PLC0415
    from ..tools import system as system_tools  # noqa: PLC0415

    match path.split("/", 1):
        case ["overview"]:
            payload = await states_tools.build_overview(context)
        case ["entities"]:
            payload = await states_tools.list_entities(context, {})
        case ["services"]:
            payload = await services_tools.list_services(context, {})
        case ["config"]:
            payload = await system_tools.get_config(context, {})
        case ["entity", entity_id]:
            payload = await states_tools.describe_entity(
                context, {"entity_id": unquote(entity_id)}
            )
        case ["area", area_id]:
            payload = _area_detail(context, unquote(area_id))
        case _:
            raise InvalidInput(f"Unknown resource: {uri!r}")

    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(payload, indent=2, default=str, ensure_ascii=False),
            }
        ]
    }


def _area_detail(context: ToolContext, area_id: str) -> dict[str, Any]:
    """Devices and entities in one area."""
    hass = context.hass
    area = ar.async_get(hass).async_get_area(area_id)
    if area is None:
        raise InvalidInput(f"Unknown area: {area_id!r}")
    floor = fr.async_get(hass).async_get_floor(area.floor_id) if area.floor_id else None
    devices = dr.async_entries_for_area(dr.async_get(hass), area_id)
    return {
        "area_id": area.id,
        "name": area.name,
        "floor": floor.name if floor else None,
        "aliases": sorted(area.aliases),
        "labels": sorted(area.labels),
        "devices": [
            {"device_id": device.id, "name": device.name_by_user or device.name}
            for device in devices
        ],
        "entities": [
            entity_id
            for entity_id in context.exposure.exposed_entity_ids()
            if context.exposure.area_for_entity_id(entity_id) == area_id
        ],
    }
