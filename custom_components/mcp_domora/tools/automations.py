"""Automation tools: list, read, validate, create, update, delete, trace.

Editing automations is what the built-in MCP server cannot do. Automations are
written to `automations.yaml` through the same validator and the same atomic write
the UI editor uses, so anything created here stays editable in the UI.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.automation import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.const import SERVICE_RELOAD, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.helpers import entity_registry as er

from ..const import GROUP_AUTOMATION
from ..context import ToolContext
from ..errors import InvalidInput, MCPBridgeError
from ..registry import require, tool
from ..schema import anything, array, boolean, integer, obj, schema, string
from ..yaml_store import async_validate, automation_store, new_config_id

CONFIG_FIELDS = {
    "alias": string("Human readable name. Required."),
    "description": string("What the automation is for."),
    "triggers": array(
        "Triggers (the modern key; `trigger` is also accepted).", items=anything("A trigger.")
    ),
    "conditions": array(
        "Conditions that must hold when a trigger fires.", items=anything("A condition.")
    ),
    "actions": array("What to do. Required.", items=anything("An action.")),
    "mode": string(
        "single | restart | queued | parallel. Default single.",
    ),
    "max": integer("Queue/parallel limit, for mode queued or parallel."),
    "variables": obj("Variables available to conditions and actions."),
    "trigger_variables": obj("Variables available to trigger templates."),
    "use_blueprint": obj(
        "Use a blueprint instead of inline triggers/actions: {\"path\": ..., \"input\": {...}}."
    ),
}


def _entity_for_config_id(context: ToolContext, config_id: str) -> str | None:
    """The automation entity belonging to a config id."""
    return er.async_get(context.hass).async_get_entity_id(
        AUTOMATION_DOMAIN, AUTOMATION_DOMAIN, config_id
    )


def _config_id_for_entity(context: ToolContext, entity_id: str) -> str | None:
    """The config id behind an automation entity."""
    entry = er.async_get(context.hass).async_get(entity_id)
    if entry is not None and entry.unique_id:
        return entry.unique_id
    state = context.hass.states.get(entity_id)
    if state is not None and (config_id := state.attributes.get("id")):
        return str(config_id)
    return None


async def _resolve(context: ToolContext, args: dict[str, Any]) -> tuple[str, str | None]:
    """Resolve a reference to (config_id, entity_id).

    Accepts an entity id, the automation's config id, or its alias.
    """
    reference = args.get("automation_id") or args.get("entity_id") or args.get("alias")
    if not reference:
        raise InvalidInput("Provide automation_id, entity_id or alias")
    reference = str(reference)

    if reference.startswith(f"{AUTOMATION_DOMAIN}."):
        config_id = _config_id_for_entity(context, reference)
        if config_id is None:
            raise InvalidInput(
                f"{reference} has no config id, so it is defined in configuration.yaml "
                "and cannot be edited through this API."
            )
        return config_id, reference

    store = automation_store(context.hass)
    items = await store.async_items()
    for config_id, config in items:
        if config_id == reference:
            return config_id, _entity_for_config_id(context, config_id)
    for config_id, config in items:
        if str(config.get("alias", "")).casefold() == reference.casefold():
            return config_id, _entity_for_config_id(context, config_id)

    known = ", ".join(sorted(str(config.get("alias", key)) for key, config in items)) or "(none)"
    raise InvalidInput(f"No automation matches {reference!r}. Editable automations: {known}")


def _normalise(config: dict[str, Any]) -> dict[str, Any]:
    """Drop empty keys and the id, which the store owns."""
    return {
        key: value
        for key, value in config.items()
        if key != "id" and value not in (None, [], {}, "")
    }


@tool(
    name="list_automations",
    group=GROUP_AUTOMATION,
    title="List automations",
    description="""
Every automation with its state, mode, when it last ran, and whether it is
editable. `editable` is false for automations defined in configuration.yaml - those
can be read and triggered but not changed here.
""",
    input_schema=schema(
        {
            "search": string("Case-insensitive match on alias, entity id or description."),
            "enabled_only": boolean("Only automations that are currently on."),
            "include_config": boolean("Include each automation's full config. Verbose."),
        }
    ),
)
async def list_automations(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List automations."""
    hass = context.hass
    stored = dict(await automation_store(hass).async_items())
    search = (args.get("search") or "").lower()
    enabled_only = bool(args.get("enabled_only"))
    include_config = bool(args.get("include_config"))

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for state in hass.states.async_all(AUTOMATION_DOMAIN):
        if not context.exposure.is_exposed(state.entity_id):
            continue
        config_id = _config_id_for_entity(context, state.entity_id)
        config = stored.get(config_id) if config_id else None
        if config_id:
            seen.add(config_id)
        entry: dict[str, Any] = {
            "entity_id": state.entity_id,
            "automation_id": config_id,
            "alias": state.name,
            "state": state.state,
            "mode": state.attributes.get("mode"),
            "current_runs": state.attributes.get("current"),
            "last_triggered": state.attributes.get("last_triggered"),
            "editable": config is not None,
        }
        if config is not None and (description := config.get("description")):
            entry["description"] = description
        if include_config and config is not None:
            entry["config"] = config
        if enabled_only and state.state != "on":
            continue
        text = f"{state.entity_id} {state.name} {entry.get('description', '')}".lower()
        if search and search not in text:
            continue
        results.append(entry)

    # Stored automations that have no entity: broken config, or just reloaded.
    for config_id, config in stored.items():
        if config_id in seen:
            continue
        alias = str(config.get("alias", config_id))
        if search and search not in f"{config_id} {alias}".lower():
            continue
        entry = {
            "entity_id": None,
            "automation_id": config_id,
            "alias": alias,
            "state": "not_loaded",
            "editable": True,
            "note": "In automations.yaml but not loaded. Reload automations or check the logs.",
        }
        if include_config:
            entry["config"] = config
        results.append(entry)

    results.sort(key=lambda item: (item["alias"] or "").lower())
    return {"count": len(results), "automations": context.limit(results)}


@tool(
    name="get_automation",
    group=GROUP_AUTOMATION,
    title="Get automation config",
    description="""
The complete stored config of one automation, by entity id, automation id or alias.
Read this before updating, and pass the result back with your changes applied -
`update_automation` replaces the whole config unless you set `merge`.
""",
    input_schema=schema(
        {
            "automation_id": string("The automation's id, as shown by list_automations."),
            "entity_id": string("The automation entity, e.g. `automation.evening_lights`."),
            "alias": string("The automation's name."),
        }
    ),
)
async def get_automation(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read one automation's config."""
    config_id, entity_id = await _resolve(context, args)
    config = await automation_store(context.hass).async_get(config_id)
    if config is None:
        raise InvalidInput(f"Automation {config_id} is not in automations.yaml")
    state = context.hass.states.get(entity_id) if entity_id else None
    return {
        "automation_id": config_id,
        "entity_id": entity_id,
        "state": state.state if state else None,
        "last_triggered": state.attributes.get("last_triggered") if state else None,
        "config": config,
    }


@tool(
    name="validate_automation_config",
    group=GROUP_AUTOMATION,
    title="Validate automation config",
    description="""
Check an automation config without saving it. Run this before create_automation or
update_automation: it catches unknown triggers, bad templates and malformed actions
and reports the same message the UI editor would, so you can fix it in one go.
""",
    input_schema=schema(
        {**CONFIG_FIELDS, "config": obj("The whole config as one object, instead of separate fields.")}
    ),
)
async def validate_automation_config(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Validate a config."""
    config = _collect_config(args)
    try:
        await async_validate(context.hass, "automation", "validate", config)
    except InvalidInput as err:
        return {"valid": False, "error": str(err), "config": config}
    return {"valid": True, "config": config}


@tool(
    name="create_automation",
    group=GROUP_AUTOMATION,
    title="Create automation",
    description="""
Create a new automation in automations.yaml and reload it so it takes effect
immediately. The config is validated first and nothing is written if it fails.

`alias` and `actions` are required; give it at least one trigger unless you only
want to run it manually. Verify entity ids with list_entities before referring to
them - a typo produces an automation that silently never fires.
""",
    input_schema=schema(
        {
            **CONFIG_FIELDS,
            "config": obj("The whole config as one object, instead of separate fields."),
            "enabled": boolean("Turn it on after creating. Default true.", default=True),
        }
    ),
    write=True,
)
async def create_automation(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create an automation."""
    config = _collect_config(args)
    if not config.get("alias"):
        raise InvalidInput("`alias` is required")
    if not (config.get("actions") or config.get("action") or config.get("use_blueprint")):
        raise InvalidInput("`actions` is required (or `use_blueprint`)")

    config_id = new_config_id()
    await async_validate(context.hass, "automation", config_id, config)
    store = automation_store(context.hass)
    written = await store.async_save(config_id, config)
    await _reload(context, config_id)

    entity_id = _entity_for_config_id(context, config_id)
    if entity_id and args.get("enabled", True) is False:
        await context.hass.services.async_call(
            AUTOMATION_DOMAIN,
            SERVICE_TURN_OFF,
            {"entity_id": entity_id},
            blocking=True,
            context=context.ha_context,
        )
    return {
        "created": True,
        "automation_id": config_id,
        "entity_id": entity_id,
        "config": written,
    }


@tool(
    name="update_automation",
    group=GROUP_AUTOMATION,
    title="Update automation",
    description="""
Change an existing automation. By default the config is replaced wholesale, so read
it with get_automation first and send the complete new version. Set `merge` to patch
only the keys you pass - but note that merging cannot remove a key, and lists are
replaced rather than appended to.
""",
    input_schema=schema(
        {
            "automation_id": string("Which automation to update."),
            "entity_id": string("The automation entity, as an alternative to automation_id."),
            **CONFIG_FIELDS,
            "config": obj("The whole new config as one object."),
            "merge": boolean("Patch the given keys instead of replacing the config."),
        }
    ),
    write=True,
    destructive=True,
)
async def update_automation(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Update an automation."""
    config_id, _entity_id = await _resolve(context, args)
    store = automation_store(context.hass)
    current = await store.async_get(config_id)
    if current is None:
        raise InvalidInput(
            f"Automation {config_id} is not in automations.yaml, so it cannot be edited."
        )

    changes = _collect_config(args, ignore={"automation_id", "entity_id", "alias_lookup", "merge"})
    if not changes:
        raise InvalidInput("Nothing to change: pass config fields or a `config` object.")

    merge = bool(args.get("merge"))
    candidate = {**_normalise(current), **changes} if merge else changes
    if not candidate.get("alias"):
        candidate["alias"] = current.get("alias")

    await async_validate(context.hass, "automation", config_id, candidate)
    written = await store.async_save(config_id, candidate)
    await _reload(context, config_id)
    return {
        "updated": True,
        "automation_id": config_id,
        "entity_id": _entity_for_config_id(context, config_id),
        "config": written,
        "previous_config": current,
    }


@tool(
    name="delete_automation",
    group=GROUP_AUTOMATION,
    title="Delete automation",
    description="""
Permanently remove an automation from automations.yaml and drop its entity. The
returned `deleted_config` is the only copy left - keep it if you might want to
restore it. Confirm with the user before calling this.
""",
    input_schema=schema(
        {
            "automation_id": string("Which automation to delete."),
            "entity_id": string("The automation entity, as an alternative."),
        }
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def delete_automation(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Delete an automation."""
    config_id, entity_id = await _resolve(context, args)
    store = automation_store(context.hass)
    current = await store.async_get(config_id)
    if current is None:
        raise InvalidInput(f"Automation {config_id} is not in automations.yaml")

    await store.async_delete(config_id)
    # Home Assistant removes the orphaned entity itself when the UI deletes an
    # automation; do the same so the entity does not linger as unavailable.
    registry = er.async_get(context.hass)
    if entity_id and registry.async_get(entity_id):
        registry.async_remove(entity_id)
    await _reload(context)
    return {"deleted": True, "automation_id": config_id, "deleted_config": current}


@tool(
    name="set_automation_enabled",
    group=GROUP_AUTOMATION,
    title="Enable or disable automation",
    description="""
Turn an automation on or off. A disabled automation keeps its config but stops
reacting to triggers. This is reversible and is usually the right move when an
automation misbehaves - delete it only if the user asks.
""",
    input_schema=schema(
        {
            "automation_id": string("Which automation."),
            "entity_id": string("The automation entity, as an alternative."),
            "enabled": boolean("True to enable, false to disable."),
        },
        ["enabled"],
    ),
    write=True,
    idempotent=True,
)
async def set_automation_enabled(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Enable or disable an automation."""
    _config_id, entity_id = await _resolve(context, args)
    if entity_id is None:
        raise InvalidInput("That automation has no entity, so it cannot be toggled.")
    context.check_control(entity_id)
    enabled = bool(args["enabled"])
    await context.hass.services.async_call(
        AUTOMATION_DOMAIN,
        SERVICE_TURN_ON if enabled else SERVICE_TURN_OFF,
        {"entity_id": entity_id},
        blocking=True,
        context=context.ha_context,
    )
    state = context.hass.states.get(entity_id)
    return {"entity_id": entity_id, "state": state.state if state else None}


@tool(
    name="trigger_automation",
    group=GROUP_AUTOMATION,
    title="Run automation now",
    description="""
Run an automation's actions immediately, as if it had been triggered. By default
its conditions are skipped, which is what you want for testing; set
`skip_condition` to false to check whether the conditions currently pass.
""",
    input_schema=schema(
        {
            "automation_id": string("Which automation."),
            "entity_id": string("The automation entity, as an alternative."),
            "skip_condition": boolean("Skip the conditions. Default true.", default=True),
        }
    ),
    write=True,
    destructive=True,
)
async def trigger_automation(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Trigger an automation."""
    _config_id, entity_id = await _resolve(context, args)
    if entity_id is None:
        raise InvalidInput("That automation has no entity, so it cannot be triggered.")
    context.check_control(entity_id)
    await context.hass.services.async_call(
        AUTOMATION_DOMAIN,
        "trigger",
        {"entity_id": entity_id, "skip_condition": bool(args.get("skip_condition", True))},
        blocking=True,
        context=context.ha_context,
    )
    return {"triggered": entity_id}


@tool(
    name="reload_automations",
    group=GROUP_AUTOMATION,
    title="Reload automations",
    description="""
Re-read automations.yaml. The editing tools reload automatically, so you only need
this after the file was changed outside Home Assistant, or to pick up an automation
that failed to load.
""",
    input_schema=schema({}),
    write=True,
    idempotent=True,
)
async def reload_automations(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Reload automations."""
    await _reload(context)
    loaded = len(context.hass.states.async_entity_ids(AUTOMATION_DOMAIN))
    return {"reloaded": True, "loaded_automations": loaded}


@tool(
    name="get_automation_traces",
    group=GROUP_AUTOMATION,
    title="Get automation traces",
    description="""
The recent runs of an automation. This is the fastest way to find out why one did
not do what was expected: each trace shows which trigger fired, how conditions
evaluated and which action ran or failed.

Without `run_id` you get a summary of the stored runs; with it you get the full
step-by-step trace of that run.
""",
    input_schema=schema(
        {
            "automation_id": string("Which automation."),
            "entity_id": string("The automation entity, as an alternative."),
            "run_id": string("A specific run, from the summary list."),
        }
    ),
)
async def get_automation_traces(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read automation traces."""
    config_id, entity_id = await _resolve(context, args)
    if run_id := args.get("run_id"):
        trace = await context.ws.call(
            "trace/get",
            {"domain": AUTOMATION_DOMAIN, "item_id": config_id, "run_id": run_id},
        )
        return {"automation_id": config_id, "entity_id": entity_id, "trace": trace}

    traces = await context.ws.call(
        "trace/list", {"domain": AUTOMATION_DOMAIN, "item_id": config_id}
    )
    summary = [
        {
            "run_id": trace.get("run_id"),
            "timestamp": trace.get("timestamp"),
            "state": trace.get("state"),
            "script_execution": trace.get("script_execution"),
            "error": trace.get("error"),
            "trigger": trace.get("trigger"),
            "last_step": trace.get("last_step"),
        }
        for trace in (traces or [])
    ]
    return {
        "automation_id": config_id,
        "entity_id": entity_id,
        "run_count": len(summary),
        "runs": summary,
        "note": "Pass run_id for the full trace of one run."
        if summary
        else "No stored traces. The automation has not run since the last restart.",
    }


@tool(
    name="list_device_automations",
    group=GROUP_AUTOMATION,
    title="List device triggers and actions",
    description="""
The device triggers, conditions and actions Home Assistant offers for a device -
the same list the UI automation editor shows under "Device".

Prefer these over hand-written state triggers for physical devices: a device
trigger like a button press or a remote's double-click often has no state
equivalent, so without this you would miss it entirely.
""",
    input_schema=schema(
        {
            "device_id": string("The device, from list_devices or describe_entity."),
            "kinds": array(
                "Which kinds to fetch: trigger, condition, action. Default all three."
            ),
        },
        ["device_id"],
    ),
)
async def list_device_automations(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List a device's automation capabilities."""
    (device_id,) = require(args, "device_id")
    kinds = [k for k in (args.get("kinds") or ["trigger", "condition", "action"])]
    invalid = set(kinds) - {"trigger", "condition", "action"}
    if invalid:
        raise InvalidInput(f"Unknown kinds: {', '.join(sorted(invalid))}")

    result: dict[str, Any] = {"device_id": device_id}
    for kind in kinds:
        try:
            result[f"{kind}s"] = await context.ws.call(
                f"device_automation/{kind}/list", {"device_id": device_id}
            )
        except MCPBridgeError as err:
            result[f"{kind}s"] = {"error": str(err)}
    return result


def _collect_config(args: dict[str, Any], ignore: set[str] | None = None) -> dict[str, Any]:
    """Build a config from either a `config` object or the individual fields."""
    ignore = (ignore or set()) | {"config", "merge", "enabled"}
    config = dict(args.get("config") or {})
    for key, value in args.items():
        if key in ignore or value is None:
            continue
        if key in CONFIG_FIELDS or key in ("trigger", "condition", "action"):
            config[key] = value
    if not config:
        raise InvalidInput(
            "No config given. Pass a `config` object, or fields like alias/triggers/actions."
        )
    return _normalise(config)


async def _reload(context: ToolContext, config_id: str | None = None) -> None:
    """Reload automations, narrowing to one when Home Assistant supports it."""
    data = {"id": config_id} if config_id else {}
    await context.hass.services.async_call(
        AUTOMATION_DOMAIN, SERVICE_RELOAD, data, blocking=True, context=context.ha_context
    )
