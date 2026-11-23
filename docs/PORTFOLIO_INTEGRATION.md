# Portfolio integration

- Repository: https://github.com/etalyahsimpson/ripplegate (public, main)
- One-line: evidence-led API compatibility and release-impact analysis (OpenAPI diff, PostgreSQL migration risk, registered consumer graph, isolated executed tests, deterministic BLOCK/REVIEW/PASS policy).
- Technologies actually shipped: Python 3.12/FastAPI/Pydantic/Celery/psycopg/PyYAML-safe, PostgreSQL 16 SQL migrations, Redis 7 queue, Next.js 15 App Router/React 19/TypeScript strict/Tailwind 4/TanStack Query, Node 22/Express reference consumer fixtures, Docker Compose, GitHub Actions, pytest (145) plus real Node consumer suites.
- Evidence: docs/EVIDENCE_INDEX.md and docs/RELEASE_RECOVERY.md; reproduction in docs/REPRODUCE_BREAKAGE.md; controlled PR gate at PR #1 (breaking, correctly rejected) and PR #2 (compatible, green).
- Media: assets/banner.svg (brand artwork), assets/overview.png (screenshot captured from the running application), assets/architecture.svg.
- Deployment status: LOCAL_RUN_VERIFIED against PostgreSQL 16.4 in the build sandbox; CLEAN_CLONE_VERIFIED from the public repository; source release on GitHub with green exact-SHA CI; public hosted deployment not attempted in this environment (no authorized host).
