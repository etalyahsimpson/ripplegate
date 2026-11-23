#!/usr/bin/env bash
# Clean-clone smoke: from a fresh clone, run the deterministic local verification.
# (In this sandbox without Docker, the script degrades honestly: it runs the
# full Python suite against a local Postgres and the consumer fixtures, and
# prints LOCAL_COMPOSE_NOT_RUN when Docker is absent.)
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== python tests =="
python3 -m pytest tests/python -q
echo "== consumer fixtures =="
(cd examples/billing-service && node contract.test.js ../orders-api/openapi-candidate-breaking.json && exit 1 || true)
(cd examples/billing-service && node contract.test.js ../orders-api/openapi-candidate-additive.json)
(cd examples/reporting-service && node contract.test.js ../orders-api/openapi-candidate-additive.json)
echo "== technology lock =="
bash scripts/verify-technology-lock.sh
bash scripts/verify-links.sh
if command -v docker >/dev/null 2>&1; then
  echo "== compose =="
  docker compose up --build -d
  bash scripts/bootstrap.sh
  bash scripts/demo-breaking.sh
  bash scripts/demo-compatible.sh
  docker compose down -v
else
  echo "LOCAL_COMPOSE_NOT_RUN: docker unavailable in this environment"
fi
echo "clean-clone verification complete"
