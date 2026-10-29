"""Tools for calling services - the general way to control anything."""

from __future__ import annotations

from typing import Any

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.service import async_get_all_descriptions

from ..const import GROUP_CONTROL
from ..context import ToolContext
from ..errors import InvalidInput, MCPBridgeError
from ..registry import require, tool
from ..schema import array, boolean, number, obj, schema, string
from .targets import resolve_entity_ids, split_target


@tool(
    name="list_services",
    group=GROUP_CONTROL,
    title="List services",
    description="""
The service catalog: every callable service with its description, its fields and
what it can target. This is the authoritative reference for what you can do - read
it before calling a service you have not used here before, because fields differ
between integrations. Filter by domain to keep the response small.
""",
    input_schema=schema(
        {
            "domain": string("Only services in this domain, e.g. `light`."),
            "service": string("Only this service name, e.g. `turn_on`."),
            "search": string("Case-insensitive match on the service name or description."),
            "include_fields": boolean(
                "Include each service's field schema. Default true.", default=True
            ),
        }
    ),
)
async def list_services(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List available services."""
    hass = context.hass
    descriptions = await async_get_all_descriptions(hass)
    wanted_domain = args.get("domain")
    wanted_service = args.get("service")
    search = (args.get("search") or "").lower()
    include_fields = args.get("include_fields", True)

    services: list[dict[str, Any]] = []
    for domain, domain_services in descriptions.items():
        if wanted_domain and domain != wanted_domain:
            continue
        for name, description in domain_services.items():
            if wanted_service and name != wanted_service:
                continue
            text = f"{domain}.{name} {description.get('description', '')}".lower()
            if search and search not in text:
                continue
            entry: dict[str, Any] = {
                "service": f"{domain}.{name}",
                "name": description.get("name"),
                "description": description.get("description"),
            }
            if target := description.get("target"):
                entry["target"] = target
            if include_fields:
                entry["fields"] = description.get("fields") or {}
            response = hass.services.supports_response(domain, name)
            if response is not SupportsResponse.NONE:
                entry["returns_response"] = response.value
            services.append(entry)

    services.sort(key=lambda item: item["service"])
    total = len(services)
    limited = context.limit(services)
    return {
        "count": len(limited),
        "total_matching": total,
        "truncated": len(limited) < total,
        "services": limited,
    }


@tool(
    name="call_service",
    group=GROUP_CONTROL,
    title="Call a service",
    description="""
Call any Home Assistant service. This is the general-purpose way to control the
home: turn things on and off, set temperatures, send notifications, press buttons,
run scripts, and anything an integration offers.

Pass targets either in `target` (`entity_id`, `device_id`, `area_id`, `floor_id`,
`label_id`) or inline in `data`. Check `list_services` for the fields a service
accepts. Some services return data - set `return_response` for those.
""",
    input_schema=schema(
        {
            "domain": string("Service domain, e.g. `light`."),
            "service": string(
                "Service name, e.g. `turn_on`. May also be given as `light.turn_on` in `domain`."
            ),
            "data": obj("Service parameters, e.g. {\"brightness_pct\": 60}."),
            "target": obj(
                "What to act on.",
                {
                    "entity_id": array("Entity ids."),
                    "device_id": array("Device ids."),
                    "area_id": array("Area ids."),
                    "floor_id": array("Floor ids."),
                    "label_id": array("Label ids."),
                },
            ),
            "blocking": boolean(
                "Wait for the service to finish. Default true, so failures surface.",
                default=True,
            ),
            "return_response": boolean(
                "Ask for the service's response data. Only for services that provide one."
            ),
            "timeout": number("Seconds to wait when blocking. Default 60.", default=60),
        },
        ["domain"],
    ),
    write=True,
    destructive=True,
)
async def call_service(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Call a service."""
    (raw_domain,) = require(args, "domain")
    domain, service = _split_service(raw_domain, args.get("service"))
    hass = context.hass

    if not hass.services.has_service(domain, service):
        available = sorted(hass.services.async_services_for_domain(domain))
        raise InvalidInput(
            f"No service {domain}.{service}. "
            + (
                f"Available in {domain}: {', '.join(available)}"
                if available
                else f"Domain {domain!r} has no services."
            )
        )

    target, inline = split_target({**(args.get("data") or {}), "target": args.get("target") or {}})
    service_data = {**inline}

    # Permission and exposure checks run against the entities the target resolves
    # to, so an area-wide call cannot reach a hidden entity.
    affected = resolve_entity_ids(context, target)
    if affected:
        context.check_control(*affected)
    elif any(target.values()):
        raise InvalidInput(
            "The target did not resolve to any entity. Check the ids with list_entities, "
            "list_areas or list_devices."
        )

    return_response = bool(args.get("return_response"))
    supports = hass.services.supports_response(domain, service)
    if return_response and supports is SupportsResponse.NONE:
        raise InvalidInput(f"{domain}.{service} does not return a response")
    if supports is SupportsResponse.ONLY:
        return_response = True

    call_target = {key: value for key, value in target.items() if value}
    # Home Assistant merges the target into service_data in place, so keep a copy
    # for the response.
    echoed_data = dict(service_data)
    try:
        response = await hass.services.async_call(
            domain,
            service,
            service_data,
            blocking=bool(args.get("blocking", True)),
            context=context.ha_context,
            target=call_target or None,
            return_response=return_response,
        )
    except ServiceNotFound as err:
        raise InvalidInput(str(err)) from err
    except HomeAssistantError as err:
        raise MCPBridgeError(f"{domain}.{service} failed: {err}") from err

    result: dict[str, Any] = {
        "called": f"{domain}.{service}",
        "target": call_target,
        "data": echoed_data,
    }
    if affected:
        result["affected_entities"] = affected
        result["new_states"] = {
            entity_id: state.state
            for entity_id in affected
            if (state := hass.states.get(entity_id)) is not None
        }
    if return_response:
        result["response"] = response
    return result


@tool(
    name="set_state",
    group=GROUP_CONTROL,
    title="Set state directly",
    description="""
Write a state into the state machine without going through the integration that
owns the entity. This is a debugging tool: the real integration will overwrite the
value on its next update, and for most entities you want `call_service` instead.
Useful for driving template sensors and testing automations.
""",
    input_schema=schema(
        {
            "entity_id": string("Entity id to write. May be an entity that does not exist yet."),
            "state": string("The new state value."),
            "attributes": obj("Attributes to set alongside the state."),
        },
        ["entity_id", "state"],
    ),
    write=True,
    admin=True,
    dangerous=True,
    destructive=True,
)
async def set_state(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Set a state directly."""
    entity_id, state = require(args, "entity_id", "state")
    context.check_admin()
    context.check_exposed(entity_id)
    context.hass.states.async_set(
        entity_id, state, args.get("attributes") or {}, context=context.ha_context
    )
    return {"entity_id": entity_id, "state": state, "note": "State set directly."}


def _split_service(domain: str, service: str | None) -> tuple[str, str]:
    """Accept either (`light`, `turn_on`) or a single `light.turn_on`."""
    if service:
        return domain, service
    if "." in domain:
        first, _, second = domain.partition(".")
        return first, second
    raise InvalidInput(
        "Provide both `domain` and `service`, or a full service name like `light.turn_on`."
    )
