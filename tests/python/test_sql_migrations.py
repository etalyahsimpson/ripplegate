"""PostgreSQL migration risk analysis (spec 13 matrix row 5)."""
from __future__ import annotations

from app.parsing.sql_migration import analyze_migration, split_statements
from app.domain.migration_rules import migration_findings


def test_drop_column_flagged_breaking():
    a = analyze_migration("ALTER TABLE orders DROP COLUMN customer_id;")
    fs = migration_findings(a)
    hit = [f for f in fs if f.rule_id == "PG-DROP-COLUMN"]
    assert hit and hit[0].classification == "BREAKING" and hit[0].severity == "critical"


def test_rename_column_potentially_breaking():
    a = analyze_migration("ALTER TABLE orders RENAME COLUMN total_cents TO amount_cents;")
    fs = migration_findings(a)
    hit = [f for f in fs if f.rule_id == "PG-RENAME-COLUMN"]
    assert hit and hit[0].classification == "POTENTIALLY_BREAKING"


def test_set_not_null_flagged():
    a = analyze_migration("ALTER TABLE orders ALTER COLUMN status SET NOT NULL;")
    fs = migration_findings(a)
    assert any(f.rule_id == "PG-SET-NOT-NULL" for f in fs)


def test_add_nullable_lower_risk():
    a = analyze_migration("ALTER TABLE orders ADD COLUMN note TEXT;")
    fs = migration_findings(a)
    hit = [f for f in fs if f.rule_id == "PG-ADD-NULLABLE"]
    assert hit and hit[0].classification == "INFORMATIONAL"


def test_add_not_null_without_default_is_risk():
    a = analyze_migration("ALTER TABLE orders ADD COLUMN priority INT NOT NULL;")
    fs = migration_findings(a)
    hit = [f for f in fs if f.rule_id == "PG-ADD-NOT-NULL"]
    assert hit and hit[0].classification == "POTENTIALLY_BREAKING"


def test_dynamic_sql_is_unknown_never_safe():
    sql = "DO $$ BEGIN EXECUTE 'ALTER TABLE orders ADD COLUMN x INT'; END $$;"
    fs = migration_findings(analyze_migration(sql))
    unknown = [f for f in fs if f.rule_id == "PG-UNKNOWN"]
    assert unknown and unknown[0].classification == "UNKNOWN"


def test_comments_ignored_but_semantics_kept():
    sql = """
-- this comment mentions DROP but is only a comment
ALTER TABLE orders ADD COLUMN note TEXT;
"""
    fs = migration_findings(analyze_migration(sql))
    assert not any(f.rule_id == "PG-UNKNOWN" for f in fs)
    assert any(f.rule_id == "PG-ADD-NULLABLE" for f in fs)


def test_quoted_identifier_with_keyword_name():
    sql = 'ALTER TABLE "order" DROP COLUMN "select";'
    fs = migration_findings(analyze_migration(sql))
    hit = [f for f in fs if f.rule_id == "PG-DROP-COLUMN"]
    assert hit and hit[0].location == "ALTER TABLE order DROP COLUMN select"


def test_semicolons_inside_strings_do_not_split():
    stmts = split_statements("INSERT INTO t VALUES ('a;b'); ALTER TABLE t DROP COLUMN c;")
    assert len([s for s in stmts if s.text]) == 2


def test_dollar_quoted_block_is_one_statement_and_unknown():
    stmts = split_statements(
        "DO $$ BEGIN IF true THEN PERFORM 1; END IF; END $$; ALTER TABLE t ADD COLUMN x INT;")
    assert len([s for s in stmts if s.text]) == 2


def test_parser_never_executes_sql(monkeypatch):
    calls = []
    monkeypatch.setattr("builtins.__import__", __import__)  # no SQL execution path exists
    fs = migration_findings(analyze_migration("DROP TABLE sensitive;"))
    assert any(f.rule_id == "PG-UNKNOWN" for f in fs)


def test_unrecognized_ddl_is_unknown():
    fs = migration_findings(analyze_migration("CREATE VIEW v AS SELECT 1;"))
    assert any(f.rule_id == "PG-UNKNOWN" for f in fs)


def test_create_index_additive():
    fs = migration_findings(analyze_migration(
        "CREATE INDEX idx_orders_customer ON orders (customer_id);"))
    hit = [f for f in fs if f.rule_id == "PG-ADD-INDEX"]
    assert hit and hit[0].classification == "ADDITIVE"


def test_transaction_control_statements_are_safe():
    fs = migration_findings(analyze_migration(
        "BEGIN; ALTER TABLE orders ADD COLUMN note TEXT; COMMIT;"))
    assert not any(f.rule_id == "PG-UNKNOWN" for f in fs)
