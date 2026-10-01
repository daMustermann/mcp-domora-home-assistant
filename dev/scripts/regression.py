#!/usr/bin/env python3
"""Exercise every tool group and report pass/fail."""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mcp

mcp.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "regression", "version": "1"}})
mcp.rpc("notifications/initialized")

PASS, FAIL = [], []


def t(name, args=None, expect_error=False):
    out = mcp.rpc("tools/call", {"name": name, "arguments": args or {}})
    if "error" in out:
        got, detail = "protocol_error", out["error"]["message"]
    elif out.get("result", {}).get("isError"):
        got, detail = "tool_error", out["result"]["content"][0]["text"]
    else:
        got, detail = "ok", out["result"]["content"][0]["text"]
    want = "tool_error" if expect_error else "ok"
    (PASS if got == want else FAIL).append((name, got, detail[:200]))
    return detail


def payload(text):
    try:
        return json.loads(text)
    except Exception:
        return {}


# --- read ---
for name, args in [
    ("get_overview", {}), ("list_entities", {"domain": "sensor"}),
    ("get_state", {"entity_id": "input_boolean.dev_flag"}),
    ("describe_entity", {"entity_id": "input_boolean.dev_flag"}),
    ("list_services", {"domain": "light"}), ("list_areas", {}), ("list_devices", {}),
    ("list_helpers", {}), ("list_automations", {}), ("list_scripts", {}),
    ("list_scenes", {}), ("get_config", {}), ("get_system_info", {}),
    ("list_repairs", {}), ("list_users", {}), ("list_integrations", {}),
    ("list_available_integrations", {"search": "sun"}), ("list_flows_in_progress", {}),
    ("list_dashboards", {}), ("list_event_listeners", {}),
    ("list_websocket_commands", {"search": "config"}), ("list_statistics", {}),
    ("get_history", {"entity_ids": ["input_boolean.dev_flag"], "start_time": "-1h"}),
    ("get_logbook", {"start_time": "-30m"}), ("get_error_log", {"lines": 2}),
    ("render_template", {"template": "{{ 1 + 1 }}"}),
    ("list_template_entities", {"template": "{{ states('sun.sun') }}"}),
    ("websocket_command", {"type": "config/area_registry/list"}),
    ("browse_media", {}), ("get_supervisor_info", {}), ("list_backups", {}),
    ("get_dashboard_config", {}),
]:
    t(name, args)

# --- error handling ---
t("get_state", {"entity_id": "light.does_not_exist_anywhere"})          # unknown -> ok w/ note
t("call_service", {"domain": "light", "service": "no_such_service"}, expect_error=True)
t("render_template", {"template": "{{ broken("})                        # reports error in band
t("get_automation", {"automation_id": "nope"}, expect_error=True)
t("create_automation", {"alias": "x"}, expect_error=True)                # no actions
t("update_helper", {"entity_id": "light.kitchen", "config": {"name": "x"}}, expect_error=True)

# --- automation lifecycle ---
cfg = {"alias": "Regression Automation",
       "triggers": [{"trigger": "state", "entity_id": "input_boolean.dev_flag", "to": "on"}],
       "actions": [{"action": "input_boolean.turn_off",
                    "target": {"entity_id": "input_boolean.dev_flag"}}]}
t("validate_automation_config", cfg)
aid = payload(t("create_automation", cfg)).get("automation_id")
if aid:
    t("get_automation", {"automation_id": aid})
    t("set_automation_enabled", {"automation_id": aid, "enabled": False})
    t("set_automation_enabled", {"automation_id": aid, "enabled": True})
    t("trigger_automation", {"automation_id": aid})
    t("get_automation_traces", {"automation_id": aid})
    t("update_automation", {"automation_id": aid, "merge": True, "mode": "restart"})
    t("reload_automations", {})
    t("delete_automation", {"automation_id": aid})

# --- script lifecycle ---
sid = payload(t("create_script", {"alias": "Regression Script",
                                  "sequence": [{"delay": {"milliseconds": 1}}]})).get("script_id")
if sid:
    t("get_script", {"script_id": sid})
    t("run_script", {"script_id": sid})
    t("update_script", {"script_id": sid, "merge": True, "mode": "restart"})
    t("delete_script", {"script_id": sid})

# --- scene lifecycle ---
scid = payload(t("create_scene", {"name": "Regression Scene",
                                  "entities": {"input_boolean.dev_flag": "on"}})).get("scene_id")
if scid:
    t("get_scene", {"scene_id": scid})
    t("apply_scene", {"scene_id": scid})
    t("update_scene", {"scene_id": scid, "merge": True, "icon": "mdi:test-tube"})
    t("delete_scene", {"scene_id": scid})

# --- helper lifecycle ---
hid = payload(t("create_helper", {"domain": "input_text",
                                  "config": {"name": "Regression Text"}})).get("helper_id")
if hid:
    t("update_helper", {"domain": "input_text", "helper_id": hid,
                        "config": {"name": "Regression Text", "max": 50}})
    t("delete_helper", {"domain": "input_text", "helper_id": hid})

# --- registry lifecycle ---
area = payload(t("manage_area", {"action": "create", "name": "Regression Area"})).get("item", {}).get("area_id")
label = payload(t("manage_label", {"action": "create", "name": "regression"})).get("item", {}).get("label_id")
floor = payload(t("manage_floor", {"action": "create", "name": "Regression Floor", "level": 2})).get("item", {}).get("floor_id")
if area and label:
    t("update_entity", {"entity_id": "input_boolean.dev_flag", "area_id": area, "labels": [label]})
    t("list_entities", {"area": "Regression Area"})
    t("list_entities", {"label": "regression"})
    t("update_entity", {"entity_id": "input_boolean.dev_flag", "area_id": None, "labels": []})
for action, key, val in (("delete", "area_id", area), ("delete", "label_id", label), ("delete", "floor_id", floor)):
    if val:
        tool = {"area_id": "manage_area", "label_id": "manage_label", "floor_id": "manage_floor"}[key]
        t(tool, {"action": action, key: val})

# --- control, events, integrations ---
t("call_service", {"domain": "input_boolean", "service": "toggle",
                   "target": {"entity_id": "input_boolean.dev_flag"}})
t("fire_event", {"event_type": "regression_event", "event_data": {"ok": True}})
flow = payload(t("start_config_flow", {"domain": "min_max"}))
if flow.get("flow_id") and flow.get("type") == "form":
    t("abort_flow", {"flow_id": flow["flow_id"]})

print(f"PASS: {len(PASS)}")
print(f"FAIL: {len(FAIL)}")
for name, got, detail in FAIL:
    print(f"  {name} -> {got}: {detail}")
sys.exit(1 if FAIL else 0)
