"""Event bus tools."""

from __future__ import annotations

from typing import Any

from ..const import GROUP_EVENTS
from ..context import ToolContext
from ..errors import InvalidInput
from ..registry import require, tool
from ..schema import integer, number, obj, schema, string


@tool(
    name="list_event_listeners",
    group=GROUP_EVENTS,
    title="List event types",
    description="""
Every event type something is currently listening for, with the number of listeners.
This is how you discover what event an integration fires so you can trigger on it -
look for domain-specific names like `zha_event` or `mqtt_message_received`.
""",
    input_schema=schema({"search": string("Case-insensitive substring match.")}),
)
async def list_event_listeners(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List event types with listeners."""
    search = (args.get("search") or "").lower()
    listeners = context.hass.bus.async_listeners()
    matching = {
        event: count for event, count in listeners.items() if not search or search in event.lower()
    }
    return {
        "count": len(matching),
        "events": dict(sorted(matching.items())),
    }


@tool(
    name="fire_event",
    group=GROUP_EVENTS,
    title="Fire an event",
    description="""
Fire a custom event on the event bus. Mainly useful for testing an automation that
triggers on an event, and for the `custom_event` pattern where several automations
listen for one named event.
""",
    input_schema=schema(
        {
            "event_type": string("The event name, e.g. `my_custom_event`."),
            "event_data": obj("The event payload."),
        },
        ["event_type"],
    ),
    write=True,
    destructive=True,
)
async def fire_event(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Fire an event."""
    (event_type,) = require(args, "event_type")
    data = args.get("event_data") or {}
    if not isinstance(data, dict):
        raise InvalidInput("`event_data` must be an object")
    context.hass.bus.async_fire(str(event_type), data, context=context.ha_context)
    return {"fired": event_type, "data": data}


@tool(
    name="listen_for_events",
    group=GROUP_EVENTS,
    title="Listen for events",
    description="""
Wait for events of a given type and return the ones that arrive, up to a limit or a
timeout. This is the way to find out what a physical control actually sends: listen
for the integration's event type, ask the user to press the button, and read the
payload.

Blocks for up to `timeout` seconds, so keep it short and tell the user to act now.
""",
    input_schema=schema(
        {
            "event_type": string("Which event to listen for."),
            "count": integer("Stop after this many events. Default 1.", default=1),
            "timeout": number("Seconds to wait. Default 15, maximum 120.", default=15),
        },
        ["event_type"],
    ),
)
async def listen_for_events(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Collect events as they happen."""
    (event_type,) = require(args, "event_type")
    count = max(1, int(args.get("count", 1)))
    timeout = min(float(args.get("timeout", 15)), 120.0)

    result = await context.ws.call(
        "subscribe_events",
        {"event_type": str(event_type)},
        wait_events=count,
        event_timeout=timeout,
        timeout=timeout + 10,
    )
    events = result.get("events", []) if isinstance(result, dict) else []
    return {
        "event_type": event_type,
        "received": len(events),
        "timed_out": len(events) < count,
        "events": events,
    }
