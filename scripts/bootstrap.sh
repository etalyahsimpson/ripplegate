#!/usr/bin/env bash
# Initialize the running stack: apply migrations, register demo contracts, seed data.
set -euo pipefail
API="${API_BASE_URL:-http://localhost:8000}"
cd "$(dirname "$0")/.."
TOKEN=$(curl -sf -X POST "$API/api/v1/demo/session" -H 'Content-Type: application/json' -d '{"account":"demo-admin"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
PROJ="11111111-1111-4111-8111-111111111111"
SVC="22222222-2222-4222-8222-222222222222"
for pair in "fixture-base-v1:openapi-base.json" "fixture-candidate-breaking-v2:openapi-candidate-breaking.json" "fixture-candidate-additive-v2:openapi-candidate-additive.json" "fixture-candidate-external-ref-v1:openapi-candidate-external-ref.json"; do
  FID="${pair%%:*}"; FILE="${pair##*:}"
  DOC=$(python3 -c "import json,sys;print(json.dumps({'service_id':'$SVC','source_type':'FIXTURE','fixture_id':'$FID','format':'json','document':open('examples/orders-api/$FILE').read()}))")
  CODE=$(curl -s -o /tmp/rg-req.json -w '%{http_code}' -X POST "$API/api/v1/projects/$PROJ/contracts" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$DOC")
  if [ "$CODE" = "201" ] || [ "$CODE" = "409" ]; then echo "contract $FID: $CODE"; else echo "contract $FID FAILED ($CODE)"; cat /tmp/rg-req.json; exit 1; fi
done
echo "bootstrap complete"
