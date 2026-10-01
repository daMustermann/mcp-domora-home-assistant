"""The MCP protocol: JSON-RPC dispatch for tools, resources and prompts."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant

from ..const import (
    LATEST_PROTOCOL_VERSION,
    NAME,
    SERVER_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from ..context import ToolContext
from ..errors import MCPBridgeError, ToolDisabled, ToolNotFound
from ..registry import ToolDef
from . import prompts as prompts_module
from . import resources as resources_module
from .results import ImageResult, MultiResult, TextResult
from .session import Session

_LOGGER = logging.getLogger(__name__)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

INSTRUCTIONS = f"""\
This server gives you full control over a Home Assistant instance.

Orientation:
- `get_overview` is the cheapest way to learn what this home contains.
- `list_entities` finds entities by domain, area, label or name; `get_state` reads them.
- `list_services` shows every callable service with its parameter schema. `call_service`
  calls any of them, which is how you control anything that has no dedicated tool.

Editing configuration:
- Automations, scripts and scenes can be listed, read, created, updated and deleted.
  Always read the current config before updating it, and pass the complete new config.
- `validate_automation_config` checks a config without saving it. Use it before writing.
- Automations stored in configuration.yaml are not editable; only UI/`automations.yaml`
  ones are. The `editable` flag in `list_automations` tells you which is which.
- After editing, `get_automation_traces` shows why an automation did or did not run.

Discovering what is possible:
- `list_device_automations` returns the device triggers, conditions and actions
  Home Assistant itself offers for a device. Prefer these over guessing state triggers.
- `render_template` evaluates Jinja templates, which is the fastest way to check a
  template before putting it in an automation.
- `websocket_command` reaches any Home Assistant WebSocket API command if no dedicated
  tool covers what you need. `list_websocket_commands` enumerates them.

Conventions:
- Times are ISO 8601. Entity ids are `domain.object_id`.
- Tools return JSON. Errors explain what to fix.
- Which tools exist, and which entities you can see, is configured by the user; a
  missing tool or entity is a deliberate setting, not a fault.

Protocol version: {LATEST_PROTOCOL_VERSION}."""


class JSONRPCError(Exception):
    """A protocol-level error that becomes a JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        """Initialise."""
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


class MCPServer:
    """Handles MCP requests for one Home Assistant instance."""

    def __init__(self, runtime: Any) -> None:
        """Initialise."""
        self.runtime = runtime

    @property
    def hass(self) -> HomeAssistant:
        """The Home Assistant instance."""
        return self.runtime.hass

    # Dispatch ----------------------------------------------------------------
    async def async_handle(
        self, message: Any, session: Session, context: ToolContext
    ) -> Any:
        """Handle one JSON-RPC message or batch. Returns None for notifications."""
        if isinstance(message, list):
            if not message:
                raise JSONRPCError(INVALID_REQUEST, "Empty batch")
            responses = [
                response
                for item in message
                if (response := await self.async_handle(item, session, context))
                is not None
            ]
            return responses or None

        if not isinstance(message, dict):
            raise JSONRPCError(INVALID_REQUEST, "Message must be a JSON object")

        method = message.get("method")
        msg_id = message.get("id")

        if method is None:
            # A response to something we sent; nothing to do.
            return None

        try:
            result = await self._async_dispatch(
                method, message.get("params") or {}, session, context
            )
        except JSONRPCError as err:
            if msg_id is None:
                return None
            return self._error(msg_id, err.code, err.message, err.data)
        except MCPBridgeError as err:
            # Bad arguments to a resource or prompt read; a tool call handles its
            # own errors in-band so the model can see them.
            if msg_id is None:
                return None
            return self._error(msg_id, INVALID_PARAMS, str(err))
        except Exception as err:  # noqa: BLE001 - never drop a connection over one call
            _LOGGER.exception("Error handling MCP method %s", method)
            if msg_id is None:
                return None
            return self._error(msg_id, INTERNAL_ERROR, f"{type(err).__name__}: {err}")

        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    async def _async_dispatch(
        self, method: str, params: dict[str, Any], session: Session, context: ToolContext
    ) -> Any:
        """Route a single method call."""
        match method:
            case "initialize":
                return self._initialize(params, session)
            case "notifications/initialized":
                session.initialized = True
                return None
            case "ping":
                return {}
            case "tools/list":
                return {"tools": [tool.as_mcp() for tool in self.available_tools(context)]}
            case "tools/call":
                return await self._call_tool(params, context)
            case "resources/list":
                return {"resources": resources_module.list_resources()}
            case "resources/templates/list":
                return {"resourceTemplates": resources_module.list_templates()}
            case "resources/read":
                return await resources_module.async_read(context, params.get("uri", ""))
            case "prompts/list":
                return {"prompts": prompts_module.list_prompts()}
            case "prompts/get":
                return await prompts_module.async_get(
                    context, params.get("name", ""), params.get("arguments") or {}
                )
            case "logging/setLevel":
                return {}
            case "completion/complete":
                return {"completion": {"values": [], "hasMore": False}}
            case _ if method.startswith("notifications/"):
                return None
        raise JSONRPCError(METHOD_NOT_FOUND, f"Unknown method: {method}")

    # Lifecycle ---------------------------------------------------------------
    def _initialize(self, params: dict[str, Any], session: Session) -> dict[str, Any]:
        """Negotiate the protocol version and advertise capabilities."""
        requested = params.get("protocolVersion") or LATEST_PROTOCOL_VERSION
        session.protocol_version = (
            requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        )
        session.client_info = params.get("clientInfo") or {}
        _LOGGER.debug(
            "MCP client %s initialized (protocol %s)",
            session.client_info.get("name", "unknown"),
            session.protocol_version,
        )
        return {
            "protocolVersion": session.protocol_version,
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
                "logging": {},
            },
            "serverInfo": {
                "name": "home-assistant-mcp-bridge",
                "title": f"{NAME} for Home Assistant",
                "version": SERVER_VERSION,
            },
            "instructions": INSTRUCTIONS,
        }

    # Tools -------------------------------------------------------------------
    def available_tools(self, context: ToolContext) -> list[ToolDef]:
        """Every tool the current configuration and user allow."""
        return self.runtime.available_tools(context.user)

    async def _call_tool(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        """Execute a tool call."""
        name = params.get("name")
        if not name:
            raise JSONRPCError(INVALID_PARAMS, "Missing tool name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise JSONRPCError(INVALID_PARAMS, "arguments must be an object")

        try:
            tool = self.runtime.get_tool(name, context.user)
        except (ToolNotFound, ToolDisabled) as err:
            raise JSONRPCError(INVALID_PARAMS, str(err)) from err

        _LOGGER.debug("Calling tool %s with %s", name, arguments)
        try:
            result = await tool.handler(context, arguments)
        except MCPBridgeError as err:
            return self._tool_error(str(err))
        except vol.Invalid as err:
            return self._tool_error(f"Invalid input: {err}")
        except Exception as err:  # noqa: BLE001 - surface it to the model, don't crash
            _LOGGER.exception("Tool %s failed", name)
            return self._tool_error(f"{type(err).__name__}: {err}")

        return self._tool_result(result)

    @staticmethod
    def _tool_result(result: Any) -> dict[str, Any]:
        """Convert a tool's return value into MCP content blocks."""
        if isinstance(result, (ImageResult, TextResult, MultiResult)):
            payload: dict[str, Any] = {"content": result.as_content(), "isError": False}
            if isinstance(result, TextResult) and result.structured is not None:
                payload["structuredContent"] = result.structured
            return payload

        if result is None:
            return {"content": [{"type": "text", "text": "OK"}], "isError": False}

        if isinstance(result, str):
            return {"content": [{"type": "text", "text": result}], "isError": False}

        text = json.dumps(result, indent=2, default=str, ensure_ascii=False)
        payload = {"content": [{"type": "text", "text": text}], "isError": False}
        if isinstance(result, dict):
            payload["structuredContent"] = result
        return payload

    @staticmethod
    def _tool_error(message: str) -> dict[str, Any]:
        """A failed tool call. Reported in-band so the model can react to it."""
        return {"content": [{"type": "text", "text": f"Error: {message}"}], "isError": True}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        """A JSON-RPC error response."""
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": msg_id, "error": error}
