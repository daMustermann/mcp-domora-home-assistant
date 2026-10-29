"""System level tools: config, logs, repairs, users, restart."""

from __future__ import annotations

import os
from typing import Any

from ..const import GROUP_SYSTEM
from ..context import ToolContext
from ..errors import InvalidInput, MCPBridgeError
from ..registry import require, tool
from ..schema import boolean, integer, schema, string


@tool(
    name="get_config",
    group=GROUP_SYSTEM,
    title="Get core configuration",
    description="""
Core configuration: version, timezone, location, unit system, config directory and
which integrations are loaded. Check the version here before using a feature that
depends on it, and the timezone before writing time-based triggers.
""",
    input_schema=schema({"include_components": boolean("List every loaded component.")}),
)
async def get_config(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Return core configuration."""
    config = context.hass.config.as_dict()
    if not args.get("include_components"):
        config["component_count"] = len(config.get("components", []))
        config.pop("components", None)
    config["user"] = {
        "name": context.user.name,
        "id": context.user.id,
        "is_admin": context.user.is_admin,
    }
    return config


@tool(
    name="get_system_info",
    group=GROUP_SYSTEM,
    title="Get system information",
    description="""
Installation details: Home Assistant and Python versions, operating system, whether
it runs in a container or on Home Assistant OS, and the architecture. Useful for
telling the user whether a feature or add-on is even available to them.
""",
    input_schema=schema({}),
)
async def get_system_info(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Return installation information."""
    try:
        return await context.ws.call("system_info/info")
    except MCPBridgeError:
        from homeassistant.helpers.system_info import async_get_system_info  # noqa: PLC0415

        return await async_get_system_info(context.hass)


@tool(
    name="get_error_log",
    group=GROUP_SYSTEM,
    title="Get the error log",
    description="""
Recent warnings and errors. Start here when something does not work and the cause is
not obvious - a failed integration, a template error or a broken automation almost
always leaves a line here.

`entries` are the structured records Home Assistant keeps; `log_tail` is the raw end
of home-assistant.log, which has more detail including tracebacks.
""",
    input_schema=schema(
        {
            "lines": integer("How many raw log lines to include. Default 100.", default=100),
            "include_raw_log": boolean("Include the raw log tail. Default true.", default=True),
            "search": string("Only lines and entries containing this text."),
        }
    ),
    admin=True,
)
async def get_error_log(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read the error log."""
    context.check_admin()
    search = (args.get("search") or "").lower()
    result: dict[str, Any] = {}

    try:
        entries = await context.ws.call("system_log/list")
    except MCPBridgeError as err:
        entries = []
        result["system_log_error"] = str(err)
    filtered = [
        entry
        for entry in entries or []
        if not search or search in str(entry.get("message", "")).lower()
        or search in str(entry.get("name", "")).lower()
    ]
    result["entries"] = context.limit(filtered)
    result["entry_count"] = len(filtered)

    if args.get("include_raw_log", True):
        lines = int(args.get("lines", 100))
        result["log_tail"] = await context.hass.async_add_executor_job(
            _tail_log, context.hass.config.path("home-assistant.log"), lines, search
        )
    return result


def _tail_log(path: str, lines: int, search: str) -> list[str] | str:
    """Read the last lines of the log file."""
    if not os.path.isfile(path):
        return f"No log file at {path}. Home Assistant may be logging to stdout only."
    with open(path, encoding="utf-8", errors="replace") as handle:
        content = handle.readlines()
    if search:
        content = [line for line in content if search in line.lower()]
    return [line.rstrip("\n") for line in content[-lines:]]


@tool(
    name="clear_error_log",
    group=GROUP_SYSTEM,
    title="Clear the error log",
    description="Discard the collected warnings and errors, so new ones stand out.",
    input_schema=schema({}),
    write=True,
    admin=True,
    idempotent=True,
)
async def clear_error_log(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Clear the system log."""
    context.check_admin()
    await context.ws.call("system_log/clear")
    return {"cleared": True}


@tool(
    name="list_repairs",
    group=GROUP_SYSTEM,
    title="List repair issues",
    description="""
Open repair issues: deprecations, misconfigurations and problems Home Assistant has
noticed about itself. Worth checking whenever something behaves oddly, since the
answer is often already here.
""",
    input_schema=schema({"include_ignored": boolean("Also list issues the user dismissed.")}),
)
async def list_repairs(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List repair issues."""
    result = await context.ws.call("repairs/list_issues")
    issues = (result or {}).get("issues", []) if isinstance(result, dict) else result or []
    if not args.get("include_ignored"):
        issues = [issue for issue in issues if not issue.get("ignored")]
    return {"count": len(issues), "issues": issues}


@tool(
    name="check_config",
    group=GROUP_SYSTEM,
    title="Check the configuration",
    description="""
Validate the whole Home Assistant configuration without restarting. Always run this
after editing YAML by hand, and before restarting - a restart with an invalid config
leaves the instance in safe mode.
""",
    input_schema=schema({}),
    admin=True,
)
async def check_config(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Check the configuration."""
    context.check_admin()
    try:
        result = await context.hass.services.async_call(
            "homeassistant",
            "check_config",
            {},
            blocking=True,
            context=context.ha_context,
            return_response=True,
        )
    except Exception:  # noqa: BLE001 - older versions return nothing
        result = None
    if result:
        return {"result": result}
    return {
        "checked": True,
        "note": "No errors reported. Check get_error_log for warnings.",
    }


@tool(
    name="reload_config",
    group=GROUP_SYSTEM,
    title="Reload configuration",
    description="""
Reload YAML configuration without restarting. With no domain this reloads everything
that supports it (`homeassistant.reload_all`); with a domain it reloads just that
one, e.g. `template` or `rest`.

Prefer this over restarting: it is much faster and does not interrupt anything.
""",
    input_schema=schema(
        {"domain": string("Reload only this integration, e.g. `template`.")}
    ),
    write=True,
    admin=True,
    idempotent=True,
)
async def reload_config(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Reload configuration."""
    context.check_admin()
    hass = context.hass
    if domain := args.get("domain"):
        if not hass.services.has_service(domain, "reload"):
            raise InvalidInput(f"{domain} has no reload service")
        await hass.services.async_call(
            domain, "reload", {}, blocking=True, context=context.ha_context
        )
        return {"reloaded": domain}
    await hass.services.async_call(
        "homeassistant", "reload_all", {}, blocking=True, context=context.ha_context
    )
    return {"reloaded": "all"}


@tool(
    name="restart_home_assistant",
    group=GROUP_SYSTEM,
    title="Restart Home Assistant",
    description="""
Restart or stop Home Assistant. This disconnects everything, including this MCP
session, for a minute or more.

Run check_config first - restarting with a broken configuration leaves the instance
in safe mode. Most changes need only `reload_config`, so ask the user before
restarting.
""",
    input_schema=schema(
        {
            "action": string("restart | stop. Default restart."),
            "safe_mode": boolean("Restart into safe mode, loading no custom integrations."),
        }
    ),
    write=True,
    admin=True,
    dangerous=True,
    destructive=True,
)
async def restart_home_assistant(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Restart or stop Home Assistant."""
    context.check_admin()
    action = str(args.get("action", "restart")).lower()
    if action not in ("restart", "stop"):
        raise InvalidInput("`action` must be restart or stop")
    data = {"safe_mode": True} if args.get("safe_mode") and action == "restart" else {}
    await context.hass.services.async_call(
        "homeassistant", action, data, blocking=False, context=context.ha_context
    )
    return {
        action: True,
        "note": "Home Assistant is going down. Reconnect in a minute.",
    }


@tool(
    name="list_users",
    group=GROUP_SYSTEM,
    title="List users",
    description="""
Home Assistant user accounts with their groups and whether they are administrators.
Useful for working out whose context an automation runs in, or why a user cannot see
an entity.
""",
    input_schema=schema({}),
    admin=True,
)
async def list_users(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List users."""
    context.check_admin()
    users = await context.ws.call("config/auth/list")
    return {"count": len(users or []), "users": users}
