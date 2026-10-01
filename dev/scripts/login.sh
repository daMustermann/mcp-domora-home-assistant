#!/usr/bin/env bash
# Log in to the dev Home Assistant and refresh dev/.token
set -euo pipefail
BASE="${BASE:-http://localhost:8123}"
CLIENT_ID="$BASE/"
DIR="$(dirname "$0")/.."

flow=$(curl -s -X POST "$BASE/auth/login_flow" -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$CLIENT_ID\",\"handler\":[\"homeassistant\",null],\"redirect_uri\":\"$CLIENT_ID\",\"type\":\"authorize\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["flow_id"])')

code=$(curl -s -X POST "$BASE/auth/login_flow/$flow" -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$CLIENT_ID\",\"username\":\"dev\",\"password\":\"devpassword123\"}" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("result",""))')

[ -n "$code" ] || { echo "login failed" >&2; exit 1; }

curl -s -X POST "$BASE/auth/token" -d "grant_type=authorization_code&code=$code&client_id=$CLIENT_ID" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);open("'"$DIR"'/.token","w").write(d["access_token"]);open("'"$DIR"'/.refresh","w").write(d["refresh_token"]);print("ok")'
