"""MCP session bookkeeping."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from ..const import LATEST_PROTOCOL_VERSION, SESSION_IDLE_TIMEOUT


@dataclass(slots=True)
class Session:
    """One client connection, shared by the streamable HTTP and legacy SSE transports."""

    session_id: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    token_id: str | None = None
    protocol_version: str = LATEST_PROTOCOL_VERSION
    client_info: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    initialized: bool = False
    #: Outbound queue, only used by the legacy HTTP+SSE transport.
    queue: asyncio.Queue[Any] | None = None

    @property
    def expired(self) -> bool:
        """Whether the session has been idle for too long."""
        return time.time() - self.last_seen > SESSION_IDLE_TIMEOUT

    def touch(self) -> None:
        """Mark the session as active."""
        self.last_seen = time.time()


class SessionManager:
    """Tracks live sessions."""

    def __init__(self) -> None:
        """Initialise."""
        self._sessions: dict[str, Session] = {}

    def create(self, **kwargs: Any) -> Session:
        """Start a new session."""
        self.purge()
        session = Session(**kwargs)
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str | None) -> Session | None:
        """Look up a session."""
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expired:
            del self._sessions[session_id]
            return None
        session.touch()
        return session

    def remove(self, session_id: str) -> bool:
        """End a session."""
        return self._sessions.pop(session_id, None) is not None

    def purge(self) -> None:
        """Drop idle sessions."""
        for session_id, session in list(self._sessions.items()):
            if session.expired:
                del self._sessions[session_id]

    def revoke_token(self, token_id: str) -> None:
        """End every session belonging to a revoked token."""
        for session_id, session in list(self._sessions.items()):
            if session.token_id == token_id:
                del self._sessions[session_id]

    def __len__(self) -> int:
        """Number of live sessions."""
        return len(self._sessions)
