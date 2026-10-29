"""History, logbook and long-term statistics."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from ..const import GROUP_HISTORY
from ..context import ToolContext
from ..errors import InvalidInput
from ..registry import require, tool
from ..schema import array, boolean, enum, integer, schema, string

TIME_HELP = (
    "ISO 8601 timestamp, or a relative shorthand like `-2h`, `-30m`, `-7d`. "
    "Defaults to one day ago."
)


def _parse_time(value: str | None, default_hours: int = 24) -> Any:
    """Parse an absolute or relative timestamp."""
    if not value:
        return dt_util.utcnow() - timedelta(hours=default_hours)
    text = str(value).strip()
    if text.startswith("-") and text[-1] in "smhd":
        try:
            amount = float(text[1:-1])
        except ValueError as err:
            raise InvalidInput(f"Could not read the relative time {value!r}") from err
        unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[text[-1]]
        return dt_util.utcnow() - timedelta(**{unit: amount})
    parsed = dt_util.parse_datetime(text)
    if parsed is None:
        raise InvalidInput(
            f"Could not read the timestamp {value!r}. Use ISO 8601, or a shorthand like `-2h`."
        )
    return dt_util.as_utc(parsed)


def _require_recorder(context: ToolContext) -> None:
    """Fail with a clear message when the recorder is not available."""
    if "recorder" not in context.hass.config.components:
        raise InvalidInput(
            "The recorder integration is not loaded, so no history is being stored."
        )


@tool(
    name="get_history",
    group=GROUP_HISTORY,
    title="Get state history",
    description="""
How entities changed over a period. Use this to answer "when did X last happen", to
check whether a sensor is reporting, or to see the state an automation reacted to.

Keep the entity list and the window small - a day of a frequently-changing sensor is
thousands of points. `minimal_response` returns only state changes without
attributes, which is usually what you want.
""",
    input_schema=schema(
        {
            "entity_ids": array("Which entities to fetch. Required."),
            "start_time": string(TIME_HELP),
            "end_time": string("ISO 8601 timestamp. Defaults to now."),
            "minimal_response": boolean(
                "Omit attributes and return only state changes. Default true.", default=True
            ),
            "significant_changes_only": boolean(
                "Skip insignificant intermediate changes. Default true.", default=True
            ),
        },
        ["entity_ids"],
    ),
)
async def get_history(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read state history."""
    _require_recorder(context)
    (entity_ids,) = require(args, "entity_ids")
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]
    context.check_read(*entity_ids)

    start = _parse_time(args.get("start_time"))
    payload: dict[str, Any] = {
        "start_time": start.isoformat(),
        "entity_ids": list(entity_ids),
        "minimal_response": bool(args.get("minimal_response", True)),
        "significant_changes_only": bool(args.get("significant_changes_only", True)),
        "no_attributes": bool(args.get("minimal_response", True)),
    }
    if end_time := args.get("end_time"):
        payload["end_time"] = _parse_time(end_time, 0).isoformat()

    history = await context.ws.call("history/history_during_period", payload)
    return {
        "start_time": payload["start_time"],
        "end_time": payload.get("end_time"),
        "entity_count": len(history or {}),
        "history": history,
    }


@tool(
    name="get_logbook",
    group=GROUP_HISTORY,
    title="Get logbook entries",
    description="""
The human-readable event log: what happened, when, and what caused it. Logbook
entries name the automation or user behind a change, which makes this the right tool
for "why did the light turn on at 3am".
""",
    input_schema=schema(
        {
            "entity_ids": array("Limit to these entities."),
            "device_ids": array("Limit to these devices."),
            "start_time": string(TIME_HELP),
            "end_time": string("ISO 8601 timestamp. Defaults to now."),
        }
    ),
)
async def get_logbook(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read the logbook."""
    _require_recorder(context)
    start = _parse_time(args.get("start_time"))
    payload: dict[str, Any] = {"start_time": start.isoformat()}
    if entity_ids := args.get("entity_ids"):
        context.check_read(*entity_ids)
        payload["entity_ids"] = list(entity_ids)
    if device_ids := args.get("device_ids"):
        payload["device_ids"] = list(device_ids)
    if end_time := args.get("end_time"):
        payload["end_time"] = _parse_time(end_time, 0).isoformat()

    events = await context.ws.call("logbook/get_events", payload)
    entries = events if isinstance(events, list) else []
    return {
        "start_time": payload["start_time"],
        "count": len(entries),
        "entries": context.limit(entries),
    }


@tool(
    name="list_statistics",
    group=GROUP_HISTORY,
    title="List statistic ids",
    description="""
Which entities have long-term statistics, and in what unit. Statistics are hourly
and daily aggregates kept forever, unlike state history which is purged - so for
energy, temperature trends or anything older than the recorder's retention, use
statistics rather than history.
""",
    input_schema=schema(
        {
            "statistic_type": enum("Filter by type.", ["mean", "sum"]),
            "search": string("Case-insensitive match on the statistic id or name."),
        }
    ),
)
async def list_statistics(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List statistic ids."""
    _require_recorder(context)
    payload = {}
    if statistic_type := args.get("statistic_type"):
        payload["statistic_type"] = statistic_type
    items = await context.ws.call("recorder/list_statistic_ids", payload)
    search = (args.get("search") or "").lower()
    matching = [
        item
        for item in items or []
        if not search or search in str(item.get("statistic_id", "")).lower()
    ]
    return {"count": len(matching), "statistics": context.limit(matching)}


@tool(
    name="get_statistics",
    group=GROUP_HISTORY,
    title="Get statistics",
    description="""
Aggregated values over time for entities that record statistics. Pick the period to
match the question: `hour` for a day, `day` for a month, `month` for a year.

For energy and water meters use `sum` (a running total) and `change` (the amount per
period); for sensors use `mean`, `min` and `max`.
""",
    input_schema=schema(
        {
            "statistic_ids": array("Which statistics to fetch. Required."),
            "start_time": string(TIME_HELP),
            "end_time": string("ISO 8601 timestamp. Defaults to now."),
            "period": enum(
                "Aggregation period. Default hour.", ["5minute", "hour", "day", "week", "month"]
            ),
            "types": array("Which values to return: mean, min, max, sum, state, change."),
            "units": string("Unit conversion, as a JSON object per device class."),
        },
        ["statistic_ids"],
    ),
)
async def get_statistics(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read statistics."""
    _require_recorder(context)
    (statistic_ids,) = require(args, "statistic_ids")
    if isinstance(statistic_ids, str):
        statistic_ids = [statistic_ids]
    start = _parse_time(args.get("start_time"))
    payload: dict[str, Any] = {
        "statistic_ids": list(statistic_ids),
        "start_time": start.isoformat(),
        "period": args.get("period", "hour"),
        "types": args.get("types") or ["mean", "min", "max", "sum", "change"],
    }
    if end_time := args.get("end_time"):
        payload["end_time"] = _parse_time(end_time, 0).isoformat()

    statistics = await context.ws.call("recorder/statistics_during_period", payload)
    return {
        "period": payload["period"],
        "start_time": payload["start_time"],
        "statistics": statistics,
    }
