# GitHub integration

Three evidence classes, never conflated:
1. **Actions (verified)**: `.github/workflows/ci.yml` runs on push to main and PRs; the run tied to the pushed SHA is the release-green signal.
2. **GitHub App Checks API (optional)**: `services/api/app/infra/github.py:create_check_run` requires an App token with checks:write. Without installation credentials the adapter raises `APP_MODE_UNCONFIGURED`; no check runs are fabricated.
3. **Webhooks**: `POST /api/v1/github/webhook` validates `X-Hub-Signature-256` HMAC on raw bytes (constant time), only `pull_request` events, only the allowlisted repo, dedupes by `X-GitHub-Delivery` (202 new, 200 duplicate, 401 bad signature, 403 wrong repo).

Controlled PR demonstration: branches `demo/breaking-change` and `demo/additive-change` carry candidate contracts; the CI `fixture-contracts` job asserts the breaking case fails billing (expected-negative detection) while the additive control passes.
