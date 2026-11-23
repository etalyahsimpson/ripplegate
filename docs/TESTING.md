# Testing

Commands (repo root):
- `RG_DATABASE_URL=... python3 -m pytest tests/python -q` (145 tests)
- `node examples/billing-service/contract.test.js ../orders-api/openapi-candidate-breaking.json` (exit 1 = correct detection)
- `npm --prefix apps/web run typecheck && npm --prefix apps/web run build`
- `bash scripts/verify-technology-lock.sh && bash scripts/verify-links.sh`

Expected-negative: the billing suite failing on the breaking candidate is asserted in CI as correct detection; CI itself stays green when detection works.

CI: `.github/workflows/ci.yml` (python-quality with real Postgres service, fixture-contracts, web-quality, source-policy).
