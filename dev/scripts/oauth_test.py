#!/usr/bin/env python3
"""Drive the full OAuth 2.1 flow end to end, as an MCP client would."""
import base64, hashlib, json, os, re, secrets, urllib.parse, urllib.request, http.cookiejar

BASE = os.environ.get("BASE", "http://localhost:8123").rstrip("/")
REDIRECT = "http://127.0.0.1:38999/oauth/callback"
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
         {"redirect_request": lambda *a, **k: None})())


def post(url, data, json_body=False):
    body = json.dumps(data).encode() if json_body else urllib.parse.urlencode(data).encode()
    headers = {"Content-Type": "application/json" if json_body else "application/x-www-form-urlencoded"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(req) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def get(url):
    try:
        with opener.open(urllib.request.Request(url)) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def step(n, label):
    print(f"\n[{n}] {label}")


# 1. Dynamic client registration
step(1, "Dynamic client registration (RFC 7591)")
status, body, _ = post(f"{BASE}/mcp_domora/oauth/register",
                       {"client_name": "OAuth Test Client", "redirect_uris": [REDIRECT],
                        "grant_types": ["authorization_code", "refresh_token"],
                        "token_endpoint_auth_method": "none"}, json_body=True)
print("   status:", status)
assert status == 201, f"Registration failed: {status} {body[:200]}"
client = json.loads(body)
client_id = client["client_id"]
print("   client_id:", client_id)

# 2. IndieAuth client document is served for it
step(2, "IndieAuth client identifier document")
status, body, _ = get(client_id)
print("   status:", status, "| advertises redirect_uri:", REDIRECT in body)
assert status == 200 and REDIRECT in body

# 3. Authorize with PKCE -> consent page
step(3, "Authorization request with PKCE")
verifier = secrets.token_urlsafe(64)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
params = urllib.parse.urlencode({
    "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
    "state": "client-state-abc", "code_challenge": challenge,
    "code_challenge_method": "S256", "scope": "homeassistant:read homeassistant:write"})
status, body, _ = get(f"{BASE}/mcp_domora/oauth/authorize?{params}")
print("   status:", status, "| consent page:", "Connect to Home Assistant" in body)
assert status == 200 and "Connect to Home Assistant" in body
consent = re.search(r'name="consent" value="([^"]+)"', body).group(1)

# 4. Approve consent -> redirect into Home Assistant's own login
step(4, "Approve consent")
status, body, headers = post(f"{BASE}/mcp_domora/oauth/authorize",
                             {"consent": consent, "action": "allow"})
location = headers.get("Location", "")
print("   status:", status)
print("   redirects to Home Assistant login:", "/auth/authorize" in location)
assert status == 302 and "/auth/authorize" in location
state_key = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)["state"][0]

# 5. Sign in to Home Assistant (what its login page does)
step(5, "Sign in to Home Assistant")
status, body, _ = post(f"{BASE}/auth/login_flow",
                       {"client_id": f"{BASE}/", "handler": ["homeassistant", None],
                        "redirect_uri": f"{BASE}/mcp_domora/oauth/callback",
                        "type": "authorize"}, json_body=True)
flow_id = json.loads(body)["flow_id"]
status, body, _ = post(f"{BASE}/auth/login_flow/{flow_id}",
                       {"client_id": f"{BASE}/", "username": "dev",
                        "password": "devpassword123"}, json_body=True)
ha_code = json.loads(body).get("result")
print("   got Home Assistant auth code:", bool(ha_code))
assert status == 200 and ha_code

# 6. Callback -> our authorization code
step(6, "Callback exchanges it and issues our code")
status, body, headers = get(
    f"{BASE}/mcp_domora/oauth/callback?code={ha_code}&state={state_key}")
location = headers.get("Location", "")
print("   status:", status)
if status != 302:
    print("   BODY:", body[:500]); raise SystemExit(1)
returned = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
print("   redirects to client:", location.startswith(REDIRECT))
print("   state preserved:", returned.get("state") == ["client-state-abc"])
assert location.startswith(REDIRECT) and returned.get("state") == ["client-state-abc"]
code = returned["code"][0]

# 7. Token exchange with the PKCE verifier
step(7, "Token exchange with PKCE verifier")
status, body, _ = post(f"{BASE}/mcp_domora/oauth/token",
                       {"grant_type": "authorization_code", "code": code,
                        "client_id": client_id, "redirect_uri": REDIRECT,
                        "code_verifier": verifier})
print("   status:", status)
tokens = json.loads(body)
assert status == 200 and tokens.get("access_token") and tokens.get("refresh_token")
print("   got access_token:", bool(tokens.get("access_token")),
      "| refresh_token:", bool(tokens.get("refresh_token")),
      "| expires_in:", tokens.get("expires_in"), "| scope:", tokens.get("scope"))

# 8. Code replay must be rejected (a wrong verifier is tested with fresh codes in pkce_test.py).
step(8, "Reusing an authorization code is rejected")
status, body, _ = post(f"{BASE}/mcp_domora/oauth/token",
                       {"grant_type": "authorization_code", "code": code,
                        "client_id": client_id, "redirect_uri": REDIRECT,
                        "code_verifier": "wrong-verifier"})
print("   status:", status, "| body:", body[:120])
assert status == 400 and json.loads(body).get("error") == "invalid_grant"

# 9. Use the token on the MCP endpoint
step(9, "Call the MCP endpoint with the issued token")
req = urllib.request.Request(
    f"{BASE}/mcp_domora/mcp",
    data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "oauth-test", "version": "1"}}}).encode(),
    headers={"Content-Type": "application/json",
             "Authorization": f"Bearer {tokens['access_token']}"}, method="POST")
with opener.open(req) as r:
    result = json.loads(r.read())
    print("   status:", r.status, "| server:",
          result["result"]["serverInfo"]["name"], "| session:", bool(r.headers.get("Mcp-Session-Id")))
    assert r.status == 200 and result["result"]["serverInfo"]["name"] == "mcp-domora"
    assert r.headers.get("Mcp-Session-Id")

# 10. Refresh token rotation
step(10, "Refresh the token")
status, body, _ = post(f"{BASE}/mcp_domora/oauth/token",
                       {"grant_type": "refresh_token",
                        "refresh_token": tokens["refresh_token"], "client_id": client_id})
print("   status:", status)
refreshed = json.loads(body)
assert status == 200 and refreshed.get("access_token") and refreshed.get("refresh_token")
print("   new access token differs:", refreshed.get("access_token") != tokens.get("access_token"))
print("   old refresh token rotated out:", refreshed.get("refresh_token") != tokens.get("refresh_token"))
assert refreshed["access_token"] != tokens["access_token"]
assert refreshed["refresh_token"] != tokens["refresh_token"]

# 11. Revocation
step(11, "Revoke the token")
status, _, _ = post(f"{BASE}/mcp_domora/oauth/revoke", {"token": refreshed["access_token"]})
print("   status:", status)
assert status == 200
req = urllib.request.Request(
    f"{BASE}/mcp_domora/mcp", data=b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}',
    headers={"Content-Type": "application/json",
             "Authorization": f"Bearer {refreshed['access_token']}"}, method="POST")
try:
    with opener.open(req) as r:
        raise AssertionError("Revoked token is still accepted")
except urllib.error.HTTPError as e:
    print("   revoked token now rejected with", e.code)
    assert e.code == 401
