#!/usr/bin/env python3
"""Minimal MCP client for driving the dev server."""
import json, os, sys, urllib.request, pathlib

BASE = os.environ.get("BASE", "http://localhost:8123").rstrip("/")
ENDPOINT = f"{BASE}/mcp_domora/mcp"
DIR = pathlib.Path(__file__).parent.parent
SESSION = {"id": None}


def _refresh():
    """Home Assistant access tokens last 30 minutes; trade the refresh token in."""
    import urllib.parse
    refresh = (DIR / ".refresh").read_text().strip()
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": refresh,
        "client_id": f"{BASE}/"}).encode()
    req = urllib.request.Request(f"{BASE}/auth/token", data=body, method="POST")
    with urllib.request.urlopen(req) as resp:
        token = json.load(resp)["access_token"]
    (DIR / ".token").write_text(token)
    return token


TOKEN = None


def get_token():
    """Refresh on first use, not when this module is imported."""
    global TOKEN
    if TOKEN is None:
        TOKEN = _refresh()
    return TOKEN


def rpc(method, params=None, _id=[0]):
    _id[0] += 1
    message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if not method.startswith("notifications/"):
        message["id"] = _id[0]
    body = json.dumps(message).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "Authorization": f"Bearer {get_token()}"}
    if SESSION["id"]:
        headers["Mcp-Session-Id"] = SESSION["id"]
    req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            if sid := resp.headers.get("Mcp-Session-Id"):
                SESSION["id"] = sid
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        return {"HTTP_ERROR": err.code, "body": err.read().decode()[:600]}


def call(name, args=None):
    out = rpc("tools/call", {"name": name, "arguments": args or {}})
    if "result" not in out:
        return out
    result = out["result"]
    text = result["content"][0]["text"] if result.get("content") else ""
    return {"isError": result.get("isError"), "text": text}


if __name__ == "__main__":
    init = rpc("initialize", {"protocolVersion": "2025-06-18",
                              "capabilities": {}, "clientInfo": {"name": "devtest", "version": "1"}})
    print("initialize:", json.dumps(init.get("result", init), indent=2)[:420])
    rpc("notifications/initialized")
    if len(sys.argv) > 1:
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        print(json.dumps(call(sys.argv[1], args), indent=2))
