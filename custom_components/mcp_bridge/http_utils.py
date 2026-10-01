"""Shared HTTP helpers for the MCP and OAuth endpoints."""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

# CORS is handled by Home Assistant: the views set `cors_allowed`, so the http
# integration attaches the preflight handler and the response headers. Adding them
# here as well would emit duplicates, which browsers reject.


def base_url(hass: HomeAssistant, request: web.Request) -> str:
    """The externally reachable origin of this Home Assistant instance.

    Always derived from the request, so every URL handed back - the issuer, the
    redirect target, the resource identifier - matches the host the client used to
    get here. Substituting a configured URL instead would break the OAuth flow for
    anyone reaching Home Assistant by a different name. Home Assistant's
    forwarded-header middleware has already corrected the scheme and host when it
    runs behind a proxy.

    The configured URL is only a fallback for the rare request that carries no
    usable origin.
    """
    try:
        origin = str(request.url.origin())
    except ValueError:
        origin = ""
    if origin:
        return origin.rstrip("/")
    for kwargs in ({"prefer_external": True}, {"allow_internal": True}):
        try:
            return get_url(hass, **kwargs).rstrip("/")
        except NoURLAvailableError:
            continue
    return origin.rstrip("/")


def json_response(data: Any, status: int = 200, headers: dict[str, str] | None = None) -> web.Response:
    """A JSON response."""
    return web.Response(
        body=json.dumps(data, default=str).encode(),
        content_type="application/json",
        status=status,
        headers=headers or {},
    )


def oauth_error(
    error: str, description: str, status: int = 400, headers: dict[str, str] | None = None
) -> web.Response:
    """An RFC 6749 error response."""
    return json_response(
        {"error": error, "error_description": description}, status=status, headers=headers
    )


def html_response(body: str, status: int = 200) -> web.Response:
    """An HTML page."""
    return web.Response(text=body, content_type="text/html", status=status)


def page(title: str, body: str) -> str:
    """Wrap page content in a minimal, theme-aware document."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #f5f5f5; --card: #ffffff; --fg: #212121; --muted: #727272;
    --accent: #03a9f4; --border: #e0e0e0; --danger: #db4437;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #111416; --card: #1c1f22; --fg: #e1e1e1; --muted: #9b9b9b;
      --border: #2e3338;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: 16px; background: var(--bg); color: var(--fg);
    font-family: Roboto, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    line-height: 1.5;
  }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 28px; max-width: 480px; width: 100%;
    box-shadow: 0 2px 12px rgba(0,0,0,.08);
  }}
  h1 {{ font-size: 1.35rem; margin: 0 0 4px; font-weight: 500; }}
  p {{ margin: 12px 0; }}
  .muted {{ color: var(--muted); font-size: .9rem; }}
  dl {{ margin: 20px 0; display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; font-size: .9rem; }}
  dt {{ color: var(--muted); }}
  dd {{ margin: 0; word-break: break-all; }}
  ul {{ margin: 8px 0; padding-left: 20px; font-size: .9rem; }}
  .actions {{ display: flex; gap: 12px; margin-top: 24px; flex-wrap: wrap; }}
  button {{
    flex: 1 1 140px; padding: 12px 20px; border-radius: 8px; border: none;
    font-size: 1rem; font-family: inherit; cursor: pointer; font-weight: 500;
  }}
  .primary {{ background: var(--accent); color: #fff; }}
  .secondary {{ background: transparent; color: var(--fg); border: 1px solid var(--border); }}
  code {{
    background: color-mix(in srgb, var(--fg) 8%, transparent);
    padding: 2px 6px; border-radius: 4px; font-size: .85em;
  }}
  .error {{ color: var(--danger); }}
</style>
</head>
<body><div class="card">{body}</div></body>
</html>"""
