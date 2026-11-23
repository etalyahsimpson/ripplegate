# Case study (independent portfolio work)

## Problem

Producer-side test suites stay green while response renames silently break downstream billing integrations. Code review rarely holds the full consumer surface in one head, and "looks safe to me" is not release evidence.

## What I built

I designed RippleGate as a release verification system around one principle: a compatibility verdict is only as strong as its weakest evidence layer, so keep the layers separate and make each one auditable.

- I implemented a bounded, deterministic OpenAPI 3.0/3.1 diff engine that records each structural change at an exact JSON pointer under a versioned rule set, with request-side and response-side compatibility handled as distinct directions.
- I implemented text-only PostgreSQL migration risk classification (DROP/RENAME/SET NOT NULL/ADD COLUMN/CREATE INDEX forms, with unsupported DDL reported as UNKNOWN rather than guessed).
- I built the consumer evidence on a registered dependency graph: producer edges are declared, impact mapping distinguishes affected from unaffected consumers, and missing coverage stays explicit.
- I implemented a controlled runner that executes the two pinned reference consumer suites with a fixed argument vector, bounded timeouts, and sanitized logs, so a BLOCK verdict carries an executed assertion rather than a heuristic.
- I implemented the deterministic policy (BLOCK/REVIEW/PASS/ERROR) with immutable evidence digests, a transactional run state machine, and idempotent worker stages safe to retry.
- I wired the whole gate into GitHub Actions, including an expected-negative check: CI asserts that the billing suite fails on a breaking candidate.

## Scenario (versioned evaluation case)

The reference producer `orders-api` renames `customer_id` to `account_id` in `GET /orders/{id}` 200 responses. RippleGate records `API-RESP-REQUIRED-REMOVED` (BREAKING, critical) at the exact JSON pointer; the impact mapper links the registered billing-service edge (required field `customer_id`); the controlled runner executes the real billing contract suite, which fails with exit 1; policy v1 emits BLOCK with the reasons and an evidence digest. The compatible control (optional response field added) yields a single ADDITIVE finding, both suites pass, and the outcome is PASS with its coverage caveat.

I verified both scenarios three ways: locally against PostgreSQL 16, in CI on the pushed SHA, and from a fresh clone of the public repository. Two controlled pull requests on GitHub show the same gate live: PR #1 fails the gate exactly as designed (the billing assertion), and PR #2 passes all checks.

## Reproduce

`bash scripts/demo-breaking.sh` and `bash scripts/demo-compatible.sh` (docs/REPRODUCE_BREAKAGE.md), or run the consumer suites directly:

```
cd examples/billing-service && node contract.test.js ../orders-api/openapi-candidate-breaking.json   # exit 1
```

## Insight

Static analysis alone would also have flagged the rename. The differentiator is executed consumer evidence attached to the exact finding, unknown coverage kept explicit instead of green-by-default, and a policy that fails closed on infrastructure errors. That combination is what makes a release decision reviewable rather than optimistic.
