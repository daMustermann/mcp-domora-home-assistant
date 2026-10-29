"""Supervisor tools: add-ons and backups.

Add-on management only exists on Home Assistant OS and Supervised installs. On a
container or core install these tools report that clearly rather than failing
obscurely.
"""

from __future__ import annotations

from typing import Any

from ..const import GROUP_SUPERVISOR
from ..context import ToolContext
from ..errors import InvalidInput, MCPBridgeError
from ..registry import require, tool
from ..schema import array, boolean, obj, schema, string

NOT_SUPERVISED = (
    "This installation has no Supervisor, so there are no add-ons. "
    "Add-ons only exist on Home Assistant OS and Supervised installations."
)


def _supervisor_client(context: ToolContext) -> Any:
    """The Supervisor API client, or fail with an explanation."""
    if "hassio" not in context.hass.config.components:
        raise MCPBridgeError(NOT_SUPERVISED)
    try:
        from homeassistant.components.hassio.handler import (  # noqa: PLC0415
            get_supervisor_client,
        )
    except ImportError as err:  # pragma: no cover
        raise MCPBridgeError(NOT_SUPERVISED) from err
    return get_supervisor_client(context.hass)


@tool(
    name="get_supervisor_info",
    group=GROUP_SUPERVISOR,
    title="Get Supervisor and host info",
    description="""
Supervisor, host and operating system information, plus the installed add-ons. Use
it to see what the installation actually is before suggesting anything that depends
on add-ons, and to check free disk space.
""",
    input_schema=schema({}),
    admin=True,
)
async def get_supervisor_info(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Return supervisor information."""
    context.check_admin()
    if "hassio" not in context.hass.config.components:
        return {"supervised": False, "note": NOT_SUPERVISED}

    from homeassistant.components import hassio  # noqa: PLC0415

    result: dict[str, Any] = {"supervised": True}
    for key, getter in (
        ("info", "get_info"),
        ("host", "get_host_info"),
        ("os", "get_os_info"),
        ("core", "get_core_info"),
        ("supervisor", "get_supervisor_info"),
        ("network", "get_network_info"),
    ):
        function = getattr(hassio, getter, None)
        if function is not None:
            try:
                result[key] = function(context.hass)
            except Exception as err:  # noqa: BLE001 - best effort
                result[key] = {"error": str(err)}
    addons = getattr(hassio, "get_addons_info", None)
    if addons is not None:
        result["addons"] = addons(context.hass)
    return result


@tool(
    name="list_addons",
    group=GROUP_SUPERVISOR,
    title="List add-ons",
    description="Installed add-ons with their version, state and whether an update is available.",
    input_schema=schema({}),
    admin=True,
)
async def list_addons(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List add-ons."""
    context.check_admin()
    client = _supervisor_client(context)
    addons = await client.addons.list()
    return {
        "count": len(addons),
        "addons": [
            {
                "slug": addon.slug,
                "name": addon.name,
                "version": str(addon.version) if addon.version else None,
                "version_latest": str(addon.version_latest) if addon.version_latest else None,
                "state": str(addon.state),
                "update_available": addon.update_available,
                "repository": addon.repository,
            }
            for addon in addons
        ],
    }


@tool(
    name="manage_addon",
    group=GROUP_SUPERVISOR,
    title="Start, stop or restart an add-on",
    description="""
Control an installed add-on. `info` returns its full state and options, `logs`
returns its recent output - which is where to look when an add-on misbehaves.

`stop` interrupts whatever the add-on provides; if it is a database, a broker or a
proxy, other things will break while it is down.
""",
    input_schema=schema(
        {
            "slug": string("The add-on slug, from list_addons."),
            "action": string("info | logs | start | stop | restart"),
        },
        ["slug", "action"],
    ),
    write=True,
    admin=True,
    dangerous=True,
    destructive=True,
)
async def manage_addon(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Act on an add-on."""
    slug, action = require(args, "slug", "action")
    context.check_admin()
    client = _supervisor_client(context)
    action = str(action).lower()

    match action:
        case "info":
            info = await client.addons.addon_info(slug)
            return {
                "slug": slug,
                "name": info.name,
                "state": str(info.state),
                "version": str(info.version) if info.version else None,
                "options": info.options,
                "ingress_url": info.ingress_url,
                "hostname": info.hostname,
            }
        case "logs":
            logs = await client.addons.addon_logs(slug) if hasattr(client.addons, "addon_logs") else None
            if logs is None:
                raise MCPBridgeError(
                    "This Supervisor client cannot fetch add-on logs; open the add-on page instead."
                )
            return {"slug": slug, "logs": logs}
        case "start":
            await client.addons.start_addon(slug)
        case "stop":
            await client.addons.stop_addon(slug)
        case "restart":
            await client.addons.restart_addon(slug)
        case _:
            raise InvalidInput("`action` must be info, logs, start, stop or restart")
    return {"slug": slug, "action": action, "done": True}


@tool(
    name="list_backups",
    group=GROUP_SUPERVISOR,
    title="List backups",
    description="Existing backups with their date, size and what they contain.",
    input_schema=schema({}),
    admin=True,
)
async def list_backups(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List backups."""
    context.check_admin()
    return await context.ws.call("backup/info")


@tool(
    name="list_backup_locations",
    group=GROUP_SUPERVISOR,
    title="List backup locations",
    description="List the actual Home Assistant backup agent IDs for backup creation and restore.",
    input_schema=schema({}),
    admin=True,
)
async def list_backup_locations(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    context.check_admin()
    return await context.ws.call("backup/agents/info")


@tool(
    name="get_backup_details",
    group=GROUP_SUPERVISOR,
    description="Get a backup's contents and available locations before restoring it.",
    input_schema=schema({"backup_id": string("Backup ID from list_backups.")}, ["backup_id"]),
    admin=True,
)
async def get_backup_details(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    context.check_admin()
    (backup_id,) = require(args, "backup_id")
    return await context.ws.call("backup/details", {"backup_id": backup_id})


@tool(
    name="create_backup",
    group=GROUP_SUPERVISOR,
    title="Create a backup",
    description="""
Start a backup. Worth doing before any risky change - removing an integration,
editing many automations at once, or restarting into a new version.

Backups take minutes and run in the background, so this returns as soon as the job
has started. Check `list_backups` afterwards to confirm it completed.
""",
    input_schema=schema(
        {
            "name": string("A name for the backup. Defaults to a timestamp."),
            "automatic_settings": boolean(
                "Use the user's configured automatic backup settings. Default true.", default=True
            ),
            "password": string("Encrypt the backup with this password."),
            "agent_ids": array("Backup locations from list_backup_locations. Required for explicit settings."),
            "include_all_addons": boolean("Include all add-ons in an explicit backup. Default true."),
            "include_database": boolean("Include the database. Default true."),
            "include_folders": array(
                "Folders to include. Defaults to share, addons/local, ssl and media."
            ),
        }
    ),
    write=True,
    admin=True,
)
async def create_backup(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create a backup."""
    context.check_admin()
    explicit = any(key in args for key in ("name", "password", "agent_ids", "include_all_addons", "include_database", "include_folders"))
    if args.get("automatic_settings", True) and not explicit:
        result = await context.ws.call("backup/generate_with_automatic_settings")
        return {"started": True, "result": result, "note": "Check list_backups for completion and errors before making changes."}

    agents = args.get("agent_ids")
    if not isinstance(agents, list) or not agents or not all(isinstance(item, str) and item for item in agents):
        raise InvalidInput("Explicit backup settings require agent_ids from list_backup_locations.")
    payload: dict[str, Any] = {
        "agent_ids": agents,
        "include_homeassistant": True,
        "include_all_addons": args.get("include_all_addons", True),
        "include_database": args.get("include_database", True),
        "include_folders": args.get("include_folders", ["share", "addons/local", "ssl", "media"]),
    }
    if name := args.get("name"):
        payload["name"] = name
    if password := args.get("password"):
        payload["password"] = password
    result = await context.ws.call("backup/generate", payload)
    return {"started": True, "result": result, "note": "Check list_backups for completion and errors before making changes."}


@tool(
    name="restore_backup",
    group=GROUP_SUPERVISOR,
    title="Restore a backup",
    description="Restore a chosen Home Assistant backup. This replaces current data and may disconnect the server; inspect get_backup_details first and tell the user what will be restored.",
    input_schema=schema({
        "backup_id": string("Backup ID from list_backups."),
        "agent_id": string("Location containing this backup, from get_backup_details."),
        "password": string("Backup encryption key, if needed."),
        "restore_addons": array("Add-on IDs to restore; omit to use Home Assistant defaults."),
        "restore_folders": array("Folders to restore; omit to use Home Assistant defaults."),
        "restore_database": boolean("Restore the database. Default true."),
        "restore_homeassistant": boolean("Restore Home Assistant. Default true."),
    }, ["backup_id", "agent_id"]),
    write=True,
    admin=True,
    destructive=True,
)
async def restore_backup(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    context.check_admin()
    backup_id, agent_id = require(args, "backup_id", "agent_id")
    payload = {"backup_id": backup_id, "agent_id": agent_id}
    for key in ("password", "restore_addons", "restore_folders", "restore_database", "restore_homeassistant"):
        if key in args:
            payload[key] = args[key]
    result = await context.ws.call("backup/restore", payload, timeout=120)
    return {"requested": True, "result": result, "note": "The connection may be interrupted; verify the restored system after it returns."}
