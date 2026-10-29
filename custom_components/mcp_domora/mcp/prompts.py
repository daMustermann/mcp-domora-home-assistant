"""MCP prompts: reusable starting points for common Home Assistant work."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from ..errors import InvalidInput

PROMPTS: dict[str, dict[str, Any]] = {
    "home_overview": {
        "title": "Summarise this home",
        "description": "Walk the areas and entities and describe what this home contains.",
        "arguments": [],
        "template": (
            "Use get_overview, then list_entities for anything that looks interesting, "
            "and give me a short tour of this home: which areas exist, what is in them, "
            "and anything that looks unhealthy (unavailable entities, low batteries, "
            "devices that have not reported recently)."
        ),
    },
    "create_automation": {
        "title": "Build an automation",
        "description": "Design, validate and save a new automation for a described goal.",
        "arguments": [
            {"name": "goal", "description": "What the automation should do.", "required": True}
        ],
        "template": (
            "I want an automation that does the following:\n\n{goal}\n\n"
            "Work like this:\n"
            "1. Find the entities involved with list_entities, and check their current "
            "state and attributes with get_state so you use real values.\n"
            "2. If a device is involved, call list_device_automations to see the triggers "
            "and actions Home Assistant offers for it, and prefer those.\n"
            "3. Draft the config, then check it with validate_automation_config.\n"
            "4. Save it with create_automation, then show me the saved config.\n"
            "Do not invent entity ids - verify every one of them first."
        ),
    },
    "debug_automation": {
        "title": "Debug an automation",
        "description": "Work out why an automation is not behaving as expected.",
        "arguments": [
            {
                "name": "automation",
                "description": "Entity id, alias or id of the automation.",
                "required": True,
            }
        ],
        "template": (
            "The automation `{automation}` is not working as expected.\n\n"
            "Read its config with get_automation, check whether it is enabled and when it "
            "last triggered, then pull its recent runs with get_automation_traces. "
            "Explain which trigger fired, which condition blocked it or which action "
            "failed, and propose a concrete fix. Do not change anything until I agree."
        ),
    },
    "audit_exposure": {
        "title": "Review what is exposed",
        "description": "Check which entities and tools this MCP connection can reach.",
        "arguments": [],
        "template": (
            "List the tools you have available and summarise them by capability. "
            "Then call get_overview and tell me roughly how many entities you can see "
            "per domain, and whether anything looks like it should not be exposed to an "
            "AI assistant (locks, alarms, covers, cameras, anything safety related)."
        ),
    },
}


def list_prompts() -> list[dict[str, Any]]:
    """Advertise the prompts."""
    return [
        {
            "name": name,
            "title": prompt["title"],
            "description": prompt["description"],
            "arguments": prompt["arguments"],
        }
        for name, prompt in PROMPTS.items()
    ]


async def async_get(
    context: ToolContext, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Render a prompt."""
    prompt = PROMPTS.get(name)
    if prompt is None:
        raise InvalidInput(f"Unknown prompt: {name!r}")

    for argument in prompt["arguments"]:
        if argument.get("required") and not arguments.get(argument["name"]):
            raise InvalidInput(f"Prompt {name!r} requires argument {argument['name']!r}")

    try:
        text = prompt["template"].format(**arguments)
    except KeyError as err:
        raise InvalidInput(f"Missing prompt argument: {err}") from err

    return {
        "description": prompt["description"],
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    }
