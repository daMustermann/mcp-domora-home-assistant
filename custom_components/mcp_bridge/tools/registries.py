"""Tools for the area, floor, label, device and entity registries."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)

from ..const import GROUP_REGISTRY
from ..context import ToolContext
from ..errors import InvalidInput
from ..registry import require, tool
from ..schema import array, boolean, obj, schema, string


@tool(
    name="list_areas",
    group=GROUP_REGISTRY,
    title="List areas, floors and labels",
    description="""
The organisational structure of the home: floors, the areas on them, and the labels
in use. Area and label ids are what the other tools and service targets expect, and
they are not the same as the display names.
""",
    input_schema=schema({"include_entities": boolean("List the entities in each area.")}),
)
async def list_areas(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List areas, floors and labels."""
    hass = context.hass
    include_entities = bool(args.get("include_entities"))
    area_reg = ar.async_get(hass)
    device_reg = dr.async_get(hass)

    areas = []
    for area in area_reg.async_list_areas():
        entry: dict[str, Any] = {
            "area_id": area.id,
            "name": area.name,
            "floor_id": area.floor_id,
            "icon": area.icon,
            "aliases": sorted(area.aliases),
            "labels": sorted(area.labels),
            "device_count": len(dr.async_entries_for_area(device_reg, area.id)),
        }
        if include_entities:
            entry["entities"] = [
                entity_id
                for entity_id in context.exposure.exposed_entity_ids()
                if context.exposure.area_for_entity_id(entity_id) == area.id
            ]
        areas.append(entry)

    return {
        "floors": [
            {
                "floor_id": floor.floor_id,
                "name": floor.name,
                "level": floor.level,
                "icon": floor.icon,
                "aliases": sorted(floor.aliases),
            }
            for floor in fr.async_get(hass).async_list_floors()
        ],
        "areas": sorted(areas, key=lambda item: item["name"]),
        "labels": [
            {
                "label_id": label.label_id,
                "name": label.name,
                "color": label.color,
                "icon": label.icon,
                "description": label.description,
            }
            for label in lr.async_get(hass).async_list_labels()
        ],
    }


@tool(
    name="manage_area",
    group=GROUP_REGISTRY,
    title="Create, update or delete an area",
    description="""
Manage areas. `create` needs a name; `update` and `delete` need an area_id. Deleting
an area does not delete the devices in it, it only unassigns them.

Aliases matter for voice control: an alias is an alternative name the user can speak.
""",
    input_schema=schema(
        {
            "action": string("create | update | delete"),
            "area_id": string("The area to update or delete."),
            "name": string("The area's name."),
            "floor_id": string("Which floor the area is on."),
            "icon": string("An mdi icon."),
            "aliases": array("Alternative spoken names."),
            "labels": array("Label ids to apply."),
        },
        ["action"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def manage_area(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create, update or delete an area."""
    return await _manage(
        context,
        args,
        command="config/area_registry",
        id_key="area_id",
        fields=("name", "floor_id", "icon", "aliases", "labels"),
    )


@tool(
    name="manage_floor",
    group=GROUP_REGISTRY,
    title="Create, update or delete a floor",
    description="Manage floors. `create` needs a name; `level` orders them (ground floor is 0).",
    input_schema=schema(
        {
            "action": string("create | update | delete"),
            "floor_id": string("The floor to update or delete."),
            "name": string("The floor's name."),
            "level": obj("Storey number; 0 is the ground floor."),
            "icon": string("An mdi icon."),
            "aliases": array("Alternative spoken names."),
        },
        ["action"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def manage_floor(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create, update or delete a floor."""
    return await _manage(
        context,
        args,
        command="config/floor_registry",
        id_key="floor_id",
        fields=("name", "level", "icon", "aliases"),
    )


@tool(
    name="manage_label",
    group=GROUP_REGISTRY,
    title="Create, update or delete a label",
    description="""
Manage labels. Labels cut across areas - "battery powered", "holiday lighting",
"critical" - and can be used as a service target, so one call reaches everything
carrying the label.
""",
    input_schema=schema(
        {
            "action": string("create | update | delete"),
            "label_id": string("The label to update or delete."),
            "name": string("The label's name."),
            "icon": string("An mdi icon."),
            "color": string("A theme colour name, e.g. `red`."),
            "description": string("What the label means."),
        },
        ["action"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def manage_label(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create, update or delete a label."""
    return await _manage(
        context,
        args,
        command="config/label_registry",
        id_key="label_id",
        fields=("name", "icon", "color", "description"),
    )


@tool(
    name="list_devices",
    group=GROUP_REGISTRY,
    title="List devices",
    description="""
Physical devices and the entities they provide. Use this when a request is about a
thing rather than a reading - one device usually owns several entities, and device
ids are what `list_device_automations` and device-targeted service calls need.
""",
    input_schema=schema(
        {
            "search": string("Case-insensitive match on name, manufacturer or model."),
            "area": string("Only devices in this area id."),
            "integration": string("Only devices from this integration domain."),
            "include_entities": boolean("List each device's entities. Default true.", default=True),
            "disabled_only": boolean("Only disabled devices."),
        }
    ),
)
async def list_devices(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List devices."""
    from .states import _device_summary  # noqa: PLC0415

    hass = context.hass
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)
    search = (args.get("search") or "").lower()
    area = args.get("area")
    integration = args.get("integration")
    include_entities = args.get("include_entities", True)

    results = []
    # Iterating the registry yields the entries; `.values()` is deprecated.
    for device in device_reg.devices:
        if area and device.area_id != area:
            continue
        if args.get("disabled_only") and not device.disabled_by:
            continue
        text = (
            f"{device.name_by_user or ''} {device.name or ''} "
            f"{getattr(device, 'manufacturer', None) or ''} "
            f"{getattr(device, 'model', None) or ''}"
        ).lower()
        if search and search not in text:
            continue

        entry = _device_summary(context, device)
        if integration:
            domains = {
                config_entry.domain
                for entry_id in ([device.config_entry_id] if device.config_entry_id else [])
                if (config_entry := hass.config_entries.async_get_entry(entry_id))
            }
            if integration not in domains:
                continue
            entry["integrations"] = sorted(domains)
        if include_entities:
            entry["entities"] = [
                item.entity_id
                for item in er.async_entries_for_device(
                    entity_reg, device.id, include_disabled_entities=True
                )
                if context.exposure.is_exposed(item.entity_id)
            ]
        results.append(entry)

    results.sort(key=lambda item: (item["name"] or "").lower())
    total = len(results)
    limited = context.limit(results)
    return {
        "count": len(limited),
        "total_matching": total,
        "truncated": len(limited) < total,
        "devices": limited,
    }


@tool(
    name="update_device",
    group=GROUP_REGISTRY,
    title="Update a device",
    description="""
Rename a device, move it to an area, label it, or disable it. Renaming a device can
rename its entities too - Home Assistant asks about that in the UI; here the entity
ids are left alone, so rename entities separately with `update_entity` if you want
their ids to match.
""",
    input_schema=schema(
        {
            "device_id": string("The device to update."),
            "name_by_user": string("A user-visible name that overrides the device's own."),
            "area_id": string("Move the device to this area."),
            "labels": array("Replace the device's labels with these label ids."),
            "disabled_by": string("Set to `user` to disable, or null to re-enable."),
        },
        ["device_id"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def update_device(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Update a device."""
    (device_id,) = require(args, "device_id")
    payload: dict[str, Any] = {"device_id": device_id}
    for key in ("name_by_user", "area_id", "labels", "disabled_by"):
        if key in args:
            payload[key] = args[key]
    if len(payload) == 1:
        raise InvalidInput("Nothing to change")
    updated = await context.ws.call("config/device_registry/update", payload)
    return {"updated": True, "device": updated}


@tool(
    name="update_entity",
    group=GROUP_REGISTRY,
    title="Update an entity registry entry",
    description="""
Change how an entity is registered: rename it, change its entity id, assign it to an
area, label it, hide or disable it, or set options such as a display precision or a
unit conversion.

Changing `new_entity_id` breaks every reference to the old id - automations,
scripts, scenes, dashboards and templates - so search for the old id first and
update those too.
""",
    input_schema=schema(
        {
            "entity_id": string("The entity to update."),
            "name": string("Override the entity's friendly name."),
            "icon": string("Override the icon."),
            "area_id": string("Assign the entity to an area, overriding its device's area."),
            "labels": array("Replace the entity's labels with these label ids."),
            "new_entity_id": string("Rename the entity id itself."),
            "hidden_by": string("Set to `user` to hide, or null to unhide."),
            "disabled_by": string("Set to `user` to disable, or null to re-enable."),
            "aliases": array("Alternative spoken names for voice control."),
            "options_domain": string("Domain for `options`, e.g. `sensor` or `number`."),
            "options": obj("Per-domain options, e.g. {\"display_precision\": 1}."),
        },
        ["entity_id"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def update_entity(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Update an entity registry entry."""
    (entity_id,) = require(args, "entity_id")
    context.check_control(entity_id)
    if er.async_get(context.hass).async_get(entity_id) is None:
        raise InvalidInput(
            f"{entity_id} is not in the entity registry, so it comes from YAML and "
            "cannot be renamed or reassigned this way."
        )

    payload: dict[str, Any] = {"entity_id": entity_id}
    for key in (
        "name",
        "icon",
        "area_id",
        "labels",
        "new_entity_id",
        "hidden_by",
        "disabled_by",
        "aliases",
    ):
        if key in args:
            payload[key] = args[key]
    if args.get("options") is not None:
        domain = args.get("options_domain") or entity_id.split(".", 1)[0]
        payload["options_domain"] = domain
        payload["options"] = args["options"]
    if len(payload) == 1:
        raise InvalidInput("Nothing to change")

    updated = await context.ws.call("config/entity_registry/update", payload)
    return {"updated": True, "entity": updated}


@tool(
    name="remove_entity",
    group=GROUP_REGISTRY,
    title="Remove an entity from the registry",
    description="""
Delete an entity's registry entry. This only works for entities whose integration
allows removal; for most, the entity comes back as soon as the integration reloads.
To make an entity go away for good, remove or disable the device or config entry
instead.
""",
    input_schema=schema({"entity_id": string("The entity to remove.")}, ["entity_id"]),
    write=True,
    admin=True,
    destructive=True,
)
async def remove_entity(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Remove an entity registry entry."""
    (entity_id,) = require(args, "entity_id")
    context.check_admin()
    context.check_control(entity_id)
    await context.ws.call("config/entity_registry/remove", {"entity_id": entity_id})
    return {"removed": entity_id}


async def _manage(
    context: ToolContext,
    args: dict[str, Any],
    *,
    command: str,
    id_key: str,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Shared create/update/delete handling for the simple registries."""
    context.check_admin()
    action = str(args.get("action", "")).lower()
    if action not in ("create", "update", "delete"):
        raise InvalidInput("`action` must be create, update or delete")

    payload = {key: args[key] for key in fields if args.get(key) is not None}

    if action == "create":
        if not payload.get("name"):
            raise InvalidInput("`name` is required to create")
        created = await context.ws.call(f"{command}/create", payload)
        return {"created": True, "item": created}

    item_id = args.get(id_key)
    if not item_id:
        raise InvalidInput(f"`{id_key}` is required to {action}")

    if action == "delete":
        await context.ws.call(f"{command}/delete", {id_key: item_id})
        return {"deleted": item_id}

    if not payload:
        raise InvalidInput("Nothing to change")
    updated = await context.ws.call(f"{command}/update", {id_key: item_id, **payload})
    return {"updated": True, "item": updated}
