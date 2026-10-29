"""Invoke Home Assistant WebSocket API commands in-process.

Most of what the Home Assistant frontend can do is a WebSocket command, so
driving that API directly gives MCP clients the same reach as the UI — including
the registry, config entry flows, traces and statistics — without reimplementing
any of it. Commands run through a real `ActiveConnection` bound to the
authenticated user and refresh token, so Home Assistant's own permission
decorators (`@require_admin` and friends) still apply.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
from typing import Any

from homeassistant.auth.models import RefreshToken, User
from homeassistant.components.websocket_api import DOMAIN as WS_DOMAIN
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.core import HomeAssistant

from .errors import MCPBridgeError

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


class WebSocketCommandError(MCPBridgeError):
    """A WebSocket command returned an error."""

    def __init__(self, code: str | None, message: str | None) -> None:
        """Initialise."""
        self.code = code or "unknown_error"
        super().__init__(f"{self.code}: {message or 'no message'}")


def _decode(message: Any) -> Any:
    """Normalise whatever a handler passed to `send_message` into plain JSON."""
    if isinstance(message, (bytes, bytearray)):
        return json.loads(message)
    if isinstance(message, str):
        return json.loads(message)
    if callable(message):
        # Some handlers send a lazily-rendered message factory.
        return _decode(message())
    return message


class WebSocketInvoker:
    """Runs WebSocket API commands as a given user."""

    def __init__(
        self, hass: HomeAssistant, user: User, refresh_token: RefreshToken
    ) -> None:
        """Initialise."""
        self.hass = hass
        self.user = user
        self.refresh_token = refresh_token

    @property
    def available_commands(self) -> list[str]:
        """Every registered WebSocket command type."""
        return sorted(self.hass.data.get(WS_DOMAIN, {}))

    async def call(
        self,
        command: str,
        payload: dict[str, Any] | None = None,
        *,
        wait_events: int = 0,
        event_timeout: float = 5.0,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Any:
        """Run `command` and return its result.

        When `wait_events` is set, events pushed by a subscription command are
        collected too and returned as `{"result": ..., "events": [...]}`. The
        subscription is always torn down before returning.
        """
        if command not in self.hass.data.get(WS_DOMAIN, {}):
            raise MCPBridgeError(
                f"Unknown WebSocket command {command!r}. "
                "Use list_websocket_commands to see what this instance supports."
            )

        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Any] = loop.create_future()
        events: list[Any] = []
        events_done: asyncio.Future[None] | None = (
            loop.create_future() if wait_events > 0 else None
        )
        msg_id = 1

        def _send(message: Any) -> None:
            try:
                data = _decode(message)
            except (ValueError, TypeError):  # pragma: no cover - defensive
                _LOGGER.debug("Could not decode websocket message: %r", message)
                return
            if not isinstance(data, dict) or data.get("id") != msg_id:
                return
            match data.get("type"):
                case "result":
                    if result_future.done():
                        return
                    if data.get("success"):
                        result_future.set_result(data.get("result"))
                    else:
                        error = data.get("error") or {}
                        result_future.set_exception(
                            WebSocketCommandError(
                                error.get("code"), error.get("message")
                            )
                        )
                case "event":
                    events.append(data.get("event"))
                    if (
                        events_done is not None
                        and not events_done.done()
                        and len(events) >= wait_events
                    ):
                        events_done.set_result(None)
                case "pong":
                    if not result_future.done():
                        result_future.set_result({"pong": True})

        connection = self._build_connection(_send)
        message = {"id": msg_id, "type": command, **(payload or {})}
        try:
            connection.async_handle(message)
            try:
                result = await asyncio.wait_for(result_future, timeout)
            except TimeoutError as err:
                raise MCPBridgeError(
                    f"WebSocket command {command!r} timed out after {timeout:g}s"
                ) from err

            if events_done is not None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(events_done, event_timeout)
                return {"result": result, "events": events}
            return result
        finally:
            await self._teardown(connection)

    def _build_connection(self, send_message: Any) -> ActiveConnection:
        """Construct an ActiveConnection, tolerating signature changes.

        Home Assistant 2025.7 added a `remote` argument for logging the caller's
        address; older releases do not accept it.
        """
        args: list[Any] = [
            _LOGGER,
            self.hass,
            send_message,
            self.user,
            self.refresh_token,
        ]
        if ActiveConnection.__init__.__code__.co_argcount > len(args) + 1:
            args.append("mcp_domora")
        return ActiveConnection(*args)

    @staticmethod
    async def _teardown(connection: ActiveConnection) -> None:
        """Cancel any subscription the command left behind."""
        for unsub in list(connection.subscriptions.values()):
            try:
                outcome = unsub()
                if inspect.isawaitable(outcome):
                    await outcome
            except Exception:  # noqa: BLE001 - teardown must not mask the result
                _LOGGER.debug("Error unsubscribing websocket command", exc_info=True)
        connection.subscriptions.clear()
