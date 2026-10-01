"""Lovelace dashboard tools."""

from __future__ import annotations

from typing import Any

from ..const import GROUP_DASHBOARD
from ..context import ToolContext
from ..errors import InvalidInput, MCPBridgeError
from ..registry import require, tool
from ..ws import WebSocketCommandError
from ..schema import boolean, obj, schema, string


@tool(
    name="list_dashboards",
    group=GROUP_DASHBOARD,
    title="List dashboards",
    description="""
Every Lovelace dashboard, plus the custom resources (JavaScript modules) that are
loaded. The default dashboard has no url_path; others are addressed by it.
""",
    input_schema=schema({}),
)
async def list_dashboards(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List dashboards."""
    result: dict[str, Any] = {}
    try:
        result["dashboards"] = await context.ws.call("lovelace/dashboards/list")
    except MCPBridgeError as err:
        raise MCPBridgeError(
            f"Could not list dashboards ({err}). The lovelace integration may be in YAML mode."
        ) from err
    try:
        result["resources"] = await context.ws.call("lovelace/resources")
    except MCPBridgeError:
        result["resources"] = []
    result["note"] = (
        "The default dashboard has url_path null. Pass url_path to get_dashboard_config "
        "for the others."
    )
    return result


@tool(
    name="get_dashboard_config",
    group=GROUP_DASHBOARD,
    title="Get dashboard config",
    description="""
The full card configuration of a dashboard. Read this before editing - saving
replaces the whole dashboard, so you need the current config to build on.

A dashboard in YAML mode cannot be edited here.
""",
    input_schema=schema(
        {
            "url_path": string(
                "Which dashboard. Omit for the default one."
            )
        }
    ),
)
async def get_dashboard_config(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read a dashboard config."""
    payload = {"url_path": args.get("url_path")}
    try:
        config = await context.ws.call("lovelace/config", payload)
    except WebSocketCommandError as err:
        if err.code != "config_not_found":
            raise
        # A dashboard Home Assistant generates automatically has no stored config
        # until something saves one.
        return {
            "url_path": args.get("url_path"),
            "config": None,
            "stored_config": False,
            "note": (
                "This dashboard is auto-generated and has no stored configuration yet. "
                "Saving a config with save_dashboard_config takes it over, and the "
                "automatic layout is then gone - build on what the user already sees, "
                "or create a separate dashboard instead."
            ),
        }
    return {"url_path": args.get("url_path"), "config": config, "stored_config": True}


@tool(
    name="save_dashboard_config",
    group=GROUP_DASHBOARD,
    title="Save dashboard config",
    description="""
Replace a dashboard's configuration. This overwrites everything, so always start
from get_dashboard_config, change what you need and send the whole structure back.

The config is a Lovelace object: `{"views": [{"title": ..., "cards": [...]}, ...]}`.
Verify every entity id you reference, because a card pointing at a non-existent
entity renders as an error for the user.
""",
    input_schema=schema(
        {
            "config": obj("The complete new dashboard configuration."),
            "url_path": string("Which dashboard. Omit for the default one."),
        },
        ["config"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def save_dashboard_config(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Save a dashboard config."""
    (config,) = require(args, "config")
    context.check_admin()
    if not isinstance(config, dict):
        raise InvalidInput("`config` must be an object with a `views` key")
    if "views" not in config:
        raise InvalidInput(
            "`config` has no `views`. A Lovelace config looks like "
            '{"views": [{"title": "Home", "cards": []}]}.'
        )
    await context.ws.call(
        "lovelace/config/save", {"url_path": args.get("url_path"), "config": config}
    )
    return {"saved": True, "url_path": args.get("url_path"), "view_count": len(config["views"])}


@tool(
    name="manage_dashboard",
    group=GROUP_DASHBOARD,
    title="Create, update or delete a dashboard",
    description="""
Manage dashboards themselves. `create` needs a title and a url_path containing a
hyphen (Home Assistant requires one). Deleting a dashboard discards its cards.
""",
    input_schema=schema(
        {
            "action": string("create | update | delete"),
            "dashboard_id": string("The dashboard to update or delete, from list_dashboards."),
            "title": string("The dashboard's title."),
            "url_path": string("URL path, which must contain a hyphen, e.g. `energy-detail`."),
            "icon": string("An mdi icon for the sidebar."),
            "show_in_sidebar": boolean("Show it in the sidebar. Default true."),
            "require_admin": boolean("Only show it to administrators."),
        },
        ["action"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def manage_dashboard(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create, update or delete a dashboard."""
    context.check_admin()
    action = str(args.get("action", "")).lower()
    fields = ("title", "icon", "show_in_sidebar", "require_admin")
    payload = {key: args[key] for key in fields if args.get(key) is not None}

    if action == "create":
        url_path = args.get("url_path")
        if not args.get("title") or not url_path:
            raise InvalidInput("`title` and `url_path` are required to create a dashboard")
        if "-" not in url_path:
            raise InvalidInput("`url_path` must contain a hyphen, e.g. `energy-detail`")
        created = await context.ws.call(
            "lovelace/dashboards/create", {**payload, "url_path": url_path}
        )
        return {"created": True, "dashboard": created}

    dashboard_id = args.get("dashboard_id")
    if not dashboard_id:
        raise InvalidInput("`dashboard_id` is required to update or delete")

    if action == "delete":
        await context.ws.call("lovelace/dashboards/delete", {"dashboard_id": dashboard_id})
        return {"deleted": dashboard_id}
    if action == "update":
        if not payload:
            raise InvalidInput("Nothing to change")
        updated = await context.ws.call(
            "lovelace/dashboards/update", {"dashboard_id": dashboard_id, **payload}
        )
        return {"updated": True, "dashboard": updated}
    raise InvalidInput("`action` must be create, update or delete")
