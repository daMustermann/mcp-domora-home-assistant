"""Constants for the MCP Bridge integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "mcp_bridge"
NAME: Final = "MCP Bridge"

# Storage ---------------------------------------------------------------------
STORAGE_KEY: Final = f"{DOMAIN}.auth"
STORAGE_VERSION: Final = 1

# HTTP paths ------------------------------------------------------------------
BASE_PATH: Final = f"/{DOMAIN}"
MCP_PATH: Final = f"{BASE_PATH}/mcp"
SSE_PATH: Final = f"{BASE_PATH}/sse"
MESSAGES_PATH: Final = f"{BASE_PATH}/messages"
OAUTH_PATH: Final = f"{BASE_PATH}/oauth"
AUTHORIZE_PATH: Final = f"{OAUTH_PATH}/authorize"
CALLBACK_PATH: Final = f"{OAUTH_PATH}/callback"
TOKEN_PATH: Final = f"{OAUTH_PATH}/token"
REGISTER_PATH: Final = f"{OAUTH_PATH}/register"
REVOKE_PATH: Final = f"{OAUTH_PATH}/revoke"
CLIENT_DOC_PATH: Final = f"{OAUTH_PATH}/client"
# Home Assistant itself serves /.well-known/oauth-authorization-server and
# /.well-known/oauth-protected-resource for its own auth API, so this server uses
# the issuer-scoped forms. RFC 8414 inserts the issuer path before the well-known
# segment; some clients concatenate instead, so both spellings are served.
ISSUER_PATH: Final = BASE_PATH
AS_METADATA_PATH: Final = f"/.well-known/oauth-authorization-server{ISSUER_PATH}"
AS_METADATA_ALT_PATHS: Final = (
    f"{ISSUER_PATH}/.well-known/oauth-authorization-server",
    f"{ISSUER_PATH}/.well-known/openid-configuration",
    f"{OAUTH_PATH}/metadata",
)
PR_METADATA_PATH: Final = f"/.well-known/oauth-protected-resource{MCP_PATH}"
PR_METADATA_ALT_PATHS: Final = (
    f"{ISSUER_PATH}/.well-known/oauth-protected-resource",
    f"{OAUTH_PATH}/resource-metadata",
)

# MCP protocol ----------------------------------------------------------------
SUPPORTED_PROTOCOL_VERSIONS: Final = (
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)
LATEST_PROTOCOL_VERSION: Final = SUPPORTED_PROTOCOL_VERSIONS[0]
SERVER_VERSION: Final = "0.1.0"
SESSION_HEADER: Final = "Mcp-Session-Id"
PROTOCOL_HEADER: Final = "MCP-Protocol-Version"
SESSION_IDLE_TIMEOUT: Final = 3600

# OAuth / IndieAuth -----------------------------------------------------------
AUTH_CODE_TTL: Final = 300
ACCESS_TOKEN_TTL: Final = 28800
REFRESH_TOKEN_TTL: Final = 60 * 60 * 24 * 90
SCOPE_READ: Final = "homeassistant:read"
SCOPE_WRITE: Final = "homeassistant:write"
SCOPE_ADMIN: Final = "homeassistant:admin"
DEFAULT_SCOPES: Final = (SCOPE_READ, SCOPE_WRITE, SCOPE_ADMIN)

# Options ---------------------------------------------------------------------
CONF_TOOL_GROUPS: Final = "tool_groups"
CONF_DISABLED_TOOLS: Final = "disabled_tools"
CONF_ALLOWED_DOMAINS: Final = "allowed_domains"
CONF_EXCLUDED_DOMAINS: Final = "excluded_domains"
CONF_INCLUDE_ENTITIES: Final = "include_entities"
CONF_EXCLUDE_ENTITIES: Final = "exclude_entities"
CONF_INCLUDE_AREAS: Final = "include_areas"
CONF_INCLUDE_LABELS: Final = "include_labels"
CONF_EXPOSE_HIDDEN: Final = "expose_hidden"
CONF_READ_ONLY: Final = "read_only"
CONF_ALLOW_DANGEROUS: Final = "allow_dangerous"
CONF_REQUIRE_ADMIN: Final = "require_admin"
CONF_ALLOW_HA_TOKENS: Final = "allow_ha_tokens"
CONF_MAX_RESULTS: Final = "max_results"
CONF_REVOKE_CLIENTS: Final = "revoke_clients"

DEFAULT_MAX_RESULTS: Final = 500

# Tool groups -----------------------------------------------------------------
GROUP_STATES: Final = "states"
GROUP_CONTROL: Final = "control"
GROUP_AUTOMATION: Final = "automation"
GROUP_SCRIPT: Final = "script"
GROUP_SCENE: Final = "scene"
GROUP_HELPERS: Final = "helpers"
GROUP_REGISTRY: Final = "registry"
GROUP_INTEGRATIONS: Final = "integrations"
GROUP_HISTORY: Final = "history"
GROUP_TEMPLATE: Final = "template"
GROUP_SYSTEM: Final = "system"
GROUP_DASHBOARD: Final = "dashboard"
GROUP_SUPERVISOR: Final = "supervisor"
GROUP_MEDIA: Final = "media"
GROUP_EVENTS: Final = "events"
GROUP_RAW: Final = "raw"

TOOL_GROUP_LABELS: Final = {
    GROUP_STATES: "Entities & states (read)",
    GROUP_CONTROL: "Service calls & device control",
    GROUP_AUTOMATION: "Automations (incl. create/edit/delete)",
    GROUP_SCRIPT: "Scripts (incl. create/edit/delete)",
    GROUP_SCENE: "Scenes (incl. create/edit/delete)",
    GROUP_HELPERS: "Helpers (input_*, counter, timer, schedule)",
    GROUP_REGISTRY: "Areas, floors, labels, devices, entity registry",
    GROUP_INTEGRATIONS: "Config entries & integration setup flows",
    GROUP_HISTORY: "History, logbook & statistics",
    GROUP_TEMPLATE: "Template rendering",
    GROUP_SYSTEM: "System info, logs, repairs, restart",
    GROUP_DASHBOARD: "Lovelace dashboards",
    GROUP_SUPERVISOR: "Supervisor & add-ons",
    GROUP_MEDIA: "Camera snapshots & media browsing",
    GROUP_EVENTS: "Event bus (fire & listen)",
    GROUP_RAW: "Raw WebSocket API escape hatch",
}

DEFAULT_TOOL_GROUPS: Final = tuple(TOOL_GROUP_LABELS)

# Domains that are normally noise for an LLM client.
DEFAULT_EXCLUDED_DOMAINS: Final = ("tts", "stt", "conversation", "wake_word")
