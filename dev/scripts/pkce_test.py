#!/usr/bin/env python3
"""Verify PKCE rejection and redirect_uri validation with fresh codes."""
import base64, hashlib, json, os, re, secrets, urllib.parse, urllib.request, http.cookiejar

BASE = os.environ.get("BASE", "http://localhost:8123").rstrip("/")
REDIRECT = "http://127.0.0.1:38999/oauth/callback"
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
         {"redirect_request": lambda *a, **k: None})())


def req(url, data=None, json_body=False):
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode() if json_body else urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/json" if json_body else "application/x-www-form-urlencoded"
    r = urllib.request.Request(url, data=body, headers=headers,
                               method="POST" if data is not None else "GET")
    try:
        with opener.open(r) as resp:
            return resp.status, resp.read().decode(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def register():
    _, body, _ = req(f"{BASE}/mcp_domora/oauth/register",
                     {"client_name": "PKCE Test", "redirect_uris": [REDIRECT],
                      "token_endpoint_auth_method": "none"}, json_body=True)
    return json.loads(body)["client_id"]


def fresh_code(client_id, challenge):
    """Run the flow up to an unused authorization code."""
    params = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "state": "s", "code_challenge": challenge, "code_challenge_method": "S256"})
    _, body, _ = req(f"{BASE}/mcp_domora/oauth/authorize?{params}")
    consent = re.search(r'name="consent" value="([^"]+)"', body).group(1)
    _, _, headers = req(f"{BASE}/mcp_domora/oauth/authorize",
                        {"consent": consent, "action": "allow"})
    state_key = urllib.parse.parse_qs(
        urllib.parse.urlparse(headers["Location"]).query)["state"][0]
    _, body, _ = req(f"{BASE}/auth/login_flow",
                     {"client_id": f"{BASE}/", "handler": ["homeassistant", None],
                      "redirect_uri": f"{BASE}/mcp_domora/oauth/callback",
                      "type": "authorize"}, json_body=True)
    flow = json.loads(body)["flow_id"]
    _, body, _ = req(f"{BASE}/auth/login_flow/{flow}",
                     {"client_id": f"{BASE}/", "username": "dev",
                      "password": "devpassword123"}, json_body=True)
    ha_code = json.loads(body)["result"]
    _, _, headers = req(f"{BASE}/mcp_domora/oauth/callback?code={ha_code}&state={state_key}")
    return urllib.parse.parse_qs(urllib.parse.urlparse(headers["Location"]).query)["code"][0]


client_id = register()
verifier = secrets.token_urlsafe(64)
challenge = base64.urlsafe_b64encode(
    hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

print("[A] fresh code + WRONG verifier")
code = fresh_code(client_id, challenge)
status, body, _ = req(f"{BASE}/mcp_domora/oauth/token",
                      {"grant_type": "authorization_code", "code": code,
                       "client_id": client_id, "redirect_uri": REDIRECT,
                       "code_verifier": secrets.token_urlsafe(64)})
print("   ", status, body[:130])
assert status == 400 and json.loads(body).get("error") == "invalid_grant"

print("[B] fresh code + NO verifier")
code = fresh_code(client_id, challenge)
status, body, _ = req(f"{BASE}/mcp_domora/oauth/token",
                      {"grant_type": "authorization_code", "code": code,
                       "client_id": client_id, "redirect_uri": REDIRECT})
print("   ", status, body[:130])
assert status == 400 and json.loads(body).get("error") == "invalid_grant"

print("[C] fresh code + mismatched redirect_uri")
code = fresh_code(client_id, challenge)
status, body, _ = req(f"{BASE}/mcp_domora/oauth/token",
                      {"grant_type": "authorization_code", "code": code,
                       "client_id": client_id, "redirect_uri": "http://evil.example/cb",
                       "code_verifier": verifier})
print("   ", status, body[:130])
assert status == 400 and json.loads(body).get("error") == "invalid_grant"

print("[D] fresh code + correct verifier (control)")
code = fresh_code(client_id, challenge)
status, body, _ = req(f"{BASE}/mcp_domora/oauth/token",
                      {"grant_type": "authorization_code", "code": code,
                       "client_id": client_id, "redirect_uri": REDIRECT,
                       "code_verifier": verifier})
print("   ", status, "access_token issued:", bool(json.loads(body).get("access_token")))
assert status == 200 and json.loads(body).get("access_token")

print("[E] authorize with an unregistered redirect_uri")
params = urllib.parse.urlencode({
    "response_type": "code", "client_id": client_id,
    "redirect_uri": "http://evil.example/cb", "state": "s",
    "code_challenge": challenge, "code_challenge_method": "S256"})
status, body, _ = req(f"{BASE}/mcp_domora/oauth/authorize?{params}")
print("   ", status, "refused:", "not registered" in body)
assert status == 400 and "not registered" in body

print("[F] authorize without PKCE")
params = urllib.parse.urlencode({
    "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "s"})
status, body, _ = req(f"{BASE}/mcp_domora/oauth/authorize?{params}")
print("   ", status, body[:130])
assert status == 400 and json.loads(body).get("error") == "invalid_request"

print("[G] unknown client_id that is not a URL")
params = urllib.parse.urlencode({
    "response_type": "code", "client_id": "just-a-name", "redirect_uri": REDIRECT,
    "state": "s", "code_challenge": challenge, "code_challenge_method": "S256"})
status, body, _ = req(f"{BASE}/mcp_domora/oauth/authorize?{params}")
print("   ", status, "refused:", "Unknown client_id" in body)
assert status == 400 and "Unknown client_id" in body
