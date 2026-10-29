# Changelog

## 0.4.2 — Local connection address

- Prefer a local Home Assistant URL in setup and options instead of a cloud or external URL.
- Document how to connect over the local network.

## 0.4.1 — MCP Domora branding

- Add local Home Assistant brand icons for light and dark themes, in standard and high resolution.
- Add the logo to the German and English READMEs.

## 0.4.0 — App development

- Add project workspaces for creating and editing Home Assistant app source files.
- Add Supervisor store discovery, repository registration, app installation,
  job inspection, app details, rebuild and log retrieval.
- Fix app log access for the current Home Assistant Supervisor client.
- Document the separate publication/copy step required between project workspaces
  and the Supervisor's local app directory.

The project tools were tested on an isolated Home Assistant Core instance. Supervisor
requests have unit tests, but installation and rebuild have not been tested on HAOS.

## 0.3.1 — Repository rename

- Update the GitHub, HACS, documentation and issue tracker links to
  `daMustermann/mcp-domora-home-assistant`.

## 0.3.0 — MCP Domora

- Introduce the MCP Domora name, `mcp_domora` integration domain and HTTP paths.
- Add backup destination discovery, backup details and restore requests.
- Support starting existing integrations' reauthentication flows and returning external login URLs.
- Update device registry handling for current Home Assistant releases.
- Add English and German installation documentation and a development script guide.
- Improve OAuth, PKCE, SSE and development client checks and guard the write regression script.

Tested on an isolated Home Assistant Core 2026.10.4 instance. HAOS backup restoration
and individual cloud-provider reauthentication flows have not been tested end to end.
