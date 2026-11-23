# Compatibility rules (v1.0.0)

All rules live in `services/api/app/domain/rules.py` (API) and `migration_rules.py` (SQL); the frontend renders results and never re-classifies.

| Rule | Trigger | Classification |
|---|---|---|
| API-PATH-REMOVED | endpoint/method removed | BREAKING (critical) |
| API-REQ-REQUIRED-ADDED | request param/property becomes required | BREAKING |
| API-REQ-ENUM-REMOVED | accepted request enum value removed | BREAKING |
| API-RESP-REQUIRED-REMOVED | required response field removed | BREAKING (critical) |
| API-RESP-TYPE-CHANGED | response type incompatible | BREAKING |
| API-RESP-ENUM-EXPANDED | new possible response value | POTENTIALLY_BREAKING |
| API-RESP-OPTIONAL-ADDED | new response property (incl. required: still data added) | ADDITIVE + strict caveat |
| API-REQUEST-NEW-OPTIONAL | new optional request property | ADDITIVE |
| API-STATUS-CHANGED | response schema added/removed | POTENTIALLY_BREAKING |
| API-REF-UNSUPPORTED | external/cyclic/unsupported construct | UNKNOWN (fail closed) |
| PG-DROP-COLUMN / PG-RENAME-COLUMN / PG-SET-NOT-NULL / PG-ADD-NOT-NULL | see migration parser | BREAKING / POTENTIALLY_BREAKING |
| PG-ADD-NULLABLE / PG-ADD-INDEX | additive | INFORMATIONAL / ADDITIVE |
| PG-UNKNOWN | unsupported DDL, dynamic SQL | UNKNOWN |

Directionality: request-side and response-side compatibility differ (a producer emitting an extra field is additive statically, yet a strict consumer test can still BLOCK). Dialects: OpenAPI 3.0 `nullable` and 3.1 `type:[T,"null"]` normalize to the same internal representation (`tests/python/test_openapi_dialects.py`).

Version changes to rules require a new rule_version string; stored findings keep the version they were produced under.
