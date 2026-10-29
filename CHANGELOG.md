# Changelog

## 0.3.0 — MCP Domora

- Introduce the MCP Domora name, `mcp_domora` integration domain and HTTP paths.
- Add backup destination discovery, backup details and restore requests.
- Support starting existing integrations' reauthentication flows and returning external login URLs.
- Update device registry handling for current Home Assistant releases.
- Add English and German installation documentation and a development script guide.
- Improve OAuth, PKCE, SSE and development client checks and guard the write regression script.

Tested on an isolated Home Assistant Core 2026.10.4 instance. HAOS backup restoration
and individual cloud-provider reauthentication flows have not been tested end to end.
