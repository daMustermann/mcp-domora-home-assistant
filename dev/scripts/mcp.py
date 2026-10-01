#!/usr/bin/env python3
"""Minimal MCP client for driving the dev server."""
import json, sys, urllib.request, pathlib

BASE = "http://localhost:8123"
ENDPOINT = f"{BASE}/mcp_bridge/mcp"
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


TOKEN = _refresh()


def rpc(method, params=None, _id=[0]):
    _id[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": method,
                       "params": params or {}}).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "Authorization": f"Bearer {TOKEN}"}
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
    return {"isError": result.get("isError"), "text": text[:2500]}


if __name__ == "__main__":
    init = rpc("initialize", {"protocolVersion": "2025-06-18",
                              "capabilities": {}, "clientInfo": {"name": "devtest", "version": "1"}})
    print("initialize:", json.dumps(init.get("result", init), indent=2)[:420])
    rpc("notifications/initialized")
    if len(sys.argv) > 1:
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        print(json.dumps(call(sys.argv[1], args), indent=2))
