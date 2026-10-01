"""Tools for config entries and integration setup flows.

Config and option flows are driven through Home Assistant's own flow managers, so
integrations can be added and reconfigured here exactly as in the UI - including
multi-step flows, which is why the schema of each step is returned in a form a
model can fill in.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers import config_validation as cv

from ..const import GROUP_INTEGRATIONS
from ..context import ToolContext
from ..errors import InvalidInput, MCPBridgeError
from ..registry import require, tool
from ..schema import boolean, obj, schema, string

_LOGGER = logging.getLogger(__name__)


def _schema_converter() -> Any:
    """The schema-to-JSON helper this Home Assistant version ships.

    2026.9 moved from `voluptuous_serialize.convert` to `probatio.to_field_list`;
    both produce the same field list the frontend renders.
    """
    try:
        from probatio import to_field_list  # noqa: PLC0415

        return to_field_list
    except ImportError:
        pass
    try:
        from voluptuous_serialize import convert  # noqa: PLC0415

        return convert
    except ImportError:
        return None


def _serialise_schema(data_schema: Any) -> Any:
    """Turn a voluptuous schema into JSON a model can fill in."""
    if data_schema is None:
        return None
    converter = _schema_converter()
    if converter is None:  # pragma: no cover - neither library present
        return {"note": "This Home Assistant version cannot describe flow schemas."}
    try:
        return converter(data_schema, custom_serializer=cv.custom_serializer)
    except Exception as err:  # noqa: BLE001 - never fail a flow over introspection
        _LOGGER.debug("Could not serialise flow schema: %s", err)
        return {"note": f"Schema could not be described: {err}"}


def _flow_result(result: dict[str, Any]) -> dict[str, Any]:
    """Describe a flow step for an MCP client."""
    payload: dict[str, Any] = {
        "flow_id": result.get("flow_id"),
        "type": result.get("type").value
        if hasattr(result.get("type"), "value")
        else result.get("type"),
        "handler": result.get("handler"),
        "step_id": result.get("step_id"),
    }
    if (data_schema := result.get("data_schema")) is not None:
        payload["fields"] = _serialise_schema(data_schema)
    for key in ("errors", "description_placeholders", "reason", "title", "preview"):
        if result.get(key):
            payload[key] = result[key]
    if result.get("type") is not None and payload["type"] == "create_entry":
        payload["created_entry"] = {
            "title": result.get("title"),
            "entry_id": (result.get("result").entry_id if result.get("result") else None),
        }
    if payload["type"] == "form":
        payload["next"] = (
            "Fill in `fields` and call continue_flow with this flow_id and your values. "
            "Ask the user for anything secret - never guess credentials."
        )
    return payload


@tool(
    name="list_integrations",
    group=GROUP_INTEGRATIONS,
    title="List config entries",
    description="""
Every configured integration (config entry) with its state, options and whether it
loaded. Check `state` and `error_reason_translation_key` when an integration's
entities are missing or unavailable - the problem is usually here rather than in the
entity.
""",
    input_schema=schema(
        {
            "domain": string("Only entries for this integration domain, e.g. `hue`."),
            "search": string("Case-insensitive match on title or domain."),
            "problems_only": boolean("Only entries that are not loaded."),
        }
    ),
)
async def list_integrations(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List config entries."""
    hass = context.hass
    domain = args.get("domain")
    search = (args.get("search") or "").lower()
    problems_only = bool(args.get("problems_only"))

    entries = []
    for entry in hass.config_entries.async_entries(domain):
        state = entry.state
        loaded = getattr(state, "recoverable", None) is None and state.name == "LOADED"
        if problems_only and state.name == "LOADED":
            continue
        if search and search not in f"{entry.title} {entry.domain}".lower():
            continue
        entries.append(
            {
                "entry_id": entry.entry_id,
                "domain": entry.domain,
                "title": entry.title,
                "state": state.name.lower(),
                "source": entry.source,
                "disabled_by": entry.disabled_by,
                "reason": entry.reason,
                "supports_options": entry.supports_options,
                "supports_reconfigure": entry.supports_reconfigure,
                "supports_remove_device": entry.supports_remove_device,
                "pref_disable_polling": entry.pref_disable_polling,
                "pref_disable_new_entities": entry.pref_disable_new_entities,
                "options": dict(entry.options),
                "data_keys": sorted(entry.data),
                "loaded": loaded,
            }
        )
    entries.sort(key=lambda item: (item["domain"], item["title"]))
    return {"count": len(entries), "config_entries": entries}


@tool(
    name="manage_integration",
    group=GROUP_INTEGRATIONS,
    title="Reload, disable or remove a config entry",
    description="""
Act on a configured integration: `reload` re-reads it (the usual fix after changing
something), `disable`/`enable` keep the configuration but stop it running, and
`remove` deletes it along with all its devices and entities.

`remove` is irreversible and takes the integration's entities with it. Confirm with
the user first.
""",
    input_schema=schema(
        {
            "entry_id": string("The config entry, from list_integrations."),
            "action": string("reload | disable | enable | remove"),
        },
        ["entry_id", "action"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def manage_integration(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Reload, disable, enable or remove a config entry."""
    entry_id, action = require(args, "entry_id", "action")
    context.check_admin()
    hass = context.hass
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise InvalidInput(f"No config entry {entry_id!r}")

    match str(action).lower():
        case "reload":
            ok = await hass.config_entries.async_reload(entry_id)
            return {"reloaded": ok, "entry_id": entry_id, "state": entry.state.name.lower()}
        case "disable":
            await hass.config_entries.async_set_disabled_by(
                entry_id, ConfigEntryDisabler.USER
            )
            return {"disabled": True, "entry_id": entry_id}
        case "enable":
            await hass.config_entries.async_set_disabled_by(entry_id, None)
            return {"enabled": True, "entry_id": entry_id}
        case "remove":
            result = await hass.config_entries.async_remove(entry_id)
            return {"removed": True, "entry_id": entry_id, **result}
    raise InvalidInput("`action` must be reload, disable, enable or remove")


@tool(
    name="list_available_integrations",
    group=GROUP_INTEGRATIONS,
    title="List integrations that can be set up",
    description="""
Every integration domain that supports a UI setup flow, i.e. everything you could
add with start_config_flow. Filter with `search` - the full list is long.
""",
    input_schema=schema({"search": string("Case-insensitive substring match on the domain.")}),
)
async def list_available_integrations(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List integrations with a config flow."""
    from homeassistant.loader import async_get_config_flows  # noqa: PLC0415

    search = (args.get("search") or "").lower()
    domains = sorted(await async_get_config_flows(context.hass))
    matching = [domain for domain in domains if not search or search in domain]
    return {
        "count": len(matching),
        "total": len(domains),
        "domains": context.limit(matching),
    }


@tool(
    name="start_config_flow",
    group=GROUP_INTEGRATIONS,
    title="Start adding an integration",
    description="""
Begin setting up a new integration. The result describes the first step and the
fields it wants; fill them in with continue_flow.

Many integrations need credentials, a host, or an interactive confirmation such as
pressing a button on a device. Ask the user for those - do not invent them, and do
not retry a failed login repeatedly, as some services lock the account.
""",
    input_schema=schema(
        {"domain": string("The integration domain to set up, e.g. `hue`.")}, ["domain"]
    ),
    write=True,
    admin=True,
)
async def start_config_flow(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Start a config flow."""
    (domain,) = require(args, "domain")
    context.check_admin()
    try:
        result = await context.hass.config_entries.flow.async_init(
            domain, context={"source": "user"}
        )
    except Exception as err:  # noqa: BLE001 - unknown handler, import error, ...
        raise MCPBridgeError(f"Could not start a config flow for {domain!r}: {err}") from err
    context.runtime_flows[result["flow_id"]] = "config"
    return _flow_result(result)


@tool(
    name="start_options_flow",
    group=GROUP_INTEGRATIONS,
    title="Start reconfiguring an integration",
    description="""
Open the options (or reconfigure) flow of an existing config entry - the UI's
"Configure" button. Use this to change an integration's settings; continue it with
continue_flow.
""",
    input_schema=schema(
        {
            "entry_id": string("The config entry to reconfigure."),
            "reconfigure": boolean(
                "Use the reconfigure flow instead of the options flow, for entries that support it."
            ),
        },
        ["entry_id"],
    ),
    write=True,
    admin=True,
)
async def start_options_flow(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Start an options or reconfigure flow."""
    (entry_id,) = require(args, "entry_id")
    context.check_admin()
    hass = context.hass
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise InvalidInput(f"No config entry {entry_id!r}")

    if args.get("reconfigure"):
        if not entry.supports_reconfigure:
            raise InvalidInput(f"{entry.title} does not support reconfiguration")
        result = await hass.config_entries.flow.async_init(
            entry.domain,
            context={"source": "reconfigure", "entry_id": entry_id},
        )
        context.runtime_flows[result["flow_id"]] = "config"
        return _flow_result(result)

    if not entry.supports_options:
        raise InvalidInput(
            f"{entry.title} has no options flow. Try reconfigure=true, or change it by "
            "removing and re-adding the integration."
        )
    result = await hass.config_entries.options.async_init(entry_id)
    context.runtime_flows[result["flow_id"]] = "options"
    return _flow_result(result)


@tool(
    name="continue_flow",
    group=GROUP_INTEGRATIONS,
    title="Submit a flow step",
    description="""
Submit values for the current step of a config or options flow. The result is either
the next step, or `create_entry`/`abort` when the flow has finished.

Pass exactly the keys listed in the step's `fields`.
""",
    input_schema=schema(
        {
            "flow_id": string("The flow to advance."),
            "user_input": obj("The values for this step's fields."),
        },
        ["flow_id"],
    ),
    write=True,
    admin=True,
)
async def continue_flow(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Advance a flow."""
    (flow_id,) = require(args, "flow_id")
    context.check_admin()
    user_input = args.get("user_input")
    if user_input is not None and not isinstance(user_input, dict):
        raise InvalidInput("`user_input` must be an object")

    for manager in _managers(context, flow_id):
        try:
            result = await manager.async_configure(flow_id, user_input)
        except UnknownFlow:
            continue
        except vol.Invalid as err:
            raise InvalidInput(f"The step rejected those values: {err}") from err
        return _flow_result(result)
    raise InvalidInput(
        f"No flow {flow_id!r} in progress. It may have timed out; start it again."
    )


@tool(
    name="abort_flow",
    group=GROUP_INTEGRATIONS,
    title="Abort a flow",
    description="Cancel a config or options flow that is in progress.",
    input_schema=schema({"flow_id": string("The flow to cancel.")}, ["flow_id"]),
    write=True,
    admin=True,
)
async def abort_flow(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Abort a flow."""
    (flow_id,) = require(args, "flow_id")
    context.check_admin()
    for manager in _managers(context, flow_id):
        try:
            manager.async_abort(flow_id)
        except UnknownFlow:
            continue
        context.runtime_flows.pop(flow_id, None)
        return {"aborted": flow_id}
    raise InvalidInput(f"No flow {flow_id!r} in progress")


@tool(
    name="list_flows_in_progress",
    group=GROUP_INTEGRATIONS,
    title="List flows in progress",
    description="""
Config flows waiting for input, including ones Home Assistant started itself from
discovery. A discovered device usually only needs a confirmation step to be adopted.
""",
    input_schema=schema({}),
)
async def list_flows_in_progress(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List in-progress flows."""
    hass = context.hass
    flows = [
        {
            "flow_id": flow.get("flow_id"),
            "handler": flow.get("handler"),
            "step_id": flow.get("step_id"),
            "source": flow.get("context", {}).get("source"),
            "title": flow.get("context", {}).get("title_placeholders"),
            "kind": "config",
        }
        for flow in hass.config_entries.flow.async_progress()
    ]
    return {"count": len(flows), "flows": flows}


def _managers(context: ToolContext, flow_id: str) -> list[Any]:
    """The flow managers to try for a flow id, best guess first."""
    hass = context.hass
    kind = context.runtime_flows.get(flow_id)
    config_manager = hass.config_entries.flow
    options_manager = hass.config_entries.options
    if kind == "options":
        return [options_manager, config_manager]
    return [config_manager, options_manager]
