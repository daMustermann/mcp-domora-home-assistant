"""The escape hatch: direct access to the WebSocket API."""

from __future__ import annotations

from typing import Any

from ..const import GROUP_RAW
from ..context import ToolContext
from ..registry import require, tool
from ..schema import integer, number, obj, schema, string


@tool(
    name="list_websocket_commands",
    group=GROUP_RAW,
    title="List WebSocket commands",
    description="""
Every WebSocket API command this instance supports. Anything the Home Assistant
frontend can do is in here, so when no dedicated tool covers what you need, look for
a command and call it with `websocket_command`.
""",
    input_schema=schema({"search": string("Case-insensitive substring match.")}),
)
async def list_websocket_commands(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List WebSocket commands."""
    search = (args.get("search") or "").lower()
    commands = [
        command for command in context.ws.available_commands if not search or search in command
    ]
    return {
        "count": len(commands),
        "total": len(context.ws.available_commands),
        "commands": context.limit(commands, 1000),
    }


@tool(
    name="websocket_command",
    group=GROUP_RAW,
    title="Call a WebSocket command",
    description="""
Call any Home Assistant WebSocket API command directly, as the signed-in user. This
reaches everything the frontend can do, including corners with no dedicated tool
here, and Home Assistant's own permission checks still apply.

Pass the command in `type` and its parameters in `payload` (do not include `id`).
For a subscription command, set `wait_events` to collect that many pushed events
before returning; the subscription is then closed.

Prefer a dedicated tool when one exists - they validate input and give better errors.
Use `list_websocket_commands` to find a command name.
""",
    input_schema=schema(
        {
            "type": string("The command type, e.g. `config/entity_registry/list`."),
            "payload": obj("The command's parameters, without `id`."),
            "wait_events": integer(
                "For subscription commands, how many events to collect. Default 0."
            ),
            "timeout": number("Seconds to wait for the result. Default 30."),
        },
        ["type"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def websocket_command(context: ToolContext, args: dict[str, Any]) -> Any:
    """Call a WebSocket command."""
    (command,) = require(args, "type")
    context.check_admin()
    result = await context.ws.call(
        str(command),
        args.get("payload") or {},
        wait_events=int(args.get("wait_events") or 0),
        timeout=float(args.get("timeout") or 30.0),
    )
    return {"type": command, "result": result}
