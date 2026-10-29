"""MCP Domora: a Model Context Protocol server for Home Assistant.

Exposes Home Assistant to MCP clients over Streamable HTTP with OAuth 2.1 /
IndieAuth authentication, and gives them tools for everything from reading states to
creating automations. Which tools exist, and which entities they can see, is
configured per domain and per tool in the integration options.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.auth.models import RefreshToken, User
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .auth import ALL_VIEWS as AUTH_VIEWS, AuthStore
from .const import (
    CONF_ALLOW_DANGEROUS,
    CONF_ALLOW_HA_TOKENS,
    CONF_DISABLED_TOOLS,
    CONF_READ_ONLY,
    CONF_REQUIRE_ADMIN,
    CONF_TOOL_GROUPS,
    DEFAULT_TOOL_GROUPS,
    DOMAIN,
    MCP_PATH,
)
from .context import ToolContext
from .errors import ToolDisabled, ToolNotFound
from .exposure import Exposure
from .mcp import ALL_VIEWS as MCP_VIEWS, MCPServer, SessionManager
from .registry import ToolDef, all_tools
from .ws import WebSocketInvoker

_LOGGER = logging.getLogger(__name__)

VIEWS_KEY = f"{DOMAIN}_views_registered"
PURGE_INTERVAL = timedelta(minutes=30)


class BridgeRuntime:
    """Everything the HTTP views need, for the lifetime of the config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self.entry = entry
        self.store = AuthStore(hass)
        self.sessions = SessionManager()
        self.server = MCPServer(self)
        #: Consent forms awaiting submission, keyed by a one-shot token.
        self.consents: dict[str, dict[str, Any]] = {}
        #: Flow id -> "config" | "options", shared across requests.
        self.flows: dict[str, str] = {}
        self.loaded = False

    @property
    def options(self) -> dict[str, Any]:
        """The current options."""
        return dict(self.entry.options)

    # Setup -------------------------------------------------------------------
    async def async_setup(self) -> None:
        """Load state and start the background purge."""
        await self.store.async_load()
        self.loaded = True
        self.entry.async_on_unload(
            async_track_time_interval(self.hass, self._async_purge, PURGE_INTERVAL)
        )

    async def _async_purge(self, _now: Any) -> None:
        """Drop expired tokens, codes and sessions."""
        await self.store.async_purge()
        self.sessions.purge()
        for key, consent in list(self.consents.items()):
            if _now.timestamp() - consent["created_at"] > 600:
                del self.consents[key]

    def async_shutdown(self) -> None:
        """Mark the runtime unavailable; the views stay registered."""
        self.loaded = False

    # Authentication ----------------------------------------------------------
    async def async_build_context(
        self, token: str
    ) -> tuple[ToolContext | None, str | None]:
        """Resolve a bearer token into a tool context, or explain the refusal."""
        user: User | None = None
        refresh_token: RefreshToken | None = None
        token_id: str | None = None
        scopes: frozenset[str] = frozenset()

        if (record := self.store.resolve_access_token(token)) is not None:
            if record.access_expired:
                return None, "The access token has expired; refresh it"
            refresh_token = self.hass.auth.async_get_refresh_token(
                record.ha_refresh_token_id
            )
            if refresh_token is None:
                await self.store.async_revoke(record.token_id, revoke_ha=False)
                return None, "The Home Assistant session behind this token was revoked"
            user = refresh_token.user
            token_id = record.token_id
            scopes = frozenset(record.scopes)
            self.store.touch(record)
        elif self.options.get(CONF_ALLOW_HA_TOKENS, True):
            refresh_token = self.hass.auth.async_validate_access_token(token)
            if refresh_token is None:
                return None, "Invalid token"
            user = refresh_token.user
            scopes = frozenset(("homeassistant:read", "homeassistant:write", "homeassistant:admin"))
        else:
            return None, "Invalid token"

        if not user.is_active:
            return None, "This Home Assistant user is deactivated"
        if self.options.get(CONF_REQUIRE_ADMIN, False) and not user.is_admin:
            return None, "This MCP server is restricted to Home Assistant administrators"

        context = ToolContext(
            hass=self.hass,
            user=user,
            refresh_token=refresh_token,
            options=self.options,
            exposure=Exposure.from_options(self.hass, self.options),
            ws=WebSocketInvoker(self.hass, user, refresh_token),
            scopes=scopes,
            token_id=token_id,
            runtime_flows=self.flows,
        )
        return context, None

    # Tool gating -------------------------------------------------------------
    def available_tools(self, user: User) -> list[ToolDef]:
        """The tools this configuration and this user allow."""
        options = self.options
        groups = set(options.get(CONF_TOOL_GROUPS, DEFAULT_TOOL_GROUPS))
        disabled = set(options.get(CONF_DISABLED_TOOLS) or ())
        read_only = bool(options.get(CONF_READ_ONLY, False))
        allow_dangerous = bool(options.get(CONF_ALLOW_DANGEROUS, False))

        return [
            tool
            for tool in all_tools().values()
            if tool.group in groups
            and tool.name not in disabled
            and not (read_only and tool.write)
            and not (tool.dangerous and not allow_dangerous)
            and not (tool.admin and not user.is_admin)
        ]

    def get_tool(self, name: str, user: User) -> ToolDef:
        """One tool, if it is allowed."""
        tool = all_tools().get(name)
        if tool is None:
            raise ToolNotFound(
                f"No tool named {name!r}. Call tools/list to see what is available."
            )
        if tool not in self.available_tools(user):
            raise ToolDisabled(self._why_disabled(tool, user))
        return tool

    def _why_disabled(self, tool: ToolDef, user: User) -> str:
        """Explain why a tool is unavailable, so the model stops retrying."""
        options = self.options
        if tool.admin and not user.is_admin:
            return f"{tool.name} needs a Home Assistant administrator account."
        if tool.name in set(options.get(CONF_DISABLED_TOOLS) or ()):
            return f"{tool.name} is switched off in the MCP Domora options."
        if tool.group not in set(options.get(CONF_TOOL_GROUPS, DEFAULT_TOOL_GROUPS)):
            return (
                f"{tool.name} belongs to the {tool.group!r} tool group, which is not "
                "enabled in the MCP Domora options."
            )
        if tool.write and options.get(CONF_READ_ONLY, False):
            return f"{tool.name} changes things, and this MCP server is in read-only mode."
        if tool.dangerous and not options.get(CONF_ALLOW_DANGEROUS, False):
            return (
                f"{tool.name} is a disruptive tool and is disabled. The user can enable "
                '"allow disruptive tools" in the MCP Domora options.'
            )
        return f"{tool.name} is not available."


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the MCP Domora."""
    runtime = BridgeRuntime(hass, entry)
    await runtime.async_setup()
    hass.data[DOMAIN] = runtime

    # Views cannot be unregistered, so they are registered once per Home Assistant
    # run and read the runtime from hass.data on each request.
    if not hass.data.get(VIEWS_KEY):
        # Set the flag first: a failed registration must not leave half the views
        # registered and then register them again on the next attempt.
        hass.data[VIEWS_KEY] = True
        for view in (*AUTH_VIEWS, *MCP_VIEWS):
            hass.http.register_view(view())
        _LOGGER.debug("Registered %d MCP Domora views", len(AUTH_VIEWS) + len(MCP_VIEWS))

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _LOGGER.info(
        "MCP Domora ready: %d tools available at %s", len(all_tools()), MCP_PATH
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the MCP Domora."""
    runtime: BridgeRuntime | None = hass.data.pop(DOMAIN, None)
    if runtime is not None:
        runtime.async_shutdown()
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)
