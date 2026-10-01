"""Tools for reading entities and states."""

from __future__ import annotations

from typing import Any

from homeassistant.core import State, split_entity_id
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)

from ..const import GROUP_STATES
from ..context import ToolContext
from ..errors import InvalidInput
from ..registry import require, tool
from ..schema import array, boolean, entity_id, integer, schema, string

#: Attributes that are noise in list output.
NOISY_ATTRIBUTES = frozenset(
    {
        "friendly_name",
        "icon",
        "entity_picture",
        "supported_features",
        "attribution",
        "device_class",
        "editable",
    }
)


def state_summary(context: ToolContext, state: State, *, attributes: bool = False) -> dict[str, Any]:
    """A compact description of one state."""
    entry = er.async_get(context.hass).async_get(state.entity_id)
    payload: dict[str, Any] = {
        "entity_id": state.entity_id,
        "name": state.name,
        "state": state.state,
        "domain": split_entity_id(state.entity_id)[0],
    }
    if (unit := state.attributes.get("unit_of_measurement")) is not None:
        payload["unit"] = unit
    if (device_class := state.attributes.get("device_class")) is not None:
        payload["device_class"] = device_class
    area_id = context.exposure.area_for_entity_id(state.entity_id)
    if area_id:
        payload["area"] = context.exposure.area_name(area_id)
    if entry is not None and entry.labels:
        payload["labels"] = sorted(entry.labels)
    payload["last_changed"] = state.last_changed.isoformat()
    if attributes:
        payload["attributes"] = {
            key: value
            for key, value in state.attributes.items()
            if key not in NOISY_ATTRIBUTES
        }
    return payload


@tool(
    name="list_entities",
    group=GROUP_STATES,
    title="List entities",
    description="""
Find entities. Every filter is optional and they combine with AND; with no filters
you get everything exposed to you, which can be a lot - prefer filtering by domain
or area. Use `search` for a case-insensitive match on the entity id or friendly name.
""",
    input_schema=schema(
        {
            "domain": string("Only entities in this domain, e.g. `light`."),
            "domains": array("Several domains at once."),
            "area": string("Area name or area id."),
            "label": string("Label name or label id."),
            "device_id": string("Only entities belonging to this device."),
            "state": string("Only entities currently in this state, e.g. `on`."),
            "search": string("Case-insensitive substring match on entity id or name."),
            "include_attributes": boolean(
                "Include each entity's attributes. Verbose; off by default."
            ),
            "limit": integer("Maximum number of entities to return.", minimum=1),
        }
    ),
)
async def list_entities(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List entities matching the given filters."""
    hass = context.hass
    domains = {d.lower() for d in args.get("domains") or []}
    if domain := args.get("domain"):
        domains.add(domain.lower())

    area_id = _resolve_area(context, args.get("area")) if args.get("area") else None
    label_id = _resolve_label(context, args.get("label")) if args.get("label") else None
    device_id = args.get("device_id")
    wanted_state = args.get("state")
    search = (args.get("search") or "").lower()
    include_attributes = bool(args.get("include_attributes"))

    registry = er.async_get(hass)
    results: list[dict[str, Any]] = []
    for state in hass.states.async_all():
        if not context.exposure.is_exposed(state.entity_id):
            continue
        if domains and split_entity_id(state.entity_id)[0] not in domains:
            continue
        if wanted_state is not None and state.state != wanted_state:
            continue
        if search and search not in state.entity_id.lower() and search not in (state.name or "").lower():
            continue

        entry = registry.async_get(state.entity_id)
        if area_id and context.exposure.area_for_entity_id(state.entity_id) != area_id:
            continue
        if label_id and (entry is None or label_id not in entry.labels):
            continue
        if device_id and (entry is None or entry.device_id != device_id):
            continue

        results.append(state_summary(context, state, attributes=include_attributes))

    results.sort(key=lambda item: item["entity_id"])
    total = len(results)
    limited = context.limit(results, args.get("limit"))
    return {
        "count": len(limited),
        "total_matching": total,
        "truncated": len(limited) < total,
        "entities": limited,
    }


@tool(
    name="get_state",
    group=GROUP_STATES,
    title="Get entity state",
    description="""
Read the full state of one or more entities, including all attributes. Use this
before changing anything so you work from real values rather than assumptions.
""",
    input_schema=schema(
        {
            "entity_id": entity_id("A single entity id."),
            "entity_ids": array("Several entity ids at once."),
        }
    ),
)
async def get_state(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Return full states."""
    entity_ids = list(args.get("entity_ids") or [])
    if single := args.get("entity_id"):
        entity_ids.insert(0, single)
    if not entity_ids:
        raise InvalidInput("Provide entity_id or entity_ids")

    context.check_read(*entity_ids)
    states: list[dict[str, Any]] = []
    missing: list[str] = []
    for eid in entity_ids:
        state = context.hass.states.get(eid)
        if state is None:
            missing.append(eid)
            continue
        states.append(
            {
                **state_summary(context, state, attributes=True),
                "last_updated": state.last_updated.isoformat(),
                "context_id": state.context.id,
            }
        )
    payload: dict[str, Any] = {"states": states}
    if missing:
        payload["unknown_entities"] = missing
    return payload


@tool(
    name="describe_entity",
    group=GROUP_STATES,
    title="Describe entity",
    description="""
Everything Home Assistant knows about one entity: its state, its registry entry,
the device and area it belongs to, which integration provides it, and the services
that can act on it. Use this when an entity behaves unexpectedly.
""",
    input_schema=schema({"entity_id": entity_id()}, ["entity_id"]),
)
async def describe_entity(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Describe one entity in depth."""
    (target,) = require(args, "entity_id")
    context.check_read(target)
    hass = context.hass
    state = hass.states.get(target)
    entry = er.async_get(hass).async_get(target)
    domain = split_entity_id(target)[0]

    payload: dict[str, Any] = {
        "entity_id": target,
        "exists": state is not None or entry is not None,
        "domain": domain,
    }
    if state is not None:
        payload["state"] = state.state
        payload["attributes"] = dict(state.attributes)
        payload["last_changed"] = state.last_changed.isoformat()
        payload["last_updated"] = state.last_updated.isoformat()
    else:
        payload["note"] = (
            "No state. The entity is disabled, not yet set up, or defined only in the registry."
        )

    if entry is not None:
        payload["registry"] = {
            "unique_id": entry.unique_id,
            "platform": entry.platform,
            "config_entry_id": entry.config_entry_id,
            "device_id": entry.device_id,
            "area_id": entry.area_id,
            "name": entry.name,
            "original_name": entry.original_name,
            "icon": entry.icon,
            "labels": sorted(entry.labels),
            "entity_category": entry.entity_category,
            "disabled_by": entry.disabled_by,
            "hidden_by": entry.hidden_by,
            "capabilities": entry.capabilities,
            "supported_features": entry.supported_features,
            "options": dict(entry.options) if entry.options else {},
            "editable": True,
        }
        if entry.device_id:
            device = dr.async_get(hass).async_get(entry.device_id)
            if device is not None:
                payload["device"] = _device_summary(context, device)
    else:
        payload["registry"] = None
        payload["registry_note"] = (
            "Not in the entity registry, so it comes from YAML (template, group, ...) "
            "and cannot be renamed or reassigned through the registry tools."
        )

    area_id = context.exposure.area_for_entity_id(target)
    payload["area"] = {"area_id": area_id, "name": context.exposure.area_name(area_id)} if area_id else None
    payload["available_services"] = sorted(
        set(context.hass.services.async_services_for_domain(domain))
        | set(context.hass.services.async_services_for_domain("homeassistant"))
    )
    return payload


@tool(
    name="get_overview",
    group=GROUP_STATES,
    title="Home overview",
    description="""
A compact map of the home: floors, areas, how many entities of each domain sit in
them, and counts of anything unavailable. Start here when you do not yet know what
this instance contains - it is far cheaper than listing every entity.
""",
    input_schema=schema(
        {
            "include_entity_ids": boolean(
                "List the entity ids per area instead of only counting them."
            )
        }
    ),
)
async def get_overview(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Summarise the instance."""
    return await build_overview(context, include_entity_ids=bool(args.get("include_entity_ids")))


async def build_overview(
    context: ToolContext, *, include_entity_ids: bool = False
) -> dict[str, Any]:
    """Build the overview payload (also served as a resource)."""
    hass = context.hass
    area_reg = ar.async_get(hass)
    floor_reg = fr.async_get(hass)

    areas: dict[str | None, dict[str, Any]] = {}
    domain_totals: dict[str, int] = {}
    unavailable: list[str] = []

    for state in hass.states.async_all():
        if not context.exposure.is_exposed(state.entity_id):
            continue
        domain = split_entity_id(state.entity_id)[0]
        domain_totals[domain] = domain_totals.get(domain, 0) + 1
        if state.state in ("unavailable", "unknown"):
            unavailable.append(state.entity_id)

        area_id = context.exposure.area_for_entity_id(state.entity_id)
        bucket = areas.setdefault(
            area_id,
            {
                "area_id": area_id,
                "name": context.exposure.area_name(area_id) or "(no area)",
                "domains": {},
                "entity_count": 0,
                **({"entity_ids": []} if include_entity_ids else {}),
            },
        )
        bucket["domains"][domain] = bucket["domains"].get(domain, 0) + 1
        bucket["entity_count"] += 1
        if include_entity_ids:
            bucket["entity_ids"].append(state.entity_id)

    for area_id, bucket in areas.items():
        if area_id and (area := area_reg.async_get_area(area_id)):
            floor = floor_reg.async_get_floor(area.floor_id) if area.floor_id else None
            bucket["floor"] = floor.name if floor else None

    return {
        "name": hass.config.location_name,
        "version": hass.config.as_dict().get("version"),
        "entity_count": sum(domain_totals.values()),
        "domains": dict(sorted(domain_totals.items(), key=lambda kv: -kv[1])),
        "areas": sorted(areas.values(), key=lambda item: item["name"]),
        "unavailable_count": len(unavailable),
        "unavailable_entities": sorted(unavailable)[:50],
    }


def _device_summary(context: ToolContext, device: dr.DeviceEntry) -> dict[str, Any]:
    """Summarise a device entry."""
    return {
        "device_id": device.id,
        "name": device.name_by_user or device.name,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "sw_version": device.sw_version,
        "hw_version": device.hw_version,
        "area_id": device.area_id,
        "area": context.exposure.area_name(device.area_id),
        "labels": sorted(device.labels),
        "disabled_by": device.disabled_by,
        "via_device_id": device.via_device_id,
        "config_entries": sorted(device.config_entries),
        "connections": [list(connection) for connection in device.connections],
        "identifiers": [list(identifier) for identifier in device.identifiers],
    }


def _resolve_area(context: ToolContext, value: str) -> str:
    """Resolve an area name or id to an area id."""
    registry = ar.async_get(context.hass)
    if registry.async_get_area(value):
        return value
    area = registry.async_get_area_by_name(value)
    if area is None:
        names = sorted(area.name for area in registry.async_list_areas())
        raise InvalidInput(f"Unknown area {value!r}. Known areas: {', '.join(names) or '(none)'}")
    return area.id


def _resolve_label(context: ToolContext, value: str) -> str:
    """Resolve a label name or id to a label id."""
    registry = lr.async_get(context.hass)
    if registry.async_get_label(value):
        return value
    label = registry.async_get_label_by_name(value)
    if label is None:
        names = sorted(label.name for label in registry.async_list_labels())
        raise InvalidInput(f"Unknown label {value!r}. Known labels: {', '.join(names) or '(none)'}")
    return label.label_id
