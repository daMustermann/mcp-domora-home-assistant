"""Tool registry.

Tools register themselves with the :func:`tool` decorator at import time. The
options flow reads this registry to render the per-tool configuration UI, so a
new tool becomes configurable simply by existing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .errors import InvalidInput

if TYPE_CHECKING:
    from .context import ToolContext

ToolHandler = Callable[["ToolContext", dict[str, Any]], Awaitable[Any]]


@dataclass(slots=True)
class ToolDef:
    """A single MCP tool."""

    name: str
    group: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    title: str | None = None
    #: Mutates Home Assistant state or configuration.
    write: bool = False
    #: Requires an admin Home Assistant user.
    admin: bool = False
    #: Irreversible or disruptive; hidden unless `allow_dangerous` is enabled.
    dangerous: bool = False
    #: Performs updates that cannot be undone by calling the tool again.
    destructive: bool = False
    #: Calling it repeatedly with the same arguments has no additional effect.
    idempotent: bool = False
    #: Interacts with the world outside Home Assistant.
    open_world: bool = False
    #: Extra fields merged into the advertised tool definition.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def annotations(self) -> dict[str, Any]:
        """MCP tool annotations (hints for clients)."""
        return {
            "title": self.title or self.name.replace("_", " ").capitalize(),
            "readOnlyHint": not self.write,
            "destructiveHint": self.destructive,
            "idempotentHint": self.idempotent,
            "openWorldHint": self.open_world,
        }

    def as_mcp(self) -> dict[str, Any]:
        """Serialise for `tools/list`."""
        payload: dict[str, Any] = {
            "name": self.name,
            "title": self.title or self.name.replace("_", " ").capitalize(),
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": self.annotations,
        }
        payload.update(self.meta)
        return payload


TOOLS: dict[str, ToolDef] = {}


def tool(
    *,
    name: str,
    group: str,
    description: str,
    input_schema: dict[str, Any] | None = None,
    title: str | None = None,
    write: bool = False,
    admin: bool = False,
    dangerous: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = False,
    meta: dict[str, Any] | None = None,
) -> Callable[[ToolHandler], ToolHandler]:
    """Register a tool implementation."""

    def decorator(handler: ToolHandler) -> ToolHandler:
        if name in TOOLS:
            raise RuntimeError(f"Duplicate MCP tool name: {name}")
        TOOLS[name] = ToolDef(
            name=name,
            group=group,
            description=description.strip(),
            input_schema=input_schema or {"type": "object", "properties": {}},
            handler=handler,
            title=title,
            write=write,
            admin=admin,
            dangerous=dangerous,
            destructive=destructive,
            idempotent=idempotent,
            open_world=open_world,
            meta=meta or {},
        )
        return handler

    return decorator


def all_tools() -> dict[str, ToolDef]:
    """Every registered tool, with the tool modules imported."""
    from . import tools  # noqa: F401  pylint: disable=import-outside-toplevel,cyclic-import

    return TOOLS


def require(args: dict[str, Any], *names: str) -> tuple[Any, ...]:
    """Return the named arguments, raising if any are missing or empty."""
    values = []
    for name in names:
        value = args.get(name)
        if value is None or value == "":
            raise InvalidInput(f"Missing required argument: {name!r}")
        values.append(value)
    return tuple(values)


def one_of(args: dict[str, Any], *names: str) -> tuple[str, Any]:
    """Return the single provided argument out of `names`."""
    present = [n for n in names if args.get(n) not in (None, "")]
    if not present:
        raise InvalidInput(f"Provide one of: {', '.join(names)}")
    if len(present) > 1:
        raise InvalidInput(f"Provide only one of: {', '.join(present)}")
    return present[0], args[present[0]]
