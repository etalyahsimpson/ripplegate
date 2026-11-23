# Deployment (local, reproducible)

Prereqs: Docker + Compose (or: Python 3.12, Node 22, Postgres 16, Redis 7).

1. `cp .env.example .env` and set `SESSION_SIGNING_SECRET`, `WEBHOOK_SECRET` (generate e.g. `LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48`).
2. `docker compose up --build -d`
3. `bash scripts/bootstrap.sh` then `bash scripts/demo-breaking.sh && bash scripts/demo-compatible.sh`
4. Health: `curl localhost:8000/api/v1/health` and `/api/v1/ready` (503 when DB down).

Rollback/restore: Postgres named volume `pgdata`; stop with `docker compose down` (keep volume) or `-v` for full reset. Synthetic data only, so restore = re-run migrations + bootstrap.

Container hygiene: pinned image tags (postgres:16-bookworm, redis:7-bookworm), non-root users, health checks, migrations applied by the API bootstrap path, no Docker socket in any app container. Cloud: PUBLIC_DEPLOYMENT_NOT_VERIFIED (no authorized host).
