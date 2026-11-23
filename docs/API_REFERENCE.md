# API reference (see live /openapi.json for the machine-readable contract)

All routes under `/api/v1`, JSON in/out, bearer demo session except `health`, `ready`, `demo/session`, `github/webhook`. Error envelope: `{"error": {"code","message","request_id","details"}}`.

Key routes (full behavior in `services/api/app/main.py`):
- `GET /health`, `GET /ready` (200/503)
- `POST /demo/session` (allowlisted accounts only)
- `GET /projects`, `POST /projects` (201/409/422/403)
- `POST /projects/{id}/services|contracts|dependencies|policies`
- `GET /projects/{id}/graph` (nodes/edges + coverage caveat)
- `POST /analyses` with `Idempotency-Key` (202 new; 200 replay; 409 conflict)
- `GET /analyses/{id}`, `/findings`, `/tests`, `/report[?format=markdown]`, `/artifacts/{artifact_id}`
- `POST /analyses/{id}/reviews` (201/409; human disposition separate from engine verdict)
- `POST /analyses/{id}/summary-draft` (200 template; 503 provider unreachable; never mutates)
- `POST /github/webhook` (202/200/400/401/403/413)

Example (observed): `POST /api/v1/analyses {"project_id":"11111111-…","base_contract_id":"…","candidate_contract_id":"…","policy_version":1,"registry_revision":1}` → `202 {"id":"…","state":"COMPLETED","links":{…}}` and the report shows `assessment: "BLOCK"` with `API-RESP-REQUIRED-REMOVED … verification_state: "CONSUMER_FAIL"`.
