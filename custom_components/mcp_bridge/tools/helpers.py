"""Tools for Home Assistant helper entities (input_*, counter, timer, schedule).

Helpers are storage collections, so they are created and edited through the same
WebSocket commands the UI uses and appear in Settings > Devices & services > Helpers.
"""

from __future__ import annotations

from typing import Any

from ..const import GROUP_HELPERS
from ..context import ToolContext
from ..errors import InvalidInput
from ..registry import require, tool
from ..schema import boolean, enum, obj, schema, string

#: Helper domains that expose a storage collection over the WebSocket API.
HELPER_DOMAINS = (
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "counter",
    "timer",
    "schedule",
)

FIELD_HINTS = """
Required fields per type:
- input_boolean: name
- input_button: name
- input_text: name; optional min, max, pattern, mode (text|password)
- input_number: name, min, max; optional step, mode (box|slider), unit_of_measurement
- input_select: name, options (list of strings); optional initial
- input_datetime: name, and at least one of has_date / has_time
- counter: name; optional initial, minimum, maximum, step, restore
- timer: name; optional duration ("00:05:00"), restore
- schedule: name, plus monday..sunday as lists of {from, to}
All types also accept icon.
"""


@tool(
    name="list_helpers",
    group=GROUP_HELPERS,
    title="List helpers",
    description="""
Every helper entity grouped by type, with its stored config. Only helpers created
through the UI or this API are editable; ones defined in configuration.yaml are
listed with `editable: false`.
""",
    input_schema=schema(
        {
            "domain": enum(
                "Only this helper type.", list(HELPER_DOMAINS)
            )
        }
    ),
)
async def list_helpers(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List helpers."""
    domains = [args["domain"]] if args.get("domain") else list(HELPER_DOMAINS)
    invalid = set(domains) - set(HELPER_DOMAINS)
    if invalid:
        raise InvalidInput(f"Not a helper domain: {', '.join(sorted(invalid))}")

    result: dict[str, Any] = {}
    for domain in domains:
        try:
            items = await context.ws.call(f"{domain}/list")
        except Exception:  # noqa: BLE001 - the integration may not be loaded
            continue
        editable_ids = {str(item.get("id")) for item in items or []}
        entries = []
        for state in context.hass.states.async_all(domain):
            if not context.exposure.is_exposed(state.entity_id):
                continue
            object_id = state.entity_id.split(".", 1)[1]
            config = next(
                (item for item in items or [] if str(item.get("id")) == object_id), None
            )
            entries.append(
                {
                    "entity_id": state.entity_id,
                    "helper_id": object_id,
                    "name": state.name,
                    "state": state.state,
                    "editable": object_id in editable_ids,
                    "config": config,
                }
            )
        if entries:
            result[domain] = entries
    return {"helpers": result, "field_reference": FIELD_HINTS.strip()}


@tool(
    name="create_helper",
    group=GROUP_HELPERS,
    title="Create helper",
    description=f"""
Create a helper entity. Helpers are the usual way to give an automation state of
its own: a toggle to enable a feature, a number to hold a threshold, a timer, or a
schedule.

{FIELD_HINTS}
""",
    input_schema=schema(
        {
            "domain": enum("Which kind of helper to create.", list(HELPER_DOMAINS)),
            "config": obj("The helper's fields, as described above."),
            "name": string("Shorthand for config.name."),
        },
        ["domain"],
    ),
    write=True,
)
async def create_helper(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create a helper."""
    (domain,) = require(args, "domain")
    if domain not in HELPER_DOMAINS:
        raise InvalidInput(f"Not a helper domain: {domain!r}")
    config = dict(args.get("config") or {})
    if name := args.get("name"):
        config.setdefault("name", name)
    if not config.get("name"):
        raise InvalidInput("`name` is required")

    created = await context.ws.call(f"{domain}/create", config)
    helper_id = str(created.get("id")) if isinstance(created, dict) else None
    return {
        "created": True,
        "domain": domain,
        "helper_id": helper_id,
        "entity_id": f"{domain}.{helper_id}" if helper_id else None,
        "config": created,
    }


@tool(
    name="update_helper",
    group=GROUP_HELPERS,
    title="Update helper",
    description="""
Change a helper's configuration. Pass the complete set of fields: a helper update
replaces the stored config, so omitted optional fields fall back to their defaults.
To change only the current value instead, call the helper's service, e.g.
`input_number.set_value`.
""",
    input_schema=schema(
        {
            "entity_id": string("The helper entity, e.g. `input_number.threshold`."),
            "domain": enum("Helper type, if you pass helper_id instead.", list(HELPER_DOMAINS)),
            "helper_id": string("The helper's object id."),
            "config": obj("The new fields."),
        },
        ["config"],
    ),
    write=True,
    destructive=True,
)
async def update_helper(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Update a helper."""
    domain, helper_id = _resolve_helper(args)
    config = args.get("config") or {}
    if not config:
        raise InvalidInput("`config` must not be empty")
    context.check_control(f"{domain}.{helper_id}")
    updated = await context.ws.call(
        f"{domain}/update", {f"{domain}_id": helper_id, **config}
    )
    return {"updated": True, "entity_id": f"{domain}.{helper_id}", "config": updated}


@tool(
    name="delete_helper",
    group=GROUP_HELPERS,
    title="Delete helper",
    description="""
Permanently remove a helper. Anything referring to it - automations, scripts,
dashboards, templates - will break, so check for references first, for example with
`list_automations` and a search for the entity id.
""",
    input_schema=schema(
        {
            "entity_id": string("The helper entity to delete."),
            "domain": enum("Helper type, if you pass helper_id instead.", list(HELPER_DOMAINS)),
            "helper_id": string("The helper's object id."),
        }
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def delete_helper(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Delete a helper."""
    domain, helper_id = _resolve_helper(args)
    entity_id = f"{domain}.{helper_id}"
    context.check_control(entity_id)
    await context.ws.call(f"{domain}/delete", {f"{domain}_id": helper_id})
    return {"deleted": True, "entity_id": entity_id}


def _resolve_helper(args: dict[str, Any]) -> tuple[str, str]:
    """Resolve a helper reference to (domain, object_id)."""
    if entity_id := args.get("entity_id"):
        domain, _, object_id = str(entity_id).partition(".")
        if domain not in HELPER_DOMAINS or not object_id:
            raise InvalidInput(f"{entity_id} is not an editable helper entity")
        return domain, object_id
    domain = args.get("domain")
    helper_id = args.get("helper_id")
    if not domain or not helper_id:
        raise InvalidInput("Provide entity_id, or both domain and helper_id")
    if domain not in HELPER_DOMAINS:
        raise InvalidInput(f"Not a helper domain: {domain!r}")
    return str(domain), str(helper_id)
