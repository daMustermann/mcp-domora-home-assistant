"""Resolve Home Assistant service targets to concrete entity ids.

Expanding targets ourselves keeps the permission and exposure checks honest: a
call aimed at an area must not reach an entity the user hid from MCP clients.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)

from ..context import ToolContext

TARGET_KEYS = ("entity_id", "device_id", "area_id", "floor_id", "label_id")


def _as_list(value: Any) -> list[str]:
    """Normalise a target value to a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def split_target(data: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Separate target selectors from service data.

    Home Assistant accepts targets either nested under `target` or inline in the
    service data, and so does this.
    """
    target: dict[str, list[str]] = {}
    rest: dict[str, Any] = {}
    nested = data.get("target") or {}
    for key, value in {**nested, **{k: v for k, v in data.items() if k != "target"}}.items():
        if key in TARGET_KEYS:
            target.setdefault(key, []).extend(_as_list(value))
        elif key != "target":
            rest[key] = value
    return target, rest


def resolve_entity_ids(context: ToolContext, target: dict[str, list[str]]) -> list[str]:
    """Expand a target into the entity ids it refers to."""
    hass = context.hass
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)

    found: set[str] = set()

    for entity_id in target.get("entity_id", []):
        if entity_id in ("all", "none"):
            if entity_id == "all":
                found.update(state.entity_id for state in hass.states.async_all())
            continue
        found.add(entity_id)

    device_ids = set(target.get("device_id", []))
    area_ids = set(target.get("area_id", []))

    for floor_id in target.get("floor_id", []):
        area_ids.update(
            area.id for area in ar.async_entries_for_floor(area_reg, floor_id)
        )

    for label_id in target.get("label_id", []):
        found.update(
            entry.entity_id for entry in er.async_entries_for_label(entity_reg, label_id)
        )
        device_ids.update(
            device.id for device in dr.async_entries_for_label(device_reg, label_id)
        )
        area_ids.update(area.id for area in ar.async_entries_for_label(area_reg, label_id))

    for area_id in area_ids:
        found.update(
            entry.entity_id
            for entry in er.async_entries_for_area(entity_reg, area_id)
            if not entry.disabled_by
        )
        device_ids.update(
            device.id for device in dr.async_entries_for_area(device_reg, area_id)
        )

    for device_id in device_ids:
        found.update(
            entry.entity_id
            for entry in er.async_entries_for_device(entity_reg, device_id)
            if not entry.disabled_by
            # An entity with its own area override is not part of the device's area.
            and (entry.area_id is None or entry.area_id in area_ids or device_id in target.get("device_id", []))
        )

    return sorted(found)
