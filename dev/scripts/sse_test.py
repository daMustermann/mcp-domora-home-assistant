#!/usr/bin/env python3
"""Exercise the legacy HTTP+SSE transport (protocol 2024-11-05)."""
import json, pathlib, threading, urllib.request, queue

BASE = "http://localhost:8123"
TOKEN = (pathlib.Path(__file__).parent.parent / ".token").read_text().strip()
messages: queue.Queue = queue.Queue()
endpoint_q: queue.Queue = queue.Queue()


def read_stream():
    req = urllib.request.Request(f"{BASE}/mcp_bridge/sse",
                                 headers={"Authorization": f"Bearer {TOKEN}",
                                          "Accept": "text/event-stream"})
    with urllib.request.urlopen(req) as resp:
        event = None
        for raw in resp:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
                if event == "endpoint":
                    endpoint_q.put(data)
                elif event == "message":
                    messages.put(json.loads(data))


threading.Thread(target=read_stream, daemon=True).start()
endpoint = endpoint_q.get(timeout=15)
print("endpoint announced:", endpoint)


def send(method, params=None, _id=[0]):
    _id[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": method,
                       "params": params or {}}).encode()
    req = urllib.request.Request(f"{BASE}{endpoint}", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {TOKEN}"}, method="POST")
    with urllib.request.urlopen(req) as r:
        assert r.status == 202, r.status
    return messages.get(timeout=20)


init = send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "sse-test", "version": "1"}})
print("initialize over SSE:", init["result"]["serverInfo"]["name"],
      "| protocol:", init["result"]["protocolVersion"])
tools = send("tools/list")
print("tools over SSE:", len(tools["result"]["tools"]))
called = send("tools/call", {"name": "render_template",
                             "arguments": {"template": "{{ 6 * 7 }}"}})
print("tool call over SSE:", called["result"]["content"][0]["text"][:80].replace("\n", " "))
