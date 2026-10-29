"""IndieAuth client identification.

An MCP client identifies itself either by registering dynamically (RFC 7591) or,
IndieAuth style, by using a URL as its `client_id` that publishes its redirect
URIs. Home Assistant already ships an IndieAuth implementation for its own login
flow and this reuses it, so a client that works with Home Assistant works here.
"""

from __future__ import annotations

import logging
from ipaddress import ip_address
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant

from ..errors import MCPBridgeError
from .store import AuthStore, OAuthClient

_LOGGER = logging.getLogger(__name__)

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


class InvalidClient(MCPBridgeError):
    """The client_id or redirect_uri could not be validated."""


def is_loopback(url: str) -> bool:
    """Whether a redirect URI points at the client's own machine."""
    host = (urlparse(url).hostname or "").strip("[]")
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _normalise_loopback(url: str) -> str:
    """Drop the port from a loopback URI.

    Native MCP clients bind an ephemeral port per run (RFC 8252 section 7.3), so
    the port registered at sign-up is not the port used next time.
    """
    parsed = urlparse(url)
    return parsed._replace(netloc=parsed.hostname or "").geturl()


def redirect_uri_matches(registered: list[str], requested: str) -> bool:
    """Compare a requested redirect URI against the registered set."""
    if requested in registered:
        return True
    if is_loopback(requested):
        target = _normalise_loopback(requested)
        return any(
            is_loopback(candidate) and _normalise_loopback(candidate) == target
            for candidate in registered
        )
    return False


def is_url_client_id(client_id: str) -> bool:
    """Whether `client_id` looks like an IndieAuth client identifier."""
    parsed = urlparse(client_id)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


async def _verify_indieauth(
    hass: HomeAssistant, client_id: str, redirect_uri: str
) -> bool:
    """Verify a redirect URI against a client_id document."""
    try:
        from homeassistant.components.auth import indieauth  # noqa: PLC0415
    except ImportError:  # pragma: no cover - `auth` is a hard dependency
        return False
    try:
        return await indieauth.verify_redirect_uri(hass, client_id, redirect_uri)
    except Exception:  # noqa: BLE001 - network/parse failures are just "no"
        _LOGGER.debug("IndieAuth verification failed for %s", client_id, exc_info=True)
        return False


async def async_resolve_client(
    hass: HomeAssistant,
    store: AuthStore,
    client_id: str,
    redirect_uri: str,
) -> OAuthClient:
    """Resolve the client behind an authorization request.

    Registered clients are matched against their stored redirect URIs. Unknown
    clients are accepted when their `client_id` is a URL that advertises the
    requested redirect URI, which is the IndieAuth discovery flow.
    """
    if not client_id:
        raise InvalidClient("Missing client_id")
    if not redirect_uri:
        raise InvalidClient("Missing redirect_uri")

    client = store.get_client(client_id)
    if client is not None:
        if not redirect_uri_matches(client.redirect_uris, redirect_uri):
            raise InvalidClient(
                f"redirect_uri {redirect_uri!r} is not registered for this client. "
                f"Registered: {', '.join(client.redirect_uris) or '(none)'}"
            )
        return client

    if not is_url_client_id(client_id):
        raise InvalidClient(
            f"Unknown client_id {client_id!r}. Either register at the registration "
            "endpoint, or use an https URL as client_id that publishes a "
            '<link rel="redirect_uri"> for IndieAuth discovery.'
        )

    if not await _verify_indieauth(hass, client_id, redirect_uri):
        raise InvalidClient(
            f"{client_id} does not advertise {redirect_uri} as a redirect_uri. "
            "Publish it as <link rel=\"redirect_uri\" href=\"...\"> on that page, "
            "or use a redirect_uri on the same host as the client_id."
        )

    # Remember the discovered client so subsequent requests skip the fetch.
    return await store.async_add_client(
        OAuthClient(
            client_id=client_id,
            client_name=urlparse(client_id).hostname or client_id,
            redirect_uris=[redirect_uri],
            dynamic=False,
        )
    )
