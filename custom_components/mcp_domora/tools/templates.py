"""Template rendering."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import TemplateError
from homeassistant.helpers.template import Template

from ..const import GROUP_TEMPLATE
from ..context import ToolContext
from ..errors import InvalidInput
from ..registry import require, tool
from ..schema import boolean, obj, schema, string


@tool(
    name="render_template",
    group=GROUP_TEMPLATE,
    title="Render a template",
    description="""
Evaluate a Jinja template against the live state machine and return the result.

This is the fastest way to check a template before putting it in an automation,
a template sensor or a notification - and it doubles as a query language, since one
template can filter and aggregate across hundreds of entities far more cheaply than
listing them all. For example:

  {{ states.sensor | selectattr('attributes.device_class','eq','battery')
     | selectattr('state','lt','20') | map(attribute='entity_id') | list }}

Errors come back with the message Home Assistant would log, so a failed render tells
you exactly what to fix.
""",
    input_schema=schema(
        {
            "template": string("The Jinja template to render."),
            "variables": obj("Variables available to the template."),
            "report_errors": boolean(
                "Return the error instead of raising it. Default true.", default=True
            ),
        },
        ["template"],
    ),
)
async def render_template(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Render a template."""
    (template_text,) = require(args, "template")
    variables = args.get("variables") or {}
    if not isinstance(variables, dict):
        raise InvalidInput("`variables` must be an object")

    template = Template(str(template_text), context.hass)
    try:
        result = template.async_render(variables=variables, parse_result=True)
    except TemplateError as err:
        if args.get("report_errors", True):
            return {"template": template_text, "error": str(err), "rendered": None}
        raise InvalidInput(f"Template error: {err}") from err

    return {
        "template": template_text,
        "rendered": result,
        "result_type": type(result).__name__,
    }


@tool(
    name="list_template_entities",
    group=GROUP_TEMPLATE,
    title="Find entities referenced by a template",
    description="""
Which entities a template depends on, without rendering it. Useful for checking that
a template listens to what you expect before using it as a trigger.
""",
    input_schema=schema({"template": string("The Jinja template to analyse.")}, ["template"]),
)
async def list_template_entities(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Report a template's dependencies."""
    (template_text,) = require(args, "template")
    template = Template(str(template_text), context.hass)
    try:
        info = template.async_render_to_info()
        return {
            "entities": sorted(info.entities),
            "domains": sorted(info.domains),
            "all_states": info.all_states,
            "rate_limit": str(info.rate_limit) if info.rate_limit else None,
        }
    except TemplateError as err:
        return {"error": str(err)}
