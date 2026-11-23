# ADRs

1. **Deterministic rules, not LLM-only**: compatibility classification must be reproducible and auditable; an optional AI only rewords immutable evidence.
2. **Explicit dependency graph, not discovery**: a missing registration is UNKNOWN coverage, never "no consumers".
3. **Bounded SQL tokenizer, not a full parser**: honest PG-UNKNOWN beats silent misparse; migration SQL is never executed.
4. **Allowlisted controlled runner, not arbitrary code**: fixed argv, pinned suites, hardened Docker profile when available; never user commands/images.
5. **Actions check as the PR evidence path; App Checks opt-in**: a PAT cannot create App check runs; unconfigured is reported APP_MODE_UNCONFIGURED, not faked.
6. **Local Compose, not paid cloud**: no authorized host exists; PUBLIC_DEPLOYMENT_NOT_VERIFIED.
7. **Postgres authoritative; Redis queue-only**: verdicts survive queue loss.
