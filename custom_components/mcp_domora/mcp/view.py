"""MCP transports.

Two transports are served:

* Streamable HTTP (`/mcp_domora/mcp`), the current MCP transport. POSTs carry
  JSON-RPC and get a JSON response; GET opens an optional server-to-client SSE
  stream; DELETE ends the session.
* HTTP+SSE (`/mcp_domora/sse` plus `/mcp_domora/messages/...`), the 2024-11-05
  transport, still spoken by a number of clients and proxies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import (
    DOMAIN,
    MCP_PATH,
    MESSAGES_PATH,
    PR_METADATA_PATH,
    SESSION_HEADER,
    SSE_PATH,
)
from ..http_utils import base_url, json_response
from .protocol import INVALID_REQUEST, PARSE_ERROR, JSONRPCError
from .session import Session

_LOGGER = logging.getLogger(__name__)

SSE_KEEPALIVE = 25


def _runtime(request: web.Request) -> Any:
    """The integration runtime, or None when the entry is unloaded."""
    return request.app["hass"].data.get(DOMAIN)


def _session_id(request: web.Request) -> str | None:
    """The session id from the header, or from the query string.

    Home Assistant's CORS policy does not allow the `Mcp-Session-Id` request
    header, so browser-based clients pass it as `?session_id=` instead.
    """
    return request.headers.get(SESSION_HEADER) or request.query.get("session_id")


def _unauthorized(hass: HomeAssistant, request: web.Request, detail: str) -> web.Response:
    """A 401 that points the client at the protected resource metadata.

    The `resource_metadata` parameter is what lets an MCP client discover where to
    authenticate without being configured for it.
    """
    base = base_url(hass, request)
    challenge = (
        f'Bearer realm="Home Assistant", '
        f'resource_metadata="{base}{PR_METADATA_PATH}", '
        f'error="invalid_token", error_description="{detail}"'
    )
    return json_response(
        {"error": "invalid_token", "error_description": detail},
        status=401,
        headers={"WWW-Authenticate": challenge},
    )


class _MCPViewBase(HomeAssistantView):
    """Shared authentication for the MCP transports.

    Authentication is handled here rather than by Home Assistant's own decorator
    because MCP requires a 401 carrying a `WWW-Authenticate` challenge.
    """

    requires_auth = False
    #: Home Assistant attaches the CORS preflight handler for this, so these views
    #: must not define an `options` method themselves.
    cors_allowed = True

    async def _authenticate(
        self, request: web.Request
    ) -> tuple[Any, Any] | web.Response:
        """Resolve the bearer token to a (runtime, context) pair, or fail."""
        hass: HomeAssistant = request.app["hass"]
        runtime = _runtime(request)
        if runtime is None or not runtime.loaded:
            return json_response(
                {"error": "server_error", "error_description": "MCP Domora is not loaded"},
                status=503,
            )

        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return _unauthorized(hass, request, "A bearer token is required")
        token = header.removeprefix("Bearer ").strip()

        context, detail = await runtime.async_build_context(token)
        if context is None:
            return _unauthorized(hass, request, detail or "Invalid token")
        return runtime, context


class MCPView(_MCPViewBase):
    """Streamable HTTP transport."""

    url = MCP_PATH
    name = f"{DOMAIN}:mcp"

    async def post(self, request: web.Request) -> web.Response:
        """Handle a JSON-RPC request, notification or batch."""
        authenticated = await self._authenticate(request)
        if isinstance(authenticated, web.Response):
            return authenticated
        runtime, context = authenticated

        try:
            message = await request.json()
        except ValueError:
            return json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": PARSE_ERROR, "message": "Invalid JSON"},
                },
                status=400,
            )

        session, created = self._resolve_session(runtime, request, message, context)
        if session is None:
            return json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": INVALID_REQUEST,
                        "message": "Unknown or expired session; send `initialize` again",
                    },
                },
                status=404,
            )

        headers = {SESSION_HEADER: session.session_id}
        try:
            response = await runtime.server.async_handle(message, session, context)
        except JSONRPCError as err:
            return json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": err.code, "message": err.message},
                },
                status=400,
                headers=headers,
            )

        if response is None:
            # Notifications and responses get no body.
            return web.Response(status=202, headers=headers)
        return json_response(response, headers=headers)

    @staticmethod
    def _resolve_session(
        runtime: Any, request: web.Request, message: Any, context: Any
    ) -> tuple[Session | None, bool]:
        """Find or create the session for this request."""
        session_id = _session_id(request)
        methods = {
            item.get("method")
            for item in (message if isinstance(message, list) else [message])
            if isinstance(item, dict)
        }

        if "initialize" in methods:
            session = runtime.sessions.create(token_id=context.token_id)
            return session, True

        session = runtime.sessions.get(session_id)
        if session is not None:
            return session, False
        if session_id:
            # The client thinks it has a session but the server has forgotten it.
            return None, False
        # Clients that do not track the session header still get served.
        return runtime.sessions.create(token_id=context.token_id), True

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Open the optional server-to-client SSE stream.

        Nothing is pushed over it today; it is kept open with comments so clients
        that insist on opening it behave normally.
        """
        authenticated = await self._authenticate(request)
        if isinstance(authenticated, web.Response):
            return authenticated
        runtime, _context = authenticated

        session = runtime.sessions.get(_session_id(request))
        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)
        try:
            while True:
                await asyncio.sleep(SSE_KEEPALIVE)
                if session is not None:
                    session.touch()
                await response.write(b": keep-alive\n\n")
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        return response

    async def delete(self, request: web.Request) -> web.Response:
        """End a session."""
        authenticated = await self._authenticate(request)
        if isinstance(authenticated, web.Response):
            return authenticated
        runtime, _context = authenticated
        session_id = _session_id(request)
        if not session_id:
            return json_response({"error": "Missing session header"}, status=400)
        removed = runtime.sessions.remove(session_id)
        return web.Response(status=200 if removed else 404)


class LegacySSEView(_MCPViewBase):
    """The 2024-11-05 HTTP+SSE transport: an event stream plus a POST endpoint."""

    url = SSE_PATH
    name = f"{DOMAIN}:sse"

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Open the event stream and announce the message endpoint."""
        authenticated = await self._authenticate(request)
        if isinstance(authenticated, web.Response):
            return authenticated
        runtime, context = authenticated

        session = runtime.sessions.create(token_id=context.token_id)
        session.queue = asyncio.Queue()
        session.protocol_version = "2024-11-05"

        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)
        endpoint = f"{MESSAGES_PATH}/{session.session_id}"
        await response.write(f"event: endpoint\ndata: {endpoint}\n\n".encode())
        _LOGGER.debug("Legacy SSE session %s opened", session.session_id)

        try:
            while True:
                try:
                    message = await asyncio.wait_for(session.queue.get(), SSE_KEEPALIVE)
                except TimeoutError:
                    await response.write(b": keep-alive\n\n")
                    session.touch()
                    continue
                payload = json.dumps(message, default=str, ensure_ascii=False)
                await response.write(f"event: message\ndata: {payload}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            runtime.sessions.remove(session.session_id)
            _LOGGER.debug("Legacy SSE session %s closed", session.session_id)
        return response


class LegacyMessagesView(_MCPViewBase):
    """Receives JSON-RPC for a legacy SSE session; replies go out over the stream."""

    url = f"{MESSAGES_PATH}/{{session_id}}"
    name = f"{DOMAIN}:messages"

    async def post(self, request: web.Request, session_id: str) -> web.Response:
        """Queue a response for delivery over the client's event stream."""
        authenticated = await self._authenticate(request)
        if isinstance(authenticated, web.Response):
            return authenticated
        runtime, context = authenticated

        session = runtime.sessions.get(session_id)
        if session is None or session.queue is None:
            return json_response({"error": "Unknown session"}, status=404)

        try:
            message = await request.json()
        except ValueError:
            return json_response({"error": "Invalid JSON"}, status=400)

        try:
            response = await runtime.server.async_handle(message, session, context)
        except JSONRPCError as err:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": err.code, "message": err.message},
            }
        if response is not None:
            await session.queue.put(response)
        return web.Response(status=202)


ALL_VIEWS = (MCPView, LegacySSEView, LegacyMessagesView)
