"""Config and options flow.

The options flow is where every tool and every domain is switched on or off. The
tool list is read from the registry, so it always matches what the server actually
offers.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    CONF_ALLOW_DANGEROUS,
    CONF_ALLOW_HA_TOKENS,
    CONF_ALLOWED_DOMAINS,
    CONF_DISABLED_TOOLS,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDED_DOMAINS,
    CONF_EXPOSE_HIDDEN,
    CONF_INCLUDE_AREAS,
    CONF_INCLUDE_ENTITIES,
    CONF_INCLUDE_LABELS,
    CONF_MAX_RESULTS,
    CONF_READ_ONLY,
    CONF_REQUIRE_ADMIN,
    CONF_REVOKE_CLIENTS,
    CONF_TOOL_GROUPS,
    DEFAULT_EXCLUDED_DOMAINS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_TOOL_GROUPS,
    DOMAIN,
    MCP_PATH,
    NAME,
    TOOL_GROUP_LABELS,
)
from .registry import all_tools

DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_TOOL_GROUPS: list(DEFAULT_TOOL_GROUPS),
    CONF_DISABLED_TOOLS: [],
    CONF_ALLOWED_DOMAINS: [],
    CONF_EXCLUDED_DOMAINS: list(DEFAULT_EXCLUDED_DOMAINS),
    CONF_INCLUDE_ENTITIES: [],
    CONF_EXCLUDE_ENTITIES: [],
    CONF_INCLUDE_AREAS: [],
    CONF_INCLUDE_LABELS: [],
    CONF_EXPOSE_HIDDEN: False,
    CONF_READ_ONLY: False,
    CONF_ALLOW_DANGEROUS: False,
    CONF_REQUIRE_ADMIN: False,
    CONF_ALLOW_HA_TOKENS: True,
    CONF_MAX_RESULTS: DEFAULT_MAX_RESULTS,
}


def _mcp_url(hass: Any) -> str:
    """The URL to hand to an MCP client."""
    for kwargs in ({"prefer_external": True}, {"allow_internal": True}):
        try:
            return f"{get_url(hass, **kwargs).rstrip('/')}{MCP_PATH}"
        except NoURLAvailableError:
            continue
    return MCP_PATH


class MCPBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the MCP Bridge."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single config entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                description_placeholders={"url": _mcp_url(self.hass)},
            )
        return self.async_create_entry(title=NAME, data={}, options=DEFAULT_OPTIONS)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MCPBridgeOptionsFlow:
        """Return the options flow."""
        return MCPBridgeOptionsFlow()


class MCPBridgeOptionsFlow(OptionsFlow):
    """Configure tools, entity exposure, security and connected clients."""

    def __init__(self) -> None:
        """Initialise."""
        self._options: dict[str, Any] = {}

    @property
    def options(self) -> dict[str, Any]:
        """The options being edited."""
        if not self._options:
            self._options = {**DEFAULT_OPTIONS, **dict(self.config_entry.options)}
        return self._options

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["tool_groups", "tools", "entities", "security", "clients"],
            description_placeholders={"url": _mcp_url(self.hass)},
        )

    # Tool groups -------------------------------------------------------------
    async def async_step_tool_groups(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose which groups of tools to offer."""
        if user_input is not None:
            return await self._async_save({CONF_TOOL_GROUPS: user_input[CONF_TOOL_GROUPS]})

        return self.async_show_form(
            step_id="tool_groups",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TOOL_GROUPS, default=self.options[CONF_TOOL_GROUPS]
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=group, label=label)
                                for group, label in TOOL_GROUP_LABELS.items()
                            ],
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    # Individual tools --------------------------------------------------------
    async def async_step_tools(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Switch individual tools on or off."""
        tools = all_tools()
        if user_input is not None:
            enabled = set(user_input.get("enabled_tools") or ())
            return await self._async_save(
                {CONF_DISABLED_TOOLS: sorted(set(tools) - enabled)}
            )

        disabled = set(self.options[CONF_DISABLED_TOOLS])
        enabled_groups = set(self.options[CONF_TOOL_GROUPS])
        options = [
            selector.SelectOptionDict(
                value=name,
                label=f"{TOOL_GROUP_LABELS.get(tool.group, tool.group).split(' (')[0]}: {name}"
                + ("" if tool.group in enabled_groups else "  [group disabled]"),
            )
            for name, tool in sorted(tools.items(), key=lambda kv: (kv[1].group, kv[0]))
        ]
        return self.async_show_form(
            step_id="tools",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "enabled_tools",
                        default=sorted(set(tools) - disabled),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            description_placeholders={"count": str(len(tools))},
        )

    # Entity exposure ---------------------------------------------------------
    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose which entities MCP clients may see."""
        if user_input is not None:
            return await self._async_save(
                {
                    CONF_ALLOWED_DOMAINS: user_input.get(CONF_ALLOWED_DOMAINS) or [],
                    CONF_EXCLUDED_DOMAINS: user_input.get(CONF_EXCLUDED_DOMAINS) or [],
                    CONF_INCLUDE_ENTITIES: user_input.get(CONF_INCLUDE_ENTITIES) or [],
                    CONF_EXCLUDE_ENTITIES: user_input.get(CONF_EXCLUDE_ENTITIES) or [],
                    CONF_INCLUDE_AREAS: user_input.get(CONF_INCLUDE_AREAS) or [],
                    CONF_INCLUDE_LABELS: user_input.get(CONF_INCLUDE_LABELS) or [],
                    CONF_EXPOSE_HIDDEN: user_input.get(CONF_EXPOSE_HIDDEN, False),
                }
            )

        domains = sorted({state.domain for state in self.hass.states.async_all()})
        domain_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=domains,
                multiple=True,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        entity_selector = selector.EntitySelector(
            selector.EntitySelectorConfig(multiple=True)
        )
        return self.async_show_form(
            step_id="entities",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ALLOWED_DOMAINS, default=self.options[CONF_ALLOWED_DOMAINS]
                    ): domain_selector,
                    vol.Optional(
                        CONF_EXCLUDED_DOMAINS, default=self.options[CONF_EXCLUDED_DOMAINS]
                    ): domain_selector,
                    vol.Optional(
                        CONF_EXCLUDE_ENTITIES, default=self.options[CONF_EXCLUDE_ENTITIES]
                    ): entity_selector,
                    vol.Optional(
                        CONF_INCLUDE_ENTITIES, default=self.options[CONF_INCLUDE_ENTITIES]
                    ): entity_selector,
                    vol.Optional(
                        CONF_INCLUDE_AREAS, default=self.options[CONF_INCLUDE_AREAS]
                    ): selector.AreaSelector(selector.AreaSelectorConfig(multiple=True)),
                    vol.Optional(
                        CONF_INCLUDE_LABELS, default=self.options[CONF_INCLUDE_LABELS]
                    ): selector.LabelSelector(selector.LabelSelectorConfig(multiple=True)),
                    vol.Optional(
                        CONF_EXPOSE_HIDDEN, default=self.options[CONF_EXPOSE_HIDDEN]
                    ): selector.BooleanSelector(),
                }
            ),
        )

    # Security ----------------------------------------------------------------
    async def async_step_security(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the safety limits."""
        if user_input is not None:
            return await self._async_save(user_input)

        return self.async_show_form(
            step_id="security",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_READ_ONLY, default=self.options[CONF_READ_ONLY]
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_ALLOW_DANGEROUS, default=self.options[CONF_ALLOW_DANGEROUS]
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_REQUIRE_ADMIN, default=self.options[CONF_REQUIRE_ADMIN]
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_ALLOW_HA_TOKENS, default=self.options[CONF_ALLOW_HA_TOKENS]
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_MAX_RESULTS, default=self.options[CONF_MAX_RESULTS]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=10, max=5000, step=10, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
        )

    # Connected clients -------------------------------------------------------
    async def async_step_clients(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Review and revoke connected MCP clients."""
        runtime = self.hass.data.get(DOMAIN)
        if runtime is None:
            return self.async_abort(reason="not_loaded")

        if user_input is not None:
            for token_id in user_input.get(CONF_REVOKE_CLIENTS) or ():
                await runtime.store.async_revoke(token_id)
                runtime.sessions.revoke_token(token_id)
            return self.async_create_entry(data=self.options)

        clients = runtime.store.connected_clients()
        if not clients:
            return self.async_show_form(
                step_id="clients",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "clients": "No MCP client has connected yet.",
                    "url": _mcp_url(self.hass),
                },
            )

        import datetime  # noqa: PLC0415

        options = []
        summary_lines = []
        for client in clients:
            user = await self.hass.auth.async_get_user(client["user_id"])
            created = datetime.datetime.fromtimestamp(client["created_at"]).strftime(
                "%Y-%m-%d %H:%M"
            )
            label = f"{client['client_name']} ({user.name if user else 'unknown user'}, since {created})"
            options.append(selector.SelectOptionDict(value=client["token_id"], label=label))
            summary_lines.append(f"- {label}")

        return self.async_show_form(
            step_id="clients",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_REVOKE_CLIENTS, default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={
                "clients": "\n".join(summary_lines),
                "url": _mcp_url(self.hass),
            },
        )

    async def _async_save(self, changes: dict[str, Any]) -> ConfigFlowResult:
        """Persist the changed options."""
        merged = {**self.options, **changes}
        if CONF_MAX_RESULTS in merged:
            merged[CONF_MAX_RESULTS] = int(merged[CONF_MAX_RESULTS])
        return self.async_create_entry(data=merged)
