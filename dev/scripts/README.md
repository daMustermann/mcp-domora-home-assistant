# Development scripts

These scripts are for an **isolated Home Assistant test instance**, not a real
home. `regression.py` creates, modifies and deletes automations, scripts, scenes,
helpers and registry entries and calls services. `options.py STEP ...` modifies
the integration's options. OAuth tests register clients and create login sessions.

The supplied development setup uses Home Assistant at `http://localhost:8123`,
with a test user named `dev` and password `devpassword123`. For another isolated
test URL, set the `BASE` environment variable consistently for all scripts.
These default credentials are for throwaway test instances only.

| Script | Purpose | Prerequisites and limitations |
| --- | --- | --- |
| `onboard.sh` | Create the test user and write `dev/.token` | Only for a fresh instance. It does not write a refresh token. |
| `login.sh` | Log in as the test user and write `dev/.token` and `dev/.refresh` | Run after onboarding. |
| `mcp.py` | Initialize MCP; optionally call a tool with JSON arguments | Needs `dev/.refresh`. Refreshes the access token on first use. |
| `options.py` | Inspect or change the integration's options | Needs `dev/.refresh`; option changes reload the integration. |
| `oauth_test.py` | Exercise client registration, authorization, refresh and revocation | Requires the test user. Registers an OAuth client. |
| `pkce_test.py` | Check PKCE and redirect rejection cases | Requires the test user. Registers an OAuth client. |
| `sse_test.py` | Exercise legacy SSE initialization, listing and a template call | Needs `dev/.refresh`. |
| `regression.py` | Exercise read and write tool lifecycles | Needs `dev/.refresh`, the seeded `dev/config` setup, admin access and optional components. Requires explicit `--allow-write`. It is not a comprehensive automated test of every tool. |

The token files are ignored by Git. Do not commit them or reuse them for a real
Home Assistant installation. The shell scripts require Bash, curl and Python 3;
the Python scripts use the standard library. For example:

```bash
./dev/scripts/onboard.sh
./dev/scripts/login.sh
python3 dev/scripts/mcp.py get_system_info
python3 dev/scripts/oauth_test.py
python3 dev/scripts/pkce_test.py
python3 dev/scripts/sse_test.py
python3 dev/scripts/options.py show
python3 dev/scripts/regression.py --allow-write
```

The offline tests in `tests/` do not require Home Assistant:
`python -m unittest discover -s tests -v`.
