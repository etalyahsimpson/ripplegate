# Case study (independent portfolio work)

**Problem**: producer-side test suites stay green while response renames silently break downstream billing integrations; code review rarely holds the full consumer surface in one head.

**Scenario (synthetic)**: `orders-api` renames `customer_id` to `account_id` in `GET /orders/{id}` 200 responses.

**With RippleGate**: the diff engine records `API-RESP-REQUIRED-REMOVED` (BREAKING, critical) at the exact JSON pointer; the impact mapper links the registered billing-service edge (required field `customer_id`); the controlled runner executes the real billing contract suite, which fails with exit 1; policy v1 emits BLOCK with reasons and an evidence digest. The additive control (optional `fulfillment_note`) yields a single ADDITIVE finding, both suites pass, outcome PASS.

**Reproduce**: `bash scripts/demo-breaking.sh` and `bash scripts/demo-compatible.sh` (docs/REPRODUCE_BREAKAGE.md).

**Insight**: static analysis alone would also have flagged the rename; the differentiator is *executed consumer evidence* attached to the exact finding, and unknown coverage kept explicit instead of green-by-default.

This project was built independently as a portfolio engineering product. It has no customers, production deployment or employer affiliation; all data is synthetic.
