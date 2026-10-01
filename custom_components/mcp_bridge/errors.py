"""Errors raised by MCP Bridge tools."""

from __future__ import annotations


class MCPBridgeError(Exception):
    """Base error. The message is returned to the MCP client as a tool error."""


class ToolNotFound(MCPBridgeError):
    """The requested tool does not exist."""


class ToolDisabled(MCPBridgeError):
    """The requested tool exists but is disabled by configuration."""


class NotExposed(MCPBridgeError):
    """The target entity is not exposed to MCP clients."""


class InvalidInput(MCPBridgeError):
    """The tool arguments were invalid."""


class NotAllowed(MCPBridgeError):
    """The authenticated user may not perform this action."""
