# Portfolio integration

- Repository: https://github.com/etalyahsimpson/ripplegate (public, main)
- One-line: evidence-led API compatibility and release-impact analysis (OpenAPI diff, PostgreSQL migration risk, registered consumer graph, isolated executed tests, deterministic BLOCK/REVIEW/PASS policy).
- Technologies actually shipped: Python 3.12/FastAPI/Pydantic/Celery/psycopg/PyYAML-safe, PostgreSQL 16 SQL migrations, Redis 7 queue, Next.js 15 App Router/React 19/TypeScript strict/Tailwind 4/TanStack Query, Node 22/Express consumer fixtures, Docker Compose, GitHub Actions, pytest (145) + real node consumer suites.
- Evidence: docs/EVIDENCE_INDEX.md; reproduction in docs/REPRODUCE_BREAKAGE.md.
- Media: assets/banner.svg (brand artwork), assets/overview.png (browser screenshot of the real running app - captured only after the app ran), assets/architecture.svg.
- Deployment status: LOCAL_RUN_VERIFIED (in-sandbox Postgres run), SOURCE_RELEASE on GitHub; PUBLIC_DEPLOYMENT_NOT_VERIFIED (no authorized host).
