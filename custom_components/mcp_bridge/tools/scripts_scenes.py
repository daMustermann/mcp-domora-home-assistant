"""Script and scene tools, including full create/edit/delete."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.const import SERVICE_RELOAD
from homeassistant.helpers import entity_registry as er

from ..const import GROUP_SCENE, GROUP_SCRIPT
from ..context import ToolContext
from ..errors import InvalidInput
from ..registry import require, tool
from ..schema import anything, array, boolean, obj, schema, string
from ..yaml_store import async_validate, new_config_id, scene_store, script_store

SCRIPT_DOMAIN = "script"
SCENE_DOMAIN = "scene"

SCRIPT_FIELDS = {
    "alias": string("Human readable name."),
    "description": string("What the script does."),
    "sequence": array("The steps to run. Required.", items=anything("A script step.")),
    "mode": string("single | restart | queued | parallel. Default single."),
    "icon": string("An mdi icon, e.g. `mdi:play`."),
    "fields": obj("Declared input fields, so the script shows parameters in the UI."),
    "variables": obj("Variables available to the sequence."),
    "max": anything("Queue/parallel limit."),
}


def _slugify(value: str) -> str:
    """Make an object id out of a name."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or f"script_{new_config_id()}"


# Scripts ---------------------------------------------------------------------
@tool(
    name="list_scripts",
    group=GROUP_SCRIPT,
    title="List scripts",
    description="""
Every script with its state, mode and last run. `editable` is false for scripts
defined in configuration.yaml.
""",
    input_schema=schema(
        {
            "search": string("Case-insensitive match on name or entity id."),
            "include_config": boolean("Include each script's full config."),
        }
    ),
)
async def list_scripts(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List scripts."""
    hass = context.hass
    stored = dict(await script_store(hass).async_items())
    search = (args.get("search") or "").lower()
    results = []
    for state in hass.states.async_all(SCRIPT_DOMAIN):
        if not context.exposure.is_exposed(state.entity_id):
            continue
        object_id = state.entity_id.split(".", 1)[1]
        if search and search not in f"{state.entity_id} {state.name}".lower():
            continue
        entry: dict[str, Any] = {
            "entity_id": state.entity_id,
            "script_id": object_id,
            "alias": state.name,
            "state": state.state,
            "mode": state.attributes.get("mode"),
            "last_triggered": state.attributes.get("last_triggered"),
            "current_runs": state.attributes.get("current"),
            "editable": object_id in stored,
        }
        if args.get("include_config") and object_id in stored:
            entry["config"] = stored[object_id]
        results.append(entry)
    results.sort(key=lambda item: item["entity_id"])
    return {"count": len(results), "scripts": context.limit(results)}


@tool(
    name="get_script",
    group=GROUP_SCRIPT,
    title="Get script config",
    description="The stored config of one script. Read this before updating it.",
    input_schema=schema(
        {
            "script_id": string("The script's object id, e.g. `morning_routine`."),
            "entity_id": string("The script entity, e.g. `script.morning_routine`."),
        }
    ),
)
async def get_script(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read one script."""
    object_id = _script_id(args)
    config = await script_store(context.hass).async_get(object_id)
    if config is None:
        raise InvalidInput(
            f"Script {object_id!r} is not in scripts.yaml, so it is defined in "
            "configuration.yaml and cannot be edited here."
        )
    return {"script_id": object_id, "entity_id": f"{SCRIPT_DOMAIN}.{object_id}", "config": config}


@tool(
    name="create_script",
    group=GROUP_SCRIPT,
    title="Create script",
    description="""
Create a script in scripts.yaml and reload it. The config is validated first.
`sequence` is required. The entity becomes `script.<script_id>`; if you do not pass
`script_id` it is derived from the alias.
""",
    input_schema=schema(
        {
            **SCRIPT_FIELDS,
            "script_id": string("Object id to use. Derived from the alias if omitted."),
            "config": obj("The whole config as one object."),
        }
    ),
    write=True,
)
async def create_script(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create a script."""
    config = _collect(args, SCRIPT_FIELDS, ignore={"script_id"})
    if not config.get("sequence"):
        raise InvalidInput("`sequence` is required")
    object_id = args.get("script_id") or _slugify(str(config.get("alias") or ""))
    store = script_store(context.hass)
    if await store.async_get(object_id) is not None:
        raise InvalidInput(
            f"Script {object_id!r} already exists. Use update_script, or pass a different script_id."
        )

    await async_validate(context.hass, "script", object_id, config)
    written = await store.async_save(object_id, config)
    await _reload(context, SCRIPT_DOMAIN)
    return {
        "created": True,
        "script_id": object_id,
        "entity_id": f"{SCRIPT_DOMAIN}.{object_id}",
        "config": written,
    }


@tool(
    name="update_script",
    group=GROUP_SCRIPT,
    title="Update script",
    description="""
Replace a script's config. Read it with get_script first and send the complete new
version, or set `merge` to patch individual keys.
""",
    input_schema=schema(
        {
            "script_id": string("Which script."),
            "entity_id": string("The script entity, as an alternative."),
            **SCRIPT_FIELDS,
            "config": obj("The whole new config as one object."),
            "merge": boolean("Patch the given keys instead of replacing the config."),
        }
    ),
    write=True,
    destructive=True,
)
async def update_script(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Update a script."""
    object_id = _script_id(args)
    store = script_store(context.hass)
    current = await store.async_get(object_id)
    if current is None:
        raise InvalidInput(f"Script {object_id!r} is not in scripts.yaml")

    changes = _collect(args, SCRIPT_FIELDS, ignore={"script_id", "entity_id"})
    candidate = {**current, **changes} if args.get("merge") else changes
    await async_validate(context.hass, "script", object_id, candidate)
    written = await store.async_save(object_id, candidate)
    await _reload(context, SCRIPT_DOMAIN)
    return {
        "updated": True,
        "script_id": object_id,
        "config": written,
        "previous_config": current,
    }


@tool(
    name="delete_script",
    group=GROUP_SCRIPT,
    title="Delete script",
    description="""
Permanently remove a script from scripts.yaml. The returned `deleted_config` is the
only copy left. Check whether any automation calls this script before deleting it.
""",
    input_schema=schema(
        {
            "script_id": string("Which script."),
            "entity_id": string("The script entity, as an alternative."),
        }
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def delete_script(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Delete a script."""
    object_id = _script_id(args)
    store = script_store(context.hass)
    current = await store.async_get(object_id)
    if current is None:
        raise InvalidInput(f"Script {object_id!r} is not in scripts.yaml")
    await store.async_delete(object_id)
    entity_id = f"{SCRIPT_DOMAIN}.{object_id}"
    registry = er.async_get(context.hass)
    if registry.async_get(entity_id):
        registry.async_remove(entity_id)
    await _reload(context, SCRIPT_DOMAIN)
    return {"deleted": True, "script_id": object_id, "deleted_config": current}


@tool(
    name="run_script",
    group=GROUP_SCRIPT,
    title="Run script",
    description="""
Run a script now. Pass `variables` for a script that declares fields. By default
this waits for the script to finish, so failures surface and any response data is
returned.
""",
    input_schema=schema(
        {
            "script_id": string("Which script."),
            "entity_id": string("The script entity, as an alternative."),
            "variables": obj("Variables to pass to the script."),
            "wait": boolean("Wait for it to finish. Default true.", default=True),
        }
    ),
    write=True,
    destructive=True,
)
async def run_script(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Run a script."""
    object_id = _script_id(args)
    entity_id = f"{SCRIPT_DOMAIN}.{object_id}"
    context.check_control(entity_id)
    await context.hass.services.async_call(
        SCRIPT_DOMAIN,
        object_id if args.get("wait", True) else "turn_on",
        args.get("variables") or {}
        if args.get("wait", True)
        else {"entity_id": entity_id, "variables": args.get("variables") or {}},
        blocking=True,
        context=context.ha_context,
    )
    state = context.hass.states.get(entity_id)
    return {"ran": entity_id, "state": state.state if state else None}


# Scenes ----------------------------------------------------------------------
@tool(
    name="list_scenes",
    group=GROUP_SCENE,
    title="List scenes",
    description="Every scene, when it was last applied, and whether it is editable.",
    input_schema=schema(
        {
            "search": string("Case-insensitive match on name or entity id."),
            "include_config": boolean("Include each scene's full config."),
        }
    ),
)
async def list_scenes(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List scenes."""
    hass = context.hass
    stored = dict(await scene_store(hass).async_items())
    search = (args.get("search") or "").lower()
    by_unique: dict[str, str] = {}
    registry = er.async_get(hass)
    for state in hass.states.async_all(SCENE_DOMAIN):
        entry = registry.async_get(state.entity_id)
        if entry and entry.unique_id:
            by_unique[str(entry.unique_id)] = state.entity_id

    results = []
    for state in hass.states.async_all(SCENE_DOMAIN):
        if not context.exposure.is_exposed(state.entity_id):
            continue
        if search and search not in f"{state.entity_id} {state.name}".lower():
            continue
        entry = registry.async_get(state.entity_id)
        scene_id = str(entry.unique_id) if entry and entry.unique_id else None
        item: dict[str, Any] = {
            "entity_id": state.entity_id,
            "scene_id": scene_id,
            "name": state.name,
            "last_activated": state.state,
            "entity_count": len(state.attributes.get("entity_id") or []),
            "editable": scene_id in stored if scene_id else False,
        }
        if args.get("include_config") and scene_id in stored:
            item["config"] = stored[scene_id]
        results.append(item)
    results.sort(key=lambda item: item["entity_id"])
    return {"count": len(results), "scenes": context.limit(results)}


@tool(
    name="get_scene",
    group=GROUP_SCENE,
    title="Get scene config",
    description="The stored config of one scene, including the state it sets per entity.",
    input_schema=schema(
        {
            "scene_id": string("The scene's id, from list_scenes."),
            "entity_id": string("The scene entity, e.g. `scene.movie_night`."),
        }
    ),
)
async def get_scene(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read one scene."""
    scene_id = await _scene_id(context, args)
    config = await scene_store(context.hass).async_get(scene_id)
    if config is None:
        raise InvalidInput(f"Scene {scene_id!r} is not in scenes.yaml")
    return {"scene_id": scene_id, "config": config}


@tool(
    name="create_scene",
    group=GROUP_SCENE,
    title="Create scene",
    description="""
Create a scene in scenes.yaml. `entities` maps entity ids to the state they should
take, either as a plain state (`"on"`) or an object with attributes
(`{"state": "on", "brightness": 200}`).

To capture how things are set right now, read the entities with get_state first and
build `entities` from the values you see.
""",
    input_schema=schema(
        {
            "name": string("The scene's name. Required."),
            "entities": obj("Entity id to target state, as described above. Required."),
            "icon": string("An mdi icon."),
            "config": obj("The whole config as one object, instead of the fields above."),
        }
    ),
    write=True,
)
async def create_scene(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create a scene."""
    config = dict(args.get("config") or {})
    for key in ("name", "entities", "icon"):
        if args.get(key) is not None:
            config[key] = args[key]
    if not config.get("name"):
        raise InvalidInput("`name` is required")
    entities = config.get("entities")
    if not isinstance(entities, dict) or not entities:
        raise InvalidInput("`entities` must be a non-empty object of entity_id -> state")
    context.check_control(*entities)

    scene_id = new_config_id()
    store = scene_store(context.hass)
    written = await store.async_save(scene_id, config)
    await _reload(context, SCENE_DOMAIN)
    return {"created": True, "scene_id": scene_id, "config": written}


@tool(
    name="update_scene",
    group=GROUP_SCENE,
    title="Update scene",
    description="Replace a scene's config, or patch parts of it with `merge`.",
    input_schema=schema(
        {
            "scene_id": string("Which scene."),
            "entity_id": string("The scene entity, as an alternative."),
            "name": string("New name."),
            "entities": obj("New entity states."),
            "icon": string("New icon."),
            "config": obj("The whole new config as one object."),
            "merge": boolean("Patch the given keys instead of replacing the config."),
        }
    ),
    write=True,
    destructive=True,
)
async def update_scene(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Update a scene."""
    scene_id = await _scene_id(context, args)
    store = scene_store(context.hass)
    current = await store.async_get(scene_id)
    if current is None:
        raise InvalidInput(f"Scene {scene_id!r} is not in scenes.yaml")

    changes = dict(args.get("config") or {})
    for key in ("name", "entities", "icon"):
        if args.get(key) is not None:
            changes[key] = args[key]
    if not changes:
        raise InvalidInput("Nothing to change")
    if isinstance(changes.get("entities"), dict):
        context.check_control(*changes["entities"])

    candidate = {**current, **changes} if args.get("merge") else changes
    written = await store.async_save(scene_id, candidate)
    await _reload(context, SCENE_DOMAIN)
    return {"updated": True, "scene_id": scene_id, "config": written, "previous_config": current}


@tool(
    name="delete_scene",
    group=GROUP_SCENE,
    title="Delete scene",
    description="Permanently remove a scene from scenes.yaml.",
    input_schema=schema(
        {
            "scene_id": string("Which scene."),
            "entity_id": string("The scene entity, as an alternative."),
        }
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def delete_scene(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Delete a scene."""
    scene_id = await _scene_id(context, args)
    store = scene_store(context.hass)
    current = await store.async_get(scene_id)
    if current is None:
        raise InvalidInput(f"Scene {scene_id!r} is not in scenes.yaml")
    await store.async_delete(scene_id)
    await _reload(context, SCENE_DOMAIN)
    return {"deleted": True, "scene_id": scene_id, "deleted_config": current}


@tool(
    name="apply_scene",
    group=GROUP_SCENE,
    title="Activate scene",
    description="""
Activate a scene, optionally with a transition in seconds. `apply_states` applies a
set of states directly without saving a scene first, which is handy for trying a
look before committing to it.
""",
    input_schema=schema(
        {
            "entity_id": string("The scene entity to activate."),
            "scene_id": string("The scene id, as an alternative."),
            "transition": anything("Transition time in seconds."),
            "apply_states": obj(
                "Apply these entity states directly instead of activating a saved scene."
            ),
        }
    ),
    write=True,
    destructive=True,
)
async def apply_scene(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Activate a scene or apply states directly."""
    if states := args.get("apply_states"):
        if not isinstance(states, dict) or not states:
            raise InvalidInput("`apply_states` must be a non-empty object")
        context.check_control(*states)
        data: dict[str, Any] = {"entities": states}
        if args.get("transition") is not None:
            data["transition"] = args["transition"]
        await context.hass.services.async_call(
            SCENE_DOMAIN, "apply", data, blocking=True, context=context.ha_context
        )
        return {"applied_states": states}

    entity_id = args.get("entity_id")
    if not entity_id:
        scene_id = await _scene_id(context, args)
        entity_id = _scene_entity_for_id(context, scene_id)
        if entity_id is None:
            raise InvalidInput(f"Scene {scene_id!r} has no entity")
    context.check_control(entity_id)
    data = {"entity_id": entity_id}
    if args.get("transition") is not None:
        data["transition"] = args["transition"]
    await context.hass.services.async_call(
        SCENE_DOMAIN, "turn_on", data, blocking=True, context=context.ha_context
    )
    return {"activated": entity_id}


# Helpers ---------------------------------------------------------------------
def _script_id(args: dict[str, Any]) -> str:
    """Resolve a script reference to an object id."""
    if script_id := args.get("script_id"):
        return str(script_id).removeprefix(f"{SCRIPT_DOMAIN}.")
    if entity_id := args.get("entity_id"):
        if not str(entity_id).startswith(f"{SCRIPT_DOMAIN}."):
            raise InvalidInput(f"{entity_id} is not a script entity")
        return str(entity_id).split(".", 1)[1]
    raise InvalidInput("Provide script_id or entity_id")


async def _scene_id(context: ToolContext, args: dict[str, Any]) -> str:
    """Resolve a scene reference to a scene id."""
    if scene_id := args.get("scene_id"):
        return str(scene_id)
    entity_id = args.get("entity_id")
    if not entity_id:
        raise InvalidInput("Provide scene_id or entity_id")
    entry = er.async_get(context.hass).async_get(str(entity_id))
    if entry is None or not entry.unique_id:
        raise InvalidInput(
            f"{entity_id} has no scene id, so it is defined in configuration.yaml "
            "and cannot be edited here."
        )
    return str(entry.unique_id)


def _scene_entity_for_id(context: ToolContext, scene_id: str) -> str | None:
    """The scene entity belonging to a scene id."""
    registry = er.async_get(context.hass)
    # YAML scenes are provided by the `homeassistant` scene platform, keyed by id.
    if entity_id := registry.async_get_entity_id(SCENE_DOMAIN, "homeassistant", scene_id):
        return entity_id
    for entry in registry.entities.values():
        if entry.domain == SCENE_DOMAIN and str(entry.unique_id) == scene_id:
            return entry.entity_id
    return None


def _collect(
    args: dict[str, Any], fields: dict[str, Any], ignore: set[str] | None = None
) -> dict[str, Any]:
    """Build a config from a `config` object plus individual fields."""
    ignore = (ignore or set()) | {"config", "merge"}
    config = dict(args.get("config") or {})
    for key, value in args.items():
        if key in fields and key not in ignore and value is not None:
            config[key] = value
    if not config:
        raise InvalidInput("No config given")
    return {key: value for key, value in config.items() if value not in (None, "", [], {})}


async def _reload(context: ToolContext, domain: str) -> None:
    """Reload a domain's YAML configuration."""
    await context.hass.services.async_call(
        domain, SERVICE_RELOAD, {}, blocking=True, context=context.ha_context
    )
