#!/usr/bin/env bash
# Onboard the dev Home Assistant and store an access token in dev/.token
set -euo pipefail
BASE="${BASE:-http://localhost:8123}"
CLIENT_ID="$BASE/"
OUT="$(dirname "$0")/../.token"

code=$(curl -s -X POST "$BASE/api/onboarding/users" \
  -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$CLIENT_ID\",\"name\":\"Dev Admin\",\"username\":\"dev\",\"password\":\"devpassword123\",\"language\":\"en\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("auth_code",""))')

if [ -z "$code" ]; then echo "onboarding failed (already onboarded?)" >&2; exit 1; fi

curl -s -X POST "$BASE/auth/token" \
  -d "grant_type=authorization_code&code=$code&client_id=$CLIENT_ID" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["access_token"])' > "$OUT"
echo "token written to $OUT"
