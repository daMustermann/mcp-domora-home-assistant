# MCP Bridge for Home Assistant

A Model Context Protocol server for Home Assistant that exposes the whole instance —
not just a handful of intents — to MCP clients like Claude, and lets you decide
exactly how much of it each client may touch.

Home Assistant's built-in [`mcp_server`](https://www.home-assistant.io/integrations/mcp_server/)
exposes only the Assist intents: turning things on and off, and reading a few states.
It cannot read or write an automation, look at a trace, create a helper, touch the
registry, or add an integration. This can.

**81 tools across 16 groups**, including the automation editor, the script and scene
editors, the area/device/entity registries, config flows, history and statistics,
dashboards, add-ons and a raw WebSocket escape hatch for anything not covered.

Everything is gated: per tool group, per individual tool, per entity domain, per
entity, per area and per label — configured in the Home Assistant UI.

> **Status:** v0.1.0, first release. Tested against Home Assistant 2026.9 with the
> full tool surface exercised end to end, but it is new code. Read
> [Security](#security) before you point anything at a production instance.

---

## Why this exists

| | Built-in `mcp_server` | MCP Bridge |
| --- | --- | --- |
| Read states | yes | yes |
| Control devices | Assist intents only | every service, with full parameter schemas |
| Read an automation | no | yes |
| Create / edit / delete automations | no | yes, validated, stays UI-editable |
| Automation traces (why did it not run?) | no | yes |
| Scripts, scenes, helpers | no | full CRUD |
| Areas, floors, labels, devices, entity registry | no | full CRUD |
| Add or reconfigure an integration | no | yes, via config flows |
| History, logbook, long-term statistics | no | yes |
| Templates | no | yes, render and analyse |
| Dashboards | no | read and write |
| Add-ons, backups, error log, repairs | no | yes |
| Anything else Home Assistant can do | no | `websocket_command` escape hatch |
| Auth | long-lived token | OAuth 2.1 + PKCE + dynamic registration, or a token |
| Configurable scope | expose entities | tools, groups, domains, entities, areas, labels |

---

## Install

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/mkenfenheuer/claude-mcp-homeassistant`, category **Integration**
3. Install **MCP Bridge**, then restart Home Assistant
4. **Settings → Devices & services → Add integration → MCP Bridge**

### Manual

Copy `custom_components/mcp_bridge` into your Home Assistant `config/custom_components/`
directory, restart, then add the integration.

---

## Connect a client

The server URL is:

```
https://your-home-assistant/mcp_bridge/mcp
```

It speaks **Streamable HTTP** (the current MCP transport). There is also a legacy
HTTP+SSE endpoint at `/mcp_bridge/sse` for older clients and proxies.

### With OAuth (recommended)

Point the client at the URL and let it discover the rest. It will register itself,
open a consent page, send you to Home Assistant's own login, and store the token it
gets back. Nothing needs to be configured by hand, and your password never reaches
the integration.

```bash
claude mcp add --transport http home-assistant https://your-home-assistant/mcp_bridge/mcp
```

For Claude Desktop, or any client that only speaks stdio:

```json
{
  "mcpServers": {
    "home-assistant": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://your-home-assistant/mcp_bridge/mcp"]
    }
  }
}
```

### With a long-lived access token

For clients that do not do OAuth, create a token under your Home Assistant profile
and send it as a bearer token:

```json
{
  "mcpServers": {
    "home-assistant": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "https://your-home-assistant/mcp_bridge/mcp",
        "--header", "Authorization: Bearer YOUR_LONG_LIVED_TOKEN"
      ]
    }
  }
}
```

You can turn this off entirely with **allow_ha_tokens** if you want OAuth to be the
only way in.

> Home Assistant must be reachable by the client over HTTPS for OAuth to work in most
> clients. Behind a reverse proxy, set `use_x_forwarded_for` and `trusted_proxies` in
> your `http:` config so the issued URLs carry the right hostname.

---

## Configure

**Settings → Devices & services → MCP Bridge → Configure.**

| Screen | What it controls |
| --- | --- |
| **Tool groups** | Switch whole capabilities on or off. A disabled group is not advertised at all. |
| **Individual tools** | Every one of the 81 tools, individually. Unchecked tools disappear even if their group is on. |
| **Entity exposure** | Which entities clients can see and control: allow or deny by domain, by entity, by area, by label. An explicit include always wins. |
| **Security** | Read-only mode, disruptive tools, admin-only access, whether long-lived tokens are accepted, response size cap. |
| **Connected clients** | Which clients hold a token, when they last used it, and a switch to revoke any of them. |

### Defaults

Everything is on except:

- **Disruptive tools** are off: `restart_home_assistant`, `set_state` and
  `manage_addon` are hidden until you enable them.
- `tts`, `stt`, `conversation` and `wake_word` entities are excluded as noise.
- Hidden and disabled entities are excluded.

### Suggested starting points

**Cautious** — read-only mode on. The client can explore and explain everything, and
change nothing.

**Day to day** — defaults, plus exclude anything safety-related from entity exposure:
locks, alarm panels, garage doors, cameras.

**Full workshop access** — enable disruptive tools and the `raw` group. Appropriate
for a test instance you are happy to break.

---

## Security

**This is a powerful integration. Read this part.**

- Every tool call runs **as the Home Assistant user who authorised the client**, with
  that user's own permissions. A non-admin cannot reach admin-only tools, and entity
  permissions are enforced per call.
- User authentication is **delegated to Home Assistant's own login page** —
  IndieAuth, the same flow the frontend uses. Credentials and MFA never pass through
  this integration.
- Tokens issued here are backed by a real Home Assistant refresh token. Revoking the
  session in Home Assistant, or the client in the options, kills access immediately.
- OAuth is **OAuth 2.1**: PKCE (S256) is mandatory, authorization codes are
  single-use and expire in five minutes, refresh tokens rotate on every use, and
  redirect URIs are verified against registration or IndieAuth discovery.
- Entity exposure is enforced on **resolved** targets, so a call aimed at an area or a
  label cannot reach an entity you excluded.
- Stored tokens are hashed. The store is a private Home Assistant storage file.

What this cannot protect you from: an MCP client you have given full access to is, by
design, able to edit automations, remove integrations and change your registry. The
model driving it can make mistakes. Use read-only mode, the entity filter and the
per-tool switches to decide how much you are comfortable delegating, and take a
backup before letting one loose on a live instance.

---

## How the authentication works

```
MCP client                  MCP Bridge                     Home Assistant
    |                            |                                |
    |-- discover metadata ------>|  /.well-known/oauth-*          |
    |-- register (RFC 7591) ---->|  issues a client_id URL        |
    |-- /authorize + PKCE ------>|  consent page                  |
    |                            |-- redirect to HA login ------->|
    |                            |                     you sign in (IndieAuth)
    |                            |<-- authorization code ---------|
    |                            |-- exchange for refresh token ->|
    |<-- authorization code -----|                                |
    |-- /token + verifier ------>|  issues access + refresh       |
    |-- Bearer token ----------->|  validates, resolves your user |
    |                            |-- acts as you ---------------->|
```

Home Assistant 2026.9 serves its own `/.well-known/oauth-authorization-server`, so
this server publishes its metadata at the issuer-scoped paths
`/.well-known/oauth-authorization-server/mcp_bridge` and
`/.well-known/oauth-protected-resource/mcp_bridge/mcp`. Clients find them from the
`WWW-Authenticate` header on a 401, exactly as the MCP spec describes.

The reason this server acts as its own authorization server, rather than pointing
clients straight at Home Assistant, is that Home Assistant's OAuth endpoint offers
neither dynamic client registration nor PKCE — which most MCP clients require.

---

## Tool reference

Tools marked **write** change something. **admin** needs a Home Assistant
administrator. **disruptive** tools are hidden until you enable them.

### Automations (incl. create/edit/delete)

| Tool | Notes | What it does |
| --- | --- | --- |
| `create_automation` | write | Create a new automation in automations.yaml and reload it so it takes effect immediately. The config is validated first and nothing is written if… |
| `delete_automation` | write, admin | Permanently remove an automation from automations.yaml and drop its entity. The returned `deleted_config` is the only copy left - keep it if you… |
| `get_automation` | read | The complete stored config of one automation, by entity id, automation id or alias. Read this before updating, and pass the result back with your… |
| `get_automation_traces` | read | The recent runs of an automation. This is the fastest way to find out why one did not do what was expected: each trace shows which trigger fired,… |
| `list_automations` | read | Every automation with its state, mode, when it last ran, and whether it is editable. `editable` is false for automations defined in… |
| `list_device_automations` | read | The device triggers, conditions and actions Home Assistant offers for a device - the same list the UI automation editor shows under "Device". |
| `reload_automations` | write | Re-read automations.yaml. The editing tools reload automatically, so you only need this after the file was changed outside Home Assistant, or to… |
| `set_automation_enabled` | write | Turn an automation on or off. A disabled automation keeps its config but stops reacting to triggers. This is reversible and is usually the right… |
| `trigger_automation` | write | Run an automation's actions immediately, as if it had been triggered. By default its conditions are skipped, which is what you want for testing;… |
| `update_automation` | write | Change an existing automation. By default the config is replaced wholesale, so read it with get_automation first and send the complete new… |
| `validate_automation_config` | read | Check an automation config without saving it. Run this before create_automation or update_automation: it catches unknown triggers, bad templates… |

### Service calls & device control

| Tool | Notes | What it does |
| --- | --- | --- |
| `call_service` | write | Call any Home Assistant service. This is the general-purpose way to control the home: turn things on and off, set temperatures, send… |
| `list_services` | read | The service catalog: every callable service with its description, its fields and what it can target. This is the authoritative reference for what… |
| `set_state` | write, admin, disruptive | Write a state into the state machine without going through the integration that owns the entity. This is a debugging tool: the real integration… |

### Lovelace dashboards

| Tool | Notes | What it does |
| --- | --- | --- |
| `get_dashboard_config` | read | The full card configuration of a dashboard. Read this before editing - saving replaces the whole dashboard, so you need the current config to… |
| `list_dashboards` | read | Every Lovelace dashboard, plus the custom resources (JavaScript modules) that are loaded. The default dashboard has no url_path; others are… |
| `manage_dashboard` | write, admin | Manage dashboards themselves. `create` needs a title and a url_path containing a hyphen (Home Assistant requires one). Deleting a dashboard… |
| `save_dashboard_config` | write, admin | Replace a dashboard's configuration. This overwrites everything, so always start from get_dashboard_config, change what you need and send the… |

### Event bus (fire & listen)

| Tool | Notes | What it does |
| --- | --- | --- |
| `fire_event` | write | Fire a custom event on the event bus. Mainly useful for testing an automation that triggers on an event, and for the `custom_event` pattern where… |
| `list_event_listeners` | read | Every event type something is currently listening for, with the number of listeners. This is how you discover what event an integration fires so… |
| `listen_for_events` | read | Wait for events of a given type and return the ones that arrive, up to a limit or a timeout. This is the way to find out what a physical control… |

### Helpers (input_*, counter, timer, schedule)

| Tool | Notes | What it does |
| --- | --- | --- |
| `create_helper` | write | Create a helper entity. Helpers are the usual way to give an automation state of its own: a toggle to enable a feature, a number to hold a… |
| `delete_helper` | write, admin | Permanently remove a helper. Anything referring to it - automations, scripts, dashboards, templates - will break, so check for references first,… |
| `list_helpers` | read | Every helper entity grouped by type, with its stored config. Only helpers created through the UI or this API are editable; ones defined in… |
| `update_helper` | write | Change a helper's configuration. Pass the complete set of fields: a helper update replaces the stored config, so omitted optional fields fall back… |

### History, logbook & statistics

| Tool | Notes | What it does |
| --- | --- | --- |
| `get_history` | read | How entities changed over a period. Use this to answer "when did X last happen", to check whether a sensor is reporting, or to see the state an… |
| `get_logbook` | read | The human-readable event log: what happened, when, and what caused it. Logbook entries name the automation or user behind a change, which makes… |
| `get_statistics` | read | Aggregated values over time for entities that record statistics. Pick the period to match the question: `hour` for a day, `day` for a month,… |
| `list_statistics` | read | Which entities have long-term statistics, and in what unit. Statistics are hourly and daily aggregates kept forever, unlike state history which is… |

### Config entries & integration setup flows

| Tool | Notes | What it does |
| --- | --- | --- |
| `abort_flow` | write, admin | Cancel a config or options flow that is in progress. |
| `continue_flow` | write, admin | Submit values for the current step of a config or options flow. The result is either the next step, or `create_entry`/`abort` when the flow has… |
| `list_available_integrations` | read | Every integration domain that supports a UI setup flow, i.e. everything you could add with start_config_flow. Filter with `search` - the full list… |
| `list_flows_in_progress` | read | Config flows waiting for input, including ones Home Assistant started itself from discovery. A discovered device usually only needs a confirmation… |
| `list_integrations` | read | Every configured integration (config entry) with its state, options and whether it loaded. Check `state` and `error_reason_translation_key` when… |
| `manage_integration` | write, admin | Act on a configured integration: `reload` re-reads it (the usual fix after changing something), `disable`/`enable` keep the configuration but stop… |
| `start_config_flow` | write, admin | Begin setting up a new integration. The result describes the first step and the fields it wants; fill them in with continue_flow. |
| `start_options_flow` | write, admin | Open the options (or reconfigure) flow of an existing config entry - the UI's "Configure" button. Use this to change an integration's settings;… |

### Camera snapshots & media browsing

| Tool | Notes | What it does |
| --- | --- | --- |
| `browse_media` | read | Browse what a media player can play, or the media sources Home Assistant knows about (local media, TTS, radio). Walk down the tree by passing a… |
| `get_camera_snapshot` | read | Fetch a still image from a camera and return it as an image you can look at. Use it to answer questions about what is actually happening - whether… |

### Raw WebSocket API escape hatch

| Tool | Notes | What it does |
| --- | --- | --- |
| `list_websocket_commands` | read | Every WebSocket API command this instance supports. Anything the Home Assistant frontend can do is in here, so when no dedicated tool covers what… |
| `websocket_command` | write, admin | Call any Home Assistant WebSocket API command directly, as the signed-in user. This reaches everything the frontend can do, including corners with… |

### Areas, floors, labels, devices, entity registry

| Tool | Notes | What it does |
| --- | --- | --- |
| `list_areas` | read | The organisational structure of the home: floors, the areas on them, and the labels in use. Area and label ids are what the other tools and… |
| `list_devices` | read | Physical devices and the entities they provide. Use this when a request is about a thing rather than a reading - one device usually owns several… |
| `manage_area` | write, admin | Manage areas. `create` needs a name; `update` and `delete` need an area_id. Deleting an area does not delete the devices in it, it only unassigns… |
| `manage_floor` | write, admin | Manage floors. `create` needs a name; `level` orders them (ground floor is 0). |
| `manage_label` | write, admin | Manage labels. Labels cut across areas - "battery powered", "holiday lighting", "critical" - and can be used as a service target, so one call… |
| `remove_entity` | write, admin | Delete an entity's registry entry. This only works for entities whose integration allows removal; for most, the entity comes back as soon as the… |
| `update_device` | write, admin | Rename a device, move it to an area, label it, or disable it. Renaming a device can rename its entities too - Home Assistant asks about that in… |
| `update_entity` | write, admin | Change how an entity is registered: rename it, change its entity id, assign it to an area, label it, hide or disable it, or set options such as a… |

### Scenes (incl. create/edit/delete)

| Tool | Notes | What it does |
| --- | --- | --- |
| `apply_scene` | write | Activate a scene, optionally with a transition in seconds. `apply_states` applies a set of states directly without saving a scene first, which is… |
| `create_scene` | write | Create a scene in scenes.yaml. `entities` maps entity ids to the state they should take, either as a plain state (`"on"`) or an object with… |
| `delete_scene` | write, admin | Permanently remove a scene from scenes.yaml. |
| `get_scene` | read | The stored config of one scene, including the state it sets per entity. |
| `list_scenes` | read | Every scene, when it was last applied, and whether it is editable. |
| `update_scene` | write | Replace a scene's config, or patch parts of it with `merge`. |

### Scripts (incl. create/edit/delete)

| Tool | Notes | What it does |
| --- | --- | --- |
| `create_script` | write | Create a script in scripts.yaml and reload it. The config is validated first. `sequence` is required. The entity becomes `script.<script_id>`; if… |
| `delete_script` | write, admin | Permanently remove a script from scripts.yaml. The returned `deleted_config` is the only copy left. Check whether any automation calls this script… |
| `get_script` | read | The stored config of one script. Read this before updating it. |
| `list_scripts` | read | Every script with its state, mode and last run. `editable` is false for scripts defined in configuration.yaml. |
| `run_script` | write | Run a script now. Pass `variables` for a script that declares fields. By default this waits for the script to finish, so failures surface and any… |
| `update_script` | write | Replace a script's config. Read it with get_script first and send the complete new version, or set `merge` to patch individual keys. |

### Entities & states (read)

| Tool | Notes | What it does |
| --- | --- | --- |
| `describe_entity` | read | Everything Home Assistant knows about one entity: its state, its registry entry, the device and area it belongs to, which integration provides it,… |
| `get_overview` | read | A compact map of the home: floors, areas, how many entities of each domain sit in them, and counts of anything unavailable. Start here when you do… |
| `get_state` | read | Read the full state of one or more entities, including all attributes. Use this before changing anything so you work from real values rather than… |
| `list_entities` | read | Find entities. Every filter is optional and they combine with AND; with no filters you get everything exposed to you, which can be a lot - prefer… |

### Supervisor & add-ons

| Tool | Notes | What it does |
| --- | --- | --- |
| `create_backup` | write, admin | Start a backup. Worth doing before any risky change - removing an integration, editing many automations at once, or restarting into a new version. |
| `get_supervisor_info` | admin | Supervisor, host and operating system information, plus the installed add-ons. Use it to see what the installation actually is before suggesting… |
| `list_addons` | admin | Installed add-ons with their version, state and whether an update is available. |
| `list_backups` | admin | Existing backups with their date, size and what they contain. |
| `manage_addon` | write, admin, disruptive | Control an installed add-on. `info` returns its full state and options, `logs` returns its recent output - which is where to look when an add-on… |

### System info, logs, repairs, restart

| Tool | Notes | What it does |
| --- | --- | --- |
| `check_config` | admin | Validate the whole Home Assistant configuration without restarting. Always run this after editing YAML by hand, and before restarting - a restart… |
| `clear_error_log` | write, admin | Discard the collected warnings and errors, so new ones stand out. |
| `get_config` | read | Core configuration: version, timezone, location, unit system, config directory and which integrations are loaded. Check the version here before… |
| `get_error_log` | admin | Recent warnings and errors. Start here when something does not work and the cause is not obvious - a failed integration, a template error or a… |
| `get_system_info` | read | Installation details: Home Assistant and Python versions, operating system, whether it runs in a container or on Home Assistant OS, and the… |
| `list_repairs` | read | Open repair issues: deprecations, misconfigurations and problems Home Assistant has noticed about itself. Worth checking whenever something… |
| `list_users` | admin | Home Assistant user accounts with their groups and whether they are administrators. Useful for working out whose context an automation runs in, or… |
| `reload_config` | write, admin | Reload YAML configuration without restarting. With no domain this reloads everything that supports it (`homeassistant.reload_all`); with a domain… |
| `restart_home_assistant` | write, admin, disruptive | Restart or stop Home Assistant. This disconnects everything, including this MCP session, for a minute or more. |

### Template rendering

| Tool | Notes | What it does |
| --- | --- | --- |
| `list_template_entities` | read | Which entities a template depends on, without rendering it. Useful for checking that a template listens to what you expect before using it as a… |
| `render_template` | read | Evaluate a Jinja template against the live state machine and return the result. |
---

## Resources and prompts

Besides tools, the server exposes read-only **resources** —
`homeassistant://overview`, `://entities`, `://services`, `://config`, plus
`://entity/{entity_id}` and `://area/{area_id}` templates — and four **prompts**:
`home_overview`, `create_automation`, `debug_automation` and `audit_exposure`.

---

## Worth knowing

- **Automations defined in `configuration.yaml` cannot be edited**, only read and
  triggered. The `editable` flag in `list_automations` tells you which is which.
  Anything created here lands in `automations.yaml` and stays editable in the UI.
- **Configs are validated before they are written**, with Home Assistant's own
  validator, so a bad automation is rejected rather than saved broken.
  `validate_automation_config` lets a client check its work first.
- **`websocket_command` reaches anything not covered by a dedicated tool** — every
  command the frontend uses. It is admin-only; disable the `raw` group to remove it.
- **`render_template` doubles as a query language.** One template can filter and
  aggregate across hundreds of entities far more cheaply than listing them all.
- **Add-on tools only work on Home Assistant OS and Supervised installs.** On
  Container or Core they report that clearly instead of failing obscurely.

---

## Troubleshooting

**The client cannot authenticate.** Check that the client reaches Home Assistant on
the same hostname it will be redirected back to. Behind a proxy, set
`use_x_forwarded_for` and `trusted_proxies`. Watch the log with
`custom_components.mcp_bridge: debug`.

**A tool is missing.** It is almost certainly switched off. The error message says
which setting is responsible — group disabled, tool disabled, read-only mode,
disruptive tools, or admin required.

**An entity is invisible.** Check **Entity exposure**. Hidden and disabled entities
are excluded by default, as are `tts`, `stt`, `conversation` and `wake_word`.

**An automation will not save.** The validator's message is returned verbatim; it is
the same message the UI editor would show. Entity ids are the usual culprit.

**Browser-based clients and CORS.** Home Assistant's CORS policy does not allow the
`Mcp-Session-Id` request header, so browser clients may pass it as a `?session_id=`
query parameter instead. Add the client's origin to `http.cors_allowed_origins`.

---

## Development

A full dev instance in Podman or Docker:

```bash
git clone https://github.com/mkenfenheuer/claude-mcp-homeassistant
cd claude-mcp-homeassistant

podman run -d --name ha-mcp-dev -p 8123:8123 \
  -v "$PWD/dev/config:/config:z" \
  -v "$PWD/custom_components/mcp_bridge:/config/custom_components/mcp_bridge:z,ro" \
  ghcr.io/home-assistant/home-assistant:stable

./dev/scripts/onboard.sh          # creates user dev / devpassword123, writes dev/.token
python3 dev/scripts/mcp.py        # initialise a session
python3 dev/scripts/mcp.py list_entities '{"domain":"light"}'
python3 dev/scripts/oauth_test.py # the whole OAuth flow, step by step
python3 dev/scripts/pkce_test.py  # PKCE and redirect_uri enforcement
python3 dev/scripts/sse_test.py   # the legacy SSE transport
python3 dev/scripts/options.py show
```

The integration is laid out as:

```
custom_components/mcp_bridge/
  auth/        OAuth 2.1 + IndieAuth: token store, client resolution, endpoints
  mcp/         protocol dispatch, transports, sessions, resources, prompts
  tools/       the tool implementations, one module per group
  ws.py        runs Home Assistant WebSocket commands in-process as the user
  yaml_store.py  automations.yaml / scripts.yaml / scenes.yaml editing
  exposure.py  entity visibility rules
  registry.py  the tool registry the options UI reads
```

Adding a tool is a `@tool(...)` decorator in a `tools/` module; it shows up in the
MCP tool list and in the options UI automatically.

---

## License

MIT
