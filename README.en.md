# MCP Domora for Home Assistant

![MCP Domora logo](custom_components/mcp_domora/brand/icon.png)

Connect Home Assistant to Codex and other MCP clients through your own Home Assistant instance. An agent can read states, control devices, edit automations, manage backups, and assist with integration reauthentication.

[Deutsch](README.md) · English

> **Status:** Version 0.4.1 · Home Assistant 2026.10 or later · MIT license
> The connection, OAuth, and backup creation were tested on an isolated Home Assistant Core 2026.10.4 instance. HAOS restore and individual cloud-provider login flows have not yet been tested end to end.

See the [changelog](CHANGELOG.md) for version history and [GitHub Releases](https://github.com/daMustermann/mcp-domora-home-assistant/releases) for published versions.

## Capabilities

| Area | Examples |
| --- | --- |
| Devices and entities | Read states, call services, find devices, areas, and labels |
| Automations | List, validate, create, edit, trigger, and inspect traces |
| Scripts and scenes | Read, create, edit, run, and delete |
| Home Assistant | Manage integrations, helpers, dashboards, logbook, history, and repairs |
| App development | Create and edit a project, add an app repository, reload the store, install, inspect build status and logs |
| Backups | Discover destinations, create backups, inspect details, and request a restore |
| Sign-in | Start and continue reauthentication flows for existing integrations |
| Advanced | Render templates and call Home Assistant's WebSocket API |

Tool groups and individual tools can be enabled or disabled in the integration options. MCP Domora supports Streamable HTTP and legacy HTTP/SSE.

## Requirements

- Home Assistant 2026.10 or later with its HTTP interface running.
- A Home Assistant account; some tools require an administrator.
- An MCP client that can reach Home Assistant over the network.
- For HACS: HACS installed and a version of this repository published on GitHub.

The bridge runs **inside Home Assistant Core** and is unavailable when Core is down. A Home Assistant backup covers selected contents; it is not an atomic VM or disk snapshot.

## Installation

### HACS

1. In HACS, open **⋮ → Custom repositories**.
2. Add `https://github.com/daMustermann/mcp-domora-home-assistant` with category **Integration**.
3. Install **MCP Domora** and restart Home Assistant.
4. Under **Settings → Devices & services → Add integration**, search for **MCP Domora** and complete setup.

HACS installs the version published on GitHub. Local changes are available through HACS only after they have been pushed. If a suitable version is not available in HACS, use the manual installation.

### Manual

1. Copy `custom_components/mcp_domora` from this repository to `/config/custom_components/mcp_domora` on your Home Assistant system.
2. Restart Home Assistant.
3. Add **MCP Domora** under **Settings → Devices & services → Add integration**.

When updating, replace the integration folder and restart Home Assistant. Home Assistant's `/config/.storage` data is separate and should be left in place.

## Connect Codex

For a local installation, the MCP endpoint might be:

```text
http://homeassistant:8123/mcp_domora/mcp
```

In a terminal with the Codex CLI installed:

```bash
codex mcp add domora --url http://homeassistant:8123/mcp_domora/mcp
codex mcp login domora
codex mcp list
```

Codex opens the Home Assistant login flow. The address must be reachable from Codex. Other MCP clients can use the same URL and OAuth discovery; some clients require HTTPS.

Alternatively, create a long-lived Home Assistant access token and configure Codex to read it from an environment variable:

```toml
[mcp_servers.domora]
url = "http://homeassistant:8123/mcp_domora/mcp"
bearer_token_env_var = "HOME_ASSISTANT_TOKEN"
```

Set the environment variable for the Codex process. Keep the token out of repositories and screenshots. Acceptance of Home Assistant tokens can be disabled in the integration options.

## Backups and restore

Before substantial changes, the agent should create a backup and check its completion, contents, and destination:

1. `list_backup_locations` lists actual backup destinations.
2. `create_backup` starts a backup. Without additional options it uses the configured automatic backup settings. For explicit settings, pass `agent_ids` from step 1; by default the request includes Home Assistant, the database, all add-ons, and the `share`, `addons/local`, `ssl`, and `media` folders. Verify the actual contents afterward.
3. `list_backups` shows status and available backups; `get_backup_details` returns details for a specific backup.
4. `restore_backup` requests restoration of a selected backup from a selected location. A restore may overwrite current data and disconnect Home Assistant.

The agent is instructed to check for a suitable backup before major changes; the server does not enforce an automatic backup before every tool call. Coverage, destinations, and encryption depend on your Home Assistant configuration. Keep the encryption key and, where possible, a copy of the backup outside the system. Test restoration on a suitable test system.

## Develop apps with a coding agent

`create_addon_project` creates an editable app repository with `repository.yaml`, `config.yaml`, `Dockerfile` and `run.sh` under `/config/mcp_domora_projects/<slug>`. The agent can edit UTF-8 source files with `list_addon_projects`, `list_addon_project_files`, `read_addon_project_file`, `write_addon_project_files`, and `delete_addon_project_file`.

The Supervisor **cannot automatically see** this project as a local app: it uses its own `local_apps` directory, which normally is not mounted in Home Assistant Core. Publish the project to a Git repository reachable by the Supervisor or copy the app subfolder to `local_apps` separately. Domora does not publish Git repositories or copy files into an unmounted directory.

Then use `add_addon_repository`, `reload_addon_store`, and `list_addon_store` to add and find the published app. `install_addon` starts installation in the background; check `get_addon_job` for its result. `get_addon_info`, `get_addon_logs`, and `rebuild_addon` help with testing. Enable **Allow disruptive tools** for start/stop through `manage_addon`. A rebuild can take a long time; configure an appropriate MCP client tool timeout.

These tools require an administrator; Supervisor operations require HAOS or a supported supervised installation. Project editing and Supervisor operations have not yet been tested end to end on HAOS.

## Expired credentials

`list_integrations` lists existing integrations. `start_reauthentication` starts a supported reauthentication flow; use `continue_flow` for subsequent steps. If a flow is already active, `list_flows_in_progress` shows its ID.

Provider login, email codes, MFA, or a provider confirmation may require additional steps. An agent may use separately connected browser or email tools, or ask the user for help. MCP Domora does not include an email client or automatic provider login. Support for Home Connect, Dreame, Tuya, Xiaomi, and other providers depends on the corresponding integration and provider.

## Configuration

Open **Settings → Devices & services → MCP Domora → Configure**:

- **Tool groups and individual tools:** enable or hide capabilities.
- **Entity exposure:** filter by domain, entity, area, or label.
- **Security:** configure read-only mode, disruptive tools, admin-only access, token acceptance, and response size.
- **Connected clients:** inspect and revoke connected OAuth clients.

Read-only mode is a useful starting point. Entity filters apply to many dedicated tools but are not a complete access boundary for all indirect paths. Template rendering and raw WebSocket access can expose additional information. OAuth scopes are stored but not independently enforced per tool; integration options and the Home Assistant account determine available access.

## Troubleshooting

- **404 at the MCP endpoint:** Check the installation path, restart Home Assistant, and ensure MCP Domora has been added under Devices & services.
- **Login fails:** Check that the client can reach the configured hostname and the OAuth callback. For reverse proxies, configure Home Assistant's proxy settings appropriately.
- **A tool is missing:** Check tool groups, individual tools, read-only mode, and administrator access. Some tools require Supervisor or other Home Assistant integrations.
- **A backup is missing:** The job may still be running, or the destination may have reported an error. Check `list_backups` and `get_backup_details`.
- **Logo missing in HACS:** Home Assistant loads the logo from the integration. Older HACS interfaces may still display a placeholder; see [HACS issue #5402](https://github.com/hacs/integration/issues/5402).
- **Home Assistant is down:** MCP Domora runs inside Core. Use Home Assistant's normal recovery methods when Core is unavailable.

## Development and tests

The integration lives in `custom_components/mcp_domora/`. The scripts in `dev/scripts/` are development utilities for a separate test instance; some create, modify, and delete Home Assistant configuration. Do not run them against a production instance.

Run the offline tests with:

```bash
python -m unittest discover -s tests
```

See [the development script guide](dev/scripts/README.md) for prerequisites and limitations.

## License

[MIT](LICENSE)
