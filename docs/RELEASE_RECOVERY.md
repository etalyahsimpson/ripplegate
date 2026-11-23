# Release recovery log

Durable ledger of the CI recovery, pull-request verification, clean-clone
verification and editorial pass. Each entry records the observed evidence at
the time it was collected. No credentials are stored here.

## Timeline

| # | Event | Evidence |
|---|---|---|
| 1 | Initial push `5b6ae95` produced Actions run 45227009824, conclusion failure, zero jobs spawned | Run metadata: `head_sha 5b6ae95…`, `total_count: 0` jobs |
| 2 | Root cause identified: workflow-level YAML parse failure. The step name `Expected-negative: billing FAILS…` contained an unquoted colon, invalid in YAML flow context, so the workflow never validated and no runner started | Local `yaml.safe_load` reproduced `mapping values are not allowed here` at line 53 |
| 3 | Fixed the step name and the invalid first line of `.gitattributes` (prose before `#` is not an attribute declaration); pushed `a3ed4af` | Commit `a3ed4af`; run 45230741105 spawned all four real jobs |
| 4 | Run 45230741105 failed in `python-quality`: consumer suites returned MODULE_NOT_FOUND for express under the Docker one-shot profile | Job log 137889269135: `Cannot find module 'express'` |
| 5 | Added the suite and producer mounts; pushed `973f95d`; run 45231098832 failed: Docker refused creating `/suite/producer` under a read-only bind | Job log: `read-only file system` |
| 6 | Moved producer to a distinct `/producer` mount; pushed `d56ca55`; run 45231459329 failed: producer's own `require('express')` unresolved (no deps mount in `python-quality`, which also executes the suites) | Job log: `MODULE_NOT_FOUND … /producer/server.js` |
| 7 | Mounted locked consumer dependencies at a shared read-only `/deps` with `NODE_PATH=/deps`, and made `python-quality` install fixture dependencies; pushed `582b83d` | Commit `582b83d` |
| 8 | CI green: run 45232538859 on `582b83d` concluded success with all four jobs passing (python-quality, fixture-contracts, web-quality, source-policy) | https://github.com/etalyahsimpson/ripplegate/actions/runs/45232538859 |
| 9 | Controlled breaking PR #1 (`demo/breaking-change`, head `20998c5`): policy gate correctly rejected the change; billing suite failed with `FAIL: response contains customer_id as a non-empty string (got undefined)`; documented as an intended validation result and closed without merging | https://github.com/etalyahsimpson/ripplegate/pull/1 |
| 10 | Controlled additive PR #2 (`demo/additive-change`, head `d0c040a`): all four checks pass; both consumer suites green | https://github.com/etalyahsimpson/ripplegate/pull/2 |
| 11 | Clean clone of the public repository at `582b83d`: 145 pytest tests passed; breaking scenario produced `BLOCK` with billing FAILED / reporting PASSED; additive scenario produced `PASS` with both suites PASSED; API `/health` and `/ready` green; web dashboard rendered live outcomes; fresh screenshot captured | Local run against PostgreSQL 16.4 |
| 12 | Editorial pass: authored em dashes removed from prose and UI strings; README restructured with verified links; DATA_PROVENANCE.md added; terminology normalized | `grep` scans return zero U+2014 in authored Markdown and UI sources |

## Current state

- `main` at `582b83d…` with green CI (run 45232538859).
- Docker Compose path: `NOT RUN: Docker unavailable` in the build sandbox; the
  clean-clone verification ran the stack directly on Python/Node with
  PostgreSQL. The Compose files remain the documented deployment path where a
  Docker daemon exists.
- Public hosted deployment: not attempted; no authorized host or billing
  approval exists in this environment.
