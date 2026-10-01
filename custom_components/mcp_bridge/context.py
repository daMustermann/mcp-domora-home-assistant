"""Per-request context handed to every tool implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.auth.models import RefreshToken, User
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.core import Context, HomeAssistant

from .const import CONF_MAX_RESULTS, DEFAULT_MAX_RESULTS
from .errors import NotAllowed, NotExposed
from .exposure import Exposure
from .ws import WebSocketInvoker


@dataclass(slots=True)
class ToolContext:
    """Everything a tool needs to do its job."""

    hass: HomeAssistant
    user: User
    refresh_token: RefreshToken
    options: dict[str, Any]
    exposure: Exposure
    ws: WebSocketInvoker
    scopes: frozenset[str]
    #: The issued token this request came in on; None for Home Assistant tokens.
    token_id: str | None = None
    #: Flow id -> "config" | "options", so a flow can be resumed by the right manager.
    runtime_flows: dict[str, str] = field(default_factory=dict)

    @property
    def ha_context(self) -> Context:
        """A Home Assistant context attributing actions to the real user."""
        return Context(user_id=self.user.id)

    @property
    def max_results(self) -> int:
        """Cap on list-shaped responses."""
        return int(self.options.get(CONF_MAX_RESULTS, DEFAULT_MAX_RESULTS))

    def limit(self, items: list[Any], requested: int | None = None) -> list[Any]:
        """Truncate a result list to the configured maximum."""
        cap = min(requested or self.max_results, self.max_results)
        return items[:cap]

    # Permissions -------------------------------------------------------------
    def check_exposed(self, *entity_ids: str) -> None:
        """Raise unless every entity is exposed to MCP clients."""
        blocked = self.exposure.blocked([eid for eid in entity_ids if eid])
        if blocked:
            raise NotExposed(
                "Not exposed to MCP clients: "
                + ", ".join(sorted(blocked))
                + ". Adjust the entity filter in the MCP Bridge options to allow it."
            )

    def check_read(self, *entity_ids: str) -> None:
        """Raise unless the user may read every entity."""
        self.check_exposed(*entity_ids)
        if self.user.is_admin:
            return
        for entity_id in entity_ids:
            if not self.user.permissions.check_entity(entity_id, POLICY_READ):
                raise NotAllowed(f"User {self.user.name!r} may not read {entity_id}")

    def check_control(self, *entity_ids: str) -> None:
        """Raise unless the user may control every entity."""
        self.check_exposed(*entity_ids)
        if self.user.is_admin:
            return
        for entity_id in entity_ids:
            if not self.user.permissions.check_entity(entity_id, POLICY_CONTROL):
                raise NotAllowed(f"User {self.user.name!r} may not control {entity_id}")

    def check_admin(self) -> None:
        """Raise unless the user is a Home Assistant administrator."""
        if not self.user.is_admin:
            raise NotAllowed(
                f"User {self.user.name!r} is not an administrator; this tool needs admin rights."
            )
