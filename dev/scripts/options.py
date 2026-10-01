#!/usr/bin/env python3
"""Drive the options flow over the REST API, as the UI does."""
import json, pathlib, sys, urllib.request

BASE = "http://localhost:8123"
TOKEN = (pathlib.Path(__file__).parent.parent / ".token").read_text().strip()
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def api(path, data=None, method=None):
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(data).encode() if data is not None else None,
        headers=H, method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return {"HTTP_ERROR": e.code, "body": e.read().decode()[:400]}


def entry_id():
    for entry in api("/api/config/config_entries/entry"):
        if entry["domain"] == "mcp_bridge":
            return entry["entry_id"]
    raise SystemExit("mcp_bridge entry not found")


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
    for entry in api("/api/config/config_entries/entry"):
        if entry["domain"] == "mcp_bridge":
            return entry.get("options", {})
    return {}


if __name__ == "__main__":
    if sys.argv[1] == "show":
        print(json.dumps(options(), indent=2))
    elif sys.argv[1] == "menu":
        eid = entry_id()
        flow = api("/api/config/config_entries/options/flow", {"handler": eid})
        print(json.dumps(flow, indent=2)[:700])
    else:
        print(json.dumps(set_options(sys.argv[1], json.loads(sys.argv[2])), indent=2)[:700])
