#!/usr/bin/env python3
"""Drive the options flow over the REST API, as the UI does."""
import json, os, sys, urllib.request
import mcp

BASE = os.environ.get("BASE", "http://localhost:8123").rstrip("/")


def api(path, data=None, method=None):
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": f"Bearer {mcp.get_token()}",
                 "Content-Type": "application/json"},
        method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return {"HTTP_ERROR": e.code, "body": e.read().decode()[:400]}


def entry_id():
    for entry in api("/api/config/config_entries/entry"):
        if entry["domain"] == "mcp_domora":
            return entry["entry_id"]
    raise SystemExit("mcp_domora entry not found")


def set_options(step, values):
    """Open the options flow, walk to `step`, and submit `values`."""
    eid = entry_id()
    flow = api("/api/config/config_entries/options/flow", {"handler": eid})
    if "HTTP_ERROR" in flow:
        return flow
    fid = flow["flow_id"]
    # The first screen is a menu; choosing a menu option submits next_step_id.
    picked = api(f"/api/config/config_entries/options/flow/{fid}", {"next_step_id": step})
    if "HTTP_ERROR" in picked:
        return picked
    return api(f"/api/config/config_entries/options/flow/{fid}", values)


def options():
    """Read the actual options through the MCP integration catalog."""
    mcp.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "options-test", "version": "1"}})
    result = mcp.rpc("tools/call", {"name": "list_integrations", "arguments": {"domain": "mcp_domora"}})
    if "error" in result or result.get("result", {}).get("isError"):
        raise SystemExit(f"Could not read integration options: {result}")
    data = json.loads(result["result"]["content"][0]["text"])
    entries = data.get("config_entries", [])
    if not entries:
        raise SystemExit("mcp_domora entry not found")
    return entries[0].get("options", {})


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: options.py show | menu | STEP JSON_VALUES")
    if sys.argv[1] == "show":
        print(json.dumps(options(), indent=2))
    elif sys.argv[1] == "menu":
        eid = entry_id()
        flow = api("/api/config/config_entries/options/flow", {"handler": eid})
        print(json.dumps(flow, indent=2)[:700])
    else:
        if len(sys.argv) < 3:
            raise SystemExit("Usage: options.py STEP JSON_VALUES")
        print(json.dumps(set_options(sys.argv[1], json.loads(sys.argv[2])), indent=2)[:700])
