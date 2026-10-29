"""OAuth 2.1 / IndieAuth HTTP endpoints.

MCP clients speak OAuth 2.1: they discover metadata, register dynamically, run an
authorization code flow with PKCE and refresh their tokens. User authentication
itself is delegated to Home Assistant's own login page, so passwords, MFA and
trusted networks keep working untouched and this integration never sees a
credential. The Home Assistant leg is IndieAuth, the same flow the frontend uses.
"""

from __future__ import annotations

import html
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlparse

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    AS_METADATA_ALT_PATHS,
    AS_METADATA_PATH,
    AUTHORIZE_PATH,
    CALLBACK_PATH,
    CLIENT_DOC_PATH,
    DEFAULT_SCOPES,
    DOMAIN,
    MCP_PATH,
    NAME,
    ISSUER_PATH,
    PR_METADATA_ALT_PATHS,
    PR_METADATA_PATH,
    REGISTER_PATH,
    REVOKE_PATH,
    TOKEN_PATH,
)
from ..http_utils import base_url, html_response, json_response, oauth_error, page
from .indieauth import InvalidClient, async_resolve_client
from .store import AuthCode, AuthStore, OAuthClient, PendingAuthorization, random_token, verify_pkce

_LOGGER = logging.getLogger(__name__)

#: Consent forms expire quickly; they only need to survive one page view.
CONSENT_TTL = 600

SCOPE_DESCRIPTIONS = {
    "homeassistant:read": "Read your entities, their states and your history",
    "homeassistant:write": "Control devices and create or edit automations, scripts and scenes",
    "homeassistant:admin": "Change system configuration, integrations and add-ons",
}


def _runtime(request: web.Request) -> Any:
    """The integration runtime, or None when the entry is unloaded."""
    return request.app["hass"].data.get(DOMAIN)


def _store(request: web.Request) -> AuthStore:
    """The auth store."""
    return _runtime(request).store


class _BaseView(HomeAssistantView):
    """Common bits for the unauthenticated OAuth endpoints.

    `cors_allowed` makes Home Assistant attach its CORS preflight handler, which is
    why these views must not define an `options` method of their own.
    """

    requires_auth = False
    cors_allowed = True


class AuthorizationServerMetadataView(_BaseView):
    """RFC 8414 authorization server metadata."""

    url = AS_METADATA_PATH
    name = f"{DOMAIN}:oauth-as-metadata"
    extra_urls = list(AS_METADATA_ALT_PATHS)

    async def get(self, request: web.Request) -> web.Response:
        """Serve the metadata document."""
        base = base_url(request.app["hass"], request)
        return json_response(
            {
                "issuer": f"{base}{ISSUER_PATH}",
                "authorization_endpoint": f"{base}{AUTHORIZE_PATH}",
                "token_endpoint": f"{base}{TOKEN_PATH}",
                "registration_endpoint": f"{base}{REGISTER_PATH}",
                "revocation_endpoint": f"{base}{REVOKE_PATH}",
                "response_types_supported": ["code"],
                "response_modes_supported": ["query"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "revocation_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": list(DEFAULT_SCOPES),
                "service_documentation": "https://github.com/daMustermann/mcp-domora-home-assistant",
            }
        )


class ProtectedResourceMetadataView(_BaseView):
    """RFC 9728 protected resource metadata, as required by the MCP auth spec."""

    url = PR_METADATA_PATH
    name = f"{DOMAIN}:oauth-pr-metadata"
    extra_urls = list(PR_METADATA_ALT_PATHS)

    async def get(self, request: web.Request) -> web.Response:
        """Serve the metadata document."""
        base = base_url(request.app["hass"], request)
        return json_response(
            {
                "resource": f"{base}{MCP_PATH}",
                "authorization_servers": [f"{base}{ISSUER_PATH}"],
                "scopes_supported": list(DEFAULT_SCOPES),
                "bearer_methods_supported": ["header"],
                "resource_name": f"{NAME} for Home Assistant",
            }
        )


class ClientDocumentView(_BaseView):
    """IndieAuth client identifier documents for dynamically registered clients."""

    url = f"{CLIENT_DOC_PATH}/{{client_ref}}"
    name = f"{DOMAIN}:oauth-client-doc"

    async def get(self, request: web.Request, client_ref: str) -> web.Response:
        """Serve the client document."""
        runtime = _runtime(request)
        if runtime is None:
            return html_response(page("Unavailable", "<h1>MCP Domora is not loaded</h1>"), 503)
        base = base_url(request.app["hass"], request)
        client = runtime.store.get_client(f"{base}{CLIENT_DOC_PATH}/{client_ref}")
        if client is None:
            return html_response(page("Unknown client", "<h1>Unknown client</h1>"), 404)
        links = "\n".join(
            f'<link rel="redirect_uri" href="{html.escape(uri)}">'
            for uri in client.redirect_uris
        )
        name = html.escape(client.client_name)
        return html_response(
            f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{name}</title>
{links}
</head><body><h1>{name}</h1>
<p>MCP client registered with Home Assistant.</p></body></html>"""
        )


class RegistrationView(_BaseView):
    """RFC 7591 dynamic client registration."""

    url = REGISTER_PATH
    name = f"{DOMAIN}:oauth-register"

    async def post(self, request: web.Request) -> web.Response:
        """Register a new public client."""
        runtime = _runtime(request)
        if runtime is None:
            return oauth_error("temporarily_unavailable", "MCP Domora is not loaded", 503)
        try:
            body = await request.json()
        except ValueError:
            return oauth_error("invalid_client_metadata", "Body must be JSON")

        redirect_uris = body.get("redirect_uris") or []
        if not isinstance(redirect_uris, list) or not all(
            isinstance(uri, str) for uri in redirect_uris
        ):
            return oauth_error(
                "invalid_redirect_uri", "redirect_uris must be a list of strings"
            )
        if not redirect_uris:
            return oauth_error("invalid_redirect_uri", "At least one redirect_uri is required")

        method = body.get("token_endpoint_auth_method", "none")
        if method != "none":
            return oauth_error(
                "invalid_client_metadata",
                "Only public clients are supported; use token_endpoint_auth_method=none with PKCE",
            )

        base = base_url(request.app["hass"], request)
        client_ref = secrets.token_urlsafe(16)
        client = OAuthClient(
            client_id=f"{base}{CLIENT_DOC_PATH}/{client_ref}",
            client_name=str(body.get("client_name") or "MCP client")[:128],
            redirect_uris=redirect_uris,
            dynamic=True,
            client_uri=body.get("client_uri"),
            logo_uri=body.get("logo_uri"),
            scope=body.get("scope") or " ".join(DEFAULT_SCOPES),
        )
        await runtime.store.async_add_client(client)
        _LOGGER.info("Registered MCP client %s (%s)", client.client_name, client.client_id)
        return json_response(client.as_registration_response(), status=201)


class AuthorizeView(_BaseView):
    """The authorization endpoint: asks for consent, then hands off to Home Assistant."""

    url = AUTHORIZE_PATH
    name = f"{DOMAIN}:oauth-authorize"

    async def get(self, request: web.Request) -> web.Response:
        """Validate the request and render the consent page."""
        hass: HomeAssistant = request.app["hass"]
        runtime = _runtime(request)
        if runtime is None:
            return html_response(page("Unavailable", "<h1>MCP Domora is not loaded</h1>"), 503)

        query = request.query
        if query.get("response_type") != "code":
            return oauth_error("unsupported_response_type", "response_type must be 'code'")
        challenge = query.get("code_challenge")
        if not challenge:
            return oauth_error("invalid_request", "PKCE is required: provide code_challenge")
        if query.get("code_challenge_method", "plain") != "S256":
            return oauth_error(
                "invalid_request", "code_challenge_method must be S256"
            )

        try:
            client = await async_resolve_client(
                hass,
                runtime.store,
                query.get("client_id", ""),
                query.get("redirect_uri", ""),
            )
        except InvalidClient as err:
            return html_response(
                page(
                    "Authorization failed",
                    f"<h1>Authorization failed</h1><p class='error'>{html.escape(str(err))}</p>",
                ),
                400,
            )

        scopes = (query.get("scope") or " ".join(DEFAULT_SCOPES)).split()
        scopes = [scope for scope in scopes if scope in DEFAULT_SCOPES] or list(DEFAULT_SCOPES)

        consent_key = random_token(24)
        runtime.consents[consent_key] = {
            "created_at": time.time(),
            "client_id": client.client_id,
            "client_name": client.client_name,
            "redirect_uri": query["redirect_uri"],
            "state": query.get("state"),
            "code_challenge": challenge,
            "scopes": scopes,
            "resource": query.get("resource"),
        }
        return html_response(self._consent_page(client, query, scopes, consent_key))

    @staticmethod
    def _consent_page(
        client: OAuthClient, query: Any, scopes: list[str], consent_key: str
    ) -> str:
        """Render the consent form."""
        scope_items = "\n".join(
            f"<li>{html.escape(SCOPE_DESCRIPTIONS.get(scope, scope))}</li>" for scope in scopes
        )
        host = html.escape(urlparse(query.get("redirect_uri", "")).netloc or "unknown")
        body = f"""
<h1>Connect to Home Assistant</h1>
<p class="muted">An MCP client is asking for access to this Home Assistant instance.</p>
<dl>
  <dt>Client</dt><dd>{html.escape(client.client_name)}</dd>
  <dt>Redirects to</dt><dd>{host}</dd>
</dl>
<p>If you continue it will be able to:</p>
<ul>{scope_items}</ul>
<p class="muted">You will be asked to sign in to Home Assistant next. The client only
receives access to what your own user account may do.</p>
<form method="post" action="{AUTHORIZE_PATH}">
  <input type="hidden" name="consent" value="{html.escape(consent_key)}">
  <div class="actions">
    <button type="submit" name="action" value="deny" class="secondary">Cancel</button>
    <button type="submit" name="action" value="allow" class="primary">Continue</button>
  </div>
</form>"""
        return page("Connect to Home Assistant", body)

    async def post(self, request: web.Request) -> web.Response:
        """Handle the consent decision and redirect into Home Assistant's login."""
        hass: HomeAssistant = request.app["hass"]
        runtime = _runtime(request)
        if runtime is None:
            return oauth_error("temporarily_unavailable", "MCP Domora is not loaded", 503)

        form = await request.post()
        consent = runtime.consents.pop(str(form.get("consent", "")), None)
        if consent is None or time.time() - consent["created_at"] > CONSENT_TTL:
            return html_response(
                page(
                    "Session expired",
                    "<h1>Session expired</h1><p>Start the connection again from your MCP client.</p>",
                ),
                400,
            )

        if form.get("action") != "allow":
            return web.HTTPFound(
                _redirect_with(
                    consent["redirect_uri"],
                    {"error": "access_denied", "state": consent["state"]},
                )
            )

        state_key = random_token(24)
        runtime.store.pending[state_key] = PendingAuthorization(
            state_key=state_key,
            client_id=consent["client_id"],
            client_name=consent["client_name"],
            redirect_uri=consent["redirect_uri"],
            client_state=consent["state"],
            code_challenge=consent["code_challenge"],
            scopes=consent["scopes"],
            resource=consent["resource"],
        )

        base = base_url(hass, request)
        # Home Assistant verifies this client_id with IndieAuth: the callback is on
        # the same origin, so the same-host rule applies and no fetch is needed.
        ha_authorize = f"{base}/auth/authorize?" + urlencode(
            {
                "response_type": "code",
                "client_id": f"{base}/",
                "redirect_uri": f"{base}{CALLBACK_PATH}",
                "state": state_key,
            }
        )
        return web.HTTPFound(ha_authorize)


class CallbackView(_BaseView):
    """Receives the Home Assistant authorization code and resolves the user."""

    url = CALLBACK_PATH
    name = f"{DOMAIN}:oauth-callback"

    async def get(self, request: web.Request) -> web.Response:
        """Exchange the Home Assistant code and redirect back to the MCP client."""
        hass: HomeAssistant = request.app["hass"]
        runtime = _runtime(request)
        if runtime is None:
            return html_response(page("Unavailable", "<h1>MCP Domora is not loaded</h1>"), 503)

        pending = runtime.store.pending.pop(request.query.get("state", ""), None)
        if pending is None or pending.expired:
            return html_response(
                page(
                    "Sign-in expired",
                    "<h1>Sign-in expired</h1><p>Start the connection again from your MCP client.</p>",
                ),
                400,
            )

        if error := request.query.get("error"):
            return web.HTTPFound(
                _redirect_with(
                    pending.redirect_uri,
                    {"error": error, "state": pending.client_state},
                )
            )

        ha_code = request.query.get("code")
        if not ha_code:
            return web.HTTPFound(
                _redirect_with(
                    pending.redirect_uri,
                    {"error": "invalid_request", "state": pending.client_state},
                )
            )

        try:
            refresh_token = await _exchange_ha_code(hass, request, ha_code)
        except HomeAssistantExchangeError as err:
            _LOGGER.error("Could not exchange Home Assistant auth code: %s", err)
            return html_response(
                page(
                    "Sign-in failed",
                    f"<h1>Sign-in failed</h1><p class='error'>{html.escape(str(err))}</p>",
                ),
                502,
            )

        code = random_token(32)
        runtime.store.codes[code] = AuthCode(
            code=code,
            client_id=pending.client_id,
            redirect_uri=pending.redirect_uri,
            code_challenge=pending.code_challenge,
            scopes=pending.scopes,
            user_id=refresh_token.user.id,
            ha_refresh_token_id=refresh_token.id,
            resource=pending.resource,
        )
        _LOGGER.info(
            "Authorized MCP client %s for user %s",
            pending.client_name,
            refresh_token.user.name,
        )
        return web.HTTPFound(
            _redirect_with(
                pending.redirect_uri, {"code": code, "state": pending.client_state}
            )
        )


class TokenView(_BaseView):
    """The token endpoint."""

    url = TOKEN_PATH
    name = f"{DOMAIN}:oauth-token"

    async def post(self, request: web.Request) -> web.Response:
        """Issue tokens for an authorization code or a refresh token."""
        runtime = _runtime(request)
        if runtime is None:
            return oauth_error("temporarily_unavailable", "MCP Domora is not loaded", 503)
        store = runtime.store
        form = await request.post()
        grant_type = form.get("grant_type")

        if grant_type == "authorization_code":
            return await self._authorization_code(request, store, form)
        if grant_type == "refresh_token":
            return await self._refresh_token(request, store, form)
        return oauth_error(
            "unsupported_grant_type",
            "grant_type must be 'authorization_code' or 'refresh_token'",
        )

    async def _authorization_code(
        self, request: web.Request, store: AuthStore, form: Any
    ) -> web.Response:
        """Redeem an authorization code."""
        code = str(form.get("code", ""))
        record = store.codes.pop(code, None)
        if record is None:
            return oauth_error("invalid_grant", "Unknown or already used authorization code")
        if record.expired:
            return oauth_error("invalid_grant", "Authorization code has expired")
        if str(form.get("client_id", "")) != record.client_id:
            return oauth_error("invalid_grant", "client_id does not match the authorization code")
        if str(form.get("redirect_uri", "")) != record.redirect_uri:
            return oauth_error("invalid_grant", "redirect_uri does not match the authorization code")

        verifier = str(form.get("code_verifier", ""))
        if not verifier or not verify_pkce(verifier, record.code_challenge):
            return oauth_error("invalid_grant", "PKCE verification failed")

        client = store.get_client(record.client_id)
        if client is None:
            return oauth_error("invalid_client", "Client is no longer registered")

        ha_token = request.app["hass"].auth.async_get_refresh_token(
            record.ha_refresh_token_id
        )
        if ha_token is None:
            return oauth_error("invalid_grant", "The Home Assistant session was revoked")

        access_token, refresh_token, issued = await store.async_issue_tokens(
            client=client,
            user_id=record.user_id,
            ha_refresh_token_id=record.ha_refresh_token_id,
            scopes=record.scopes,
        )
        return json_response(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": int(issued.expires_at - time.time()),
                "refresh_token": refresh_token,
                "scope": " ".join(issued.scopes),
            },
            headers={"Cache-Control": "no-store"},
        )

    async def _refresh_token(
        self, request: web.Request, store: AuthStore, form: Any
    ) -> web.Response:
        """Rotate a refresh token."""
        record = store.resolve_refresh_token(str(form.get("refresh_token", "")))
        if record is None:
            return oauth_error("invalid_grant", "Unknown refresh token")
        if record.refresh_expired:
            await store.async_revoke(record.token_id, revoke_ha=False)
            return oauth_error("invalid_grant", "Refresh token has expired")
        if (client_id := form.get("client_id")) and str(client_id) != record.client_id:
            return oauth_error("invalid_grant", "client_id does not match the refresh token")
        if request.app["hass"].auth.async_get_refresh_token(record.ha_refresh_token_id) is None:
            await store.async_revoke(record.token_id, revoke_ha=False)
            return oauth_error("invalid_grant", "The Home Assistant session was revoked")

        access_token, refresh_token = await store.async_rotate(record)
        return json_response(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": int(record.expires_at - time.time()),
                "refresh_token": refresh_token,
                "scope": " ".join(record.scopes),
            },
            headers={"Cache-Control": "no-store"},
        )


class RevokeView(_BaseView):
    """RFC 7009 token revocation."""

    url = REVOKE_PATH
    name = f"{DOMAIN}:oauth-revoke"

    async def post(self, request: web.Request) -> web.Response:
        """Revoke a token. Always reports success, as the RFC requires."""
        runtime = _runtime(request)
        if runtime is None:
            return oauth_error("temporarily_unavailable", "MCP Domora is not loaded", 503)
        store = runtime.store
        token = str((await request.post()).get("token", ""))
        record = store.resolve_access_token(token) or store.resolve_refresh_token(token)
        if record is not None:
            await store.async_revoke(record.token_id)
            _LOGGER.info("Revoked MCP token for client %s", record.client_name)
        return web.Response(status=200, headers={"Access-Control-Allow-Origin": "*"})


class HomeAssistantExchangeError(Exception):
    """The Home Assistant token exchange failed."""


def _token_endpoints(hass: HomeAssistant, request: web.Request) -> list[tuple[str, bool]]:
    """Candidate Home Assistant token endpoints, as (url, verify_ssl) pairs.

    Loopback is tried first when Home Assistant serves plain HTTP, since it never
    leaves the machine. Otherwise the origin the browser just used is the best bet.
    """
    port = getattr(hass.http, "server_port", 8123)
    uses_ssl = bool(getattr(hass.http, "ssl_certificate", None))
    loopback = (f"http{'s' if uses_ssl else ''}://127.0.0.1:{port}/auth/token", False)
    origin = (f"{base_url(hass, request)}/auth/token", True)
    candidates = [origin, loopback] if uses_ssl else [loopback, origin]
    return list(dict.fromkeys(candidates))


async def _exchange_ha_code(hass: HomeAssistant, request: web.Request, code: str) -> Any:
    """Trade a Home Assistant authorization code for a refresh token object."""
    base = base_url(hass, request)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": f"{base}/",
    }
    errors: list[str] = []
    for url, verify_ssl in _token_endpoints(hass, request):
        session = async_get_clientsession(hass, verify_ssl=verify_ssl)
        try:
            async with session.post(url, data=payload, timeout=30) as response:
                body = await response.json(content_type=None)
                if response.status != 200:
                    errors.append(
                        f"{url} -> {response.status} {body.get('error') if isinstance(body, dict) else body}"
                    )
                    continue
        except Exception as err:  # noqa: BLE001 - try the next candidate
            errors.append(f"{url} -> {type(err).__name__}: {err}")
            continue

        access_token = body.get("access_token")
        if not access_token:
            errors.append(f"{url} -> response contained no access_token")
            continue
        refresh_token = hass.auth.async_validate_access_token(access_token)
        if refresh_token is None:
            errors.append(f"{url} -> issued token did not validate")
            continue
        return refresh_token

    raise HomeAssistantExchangeError(
        "Could not reach the Home Assistant token endpoint. Tried: " + "; ".join(errors)
    )


def _redirect_with(redirect_uri: str, params: dict[str, Any]) -> str:
    """Append query parameters to a redirect URI."""
    clean = {key: value for key, value in params.items() if value is not None}
    separator = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{separator}{urlencode(clean)}"


ALL_VIEWS = (
    AuthorizationServerMetadataView,
    ProtectedResourceMetadataView,
    ClientDocumentView,
    RegistrationView,
    AuthorizeView,
    CallbackView,
    TokenView,
    RevokeView,
)
