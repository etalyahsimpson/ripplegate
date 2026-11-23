# Reproduce the breakage

1. `docker compose up --build -d` (or run the stack locally per docs/DEPLOYMENT.md)
2. `bash scripts/bootstrap.sh`: registers the four immutable fixture contracts
3. `bash scripts/demo-breaking.sh` → expect `assessment: BLOCK`, findings `API-RESP-REQUIRED-REMOVED` (BREAKING, critical) at `/paths/~1orders~1{id}/get/responses/200/.../properties/customer_id`, billing suite FAILED (exit 1), reporting PASSED
4. `bash scripts/demo-compatible.sh` → expect `assessment: PASS`, single ADDITIVE finding
5. Direct consumer proof: `cd examples/billing-service && node contract.test.js ../orders-api/openapi-candidate-breaking.json` exits 1 with `FAIL: response contains customer_id as a non-empty string`.
6. Unknown path: register `openapi-candidate-external-ref.json` as candidate and analyze → REVIEW (never PASS).

Sanitized logs: `GET /api/v1/analyses/{run_id}/artifacts/{artifact_id}`. Reports: `GET /api/v1/analyses/{run_id}/report[?format=markdown]`.
