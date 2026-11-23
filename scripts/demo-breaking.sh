#!/usr/bin/env bash
# Run the controlled breaking-change demo against the running stack.
set -euo pipefail
API="${API_BASE_URL:-http://localhost:8000}"
TOKEN=$(curl -sf -X POST "$API/api/v1/demo/session" -H 'Content-Type: application/json' -d '{"account":"demo-admin"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
BODY=$(python3 - <<'PY'
import json, urllib.request
req = urllib.request.Request("http://localhost:8000/api/v1/projects/11111111-1111-4111-8111-111111111111/contracts")
print("placeholder")
PY
)
BODY='{"project_id":"11111111-1111-4111-8111-111111111111","producer_service_id":"22222222-2222-4222-8222-222222222222","base_contract_id":"'"$(curl -sf "$API/api/v1/projects/11111111-1111-4111-8111-111111111111/contracts" -H "Authorization: Bearer $TOKEN" | python3 -c 'import json,sys;items=json.load(sys.stdin)["items"];print([c["id"] for c in items if c["fixture_id"]=="fixture-base-v1"][0])')"'","candidate_contract_id":"'"$(curl -sf "$API/api/v1/projects/11111111-1111-4111-8111-111111111111/contracts" -H "Authorization: Bearer $TOKEN" | python3 -c 'import json,sys;items=json.load(sys.stdin)["items"];print([c["id"] for c in items if c["fixture_id"]=="fixture-candidate-breaking-v2"][0])')"'","migration_artifact_id":null,"policy_version":1,"registry_revision":1}'
RESP=$(curl -sf -X POST "$API/api/v1/analyses" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-breaking-script-0001' -d "$BODY")
RUN_ID=$(echo "$RESP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "run: $RUN_ID"
curl -sf "$API/api/v1/analyses/$RUN_ID" -H "Authorization: Bearer $TOKEN" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("state:",d["state"]);print("assessment:",d["assessment"]);print("findings:",d["finding_counts"])'
curl -sf "$API/api/v1/analyses/$RUN_ID/report?format=markdown" -H "Authorization: Bearer $TOKEN" | head -30
