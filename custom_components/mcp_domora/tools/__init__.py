"""Tool implementations.

Importing this package registers every tool. Each module calls the `tool`
decorator at import time, so adding a module here is all it takes to add tools -
the MCP tool list and the options UI both read from the registry.
"""

from . import (  # noqa: F401
    addon_development,
    automations,
    dashboards,
    events,
    helpers,
    history,
    integrations,
    media,
    raw,
    registries,
    scripts_scenes,
    services,
    states,
    supervisor,
    system,
    templates,
)

__all__ = [
    "addon_development",
    "automations",
    "dashboards",
    "events",
    "helpers",
    "history",
    "integrations",
    "media",
    "raw",
    "registries",
    "scripts_scenes",
    "services",
    "states",
    "supervisor",
    "system",
    "templates",
]
