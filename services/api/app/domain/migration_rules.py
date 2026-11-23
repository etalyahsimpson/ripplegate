"""Map bounded SQL migration analysis to versioned PG-* rule findings (spec 5.3)."""
from __future__ import annotations

from typing import Any

from app.parsing.sql_migration import MigrationAnalysis
from .findings import Finding

PG_RULE_VERSION = "1.0.0"


def migration_findings(analysis: MigrationAnalysis) -> list[Finding]:
    out: list[Finding] = []
    for table, column in analysis.drop_columns:
        out.append(Finding(
            rule_id="PG-DROP-COLUMN", rule_version=PG_RULE_VERSION,
            surface="DB_MIGRATION", location=f"ALTER TABLE {table} DROP COLUMN {column}",
            before_value={"table": table, "column": column},
            after_value=None,
            classification="BREAKING", severity="critical",
            reason=f"dropping column {table}.{column} removes data actively read by any "
                   "existing consumer; this is high-risk migration evidence",
        ))
    for table, old, new in analysis.renamed_columns:
        out.append(Finding(
            rule_id="PG-RENAME-COLUMN", rule_version=PG_RULE_VERSION,
            surface="DB_MIGRATION", location=f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}",
            before_value={"table": table, "column": old},
            after_value={"table": table, "column": new},
            classification="POTENTIALLY_BREAKING", severity="high",
            reason=f"renaming {table}.{old} to {new} without an expand/contract plan breaks "
                   "readers of the old name; known consumers elevate this to BREAKING",
        ))
    for table, column in analysis.set_not_null:
        out.append(Finding(
            rule_id="PG-SET-NOT-NULL", rule_version=PG_RULE_VERSION,
            surface="DB_MIGRATION",
            location=f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL",
            before_value={"table": table, "column": column, "nullable": True},
            after_value={"table": table, "column": column, "nullable": False},
            classification="POTENTIALLY_BREAKING", severity="medium",
            reason=f"tightening {table}.{column} to NOT NULL without a proven backfill "
                   "rejects previously legal writes",
        ))
    for table, column, not_null in analysis.added_columns:
        if not_null:
            out.append(Finding(
                rule_id="PG-ADD-NOT-NULL", rule_version=PG_RULE_VERSION,
                surface="DB_MIGRATION",
                location=f"ALTER TABLE {table} ADD COLUMN {column}",
                before_value=None,
                after_value={"table": table, "column": column, "not_null": True},
                classification="POTENTIALLY_BREAKING", severity="medium",
                reason=f"adding NOT NULL column {table}.{column} without DEFAULT requires a "
                       "table rewrite and fails on existing rows",
            ))
        else:
            out.append(Finding(
                rule_id="PG-ADD-NULLABLE", rule_version=PG_RULE_VERSION,
                surface="DB_MIGRATION",
                location=f"ALTER TABLE {table} ADD COLUMN {column}",
                before_value=None,
                after_value={"table": table, "column": column, "not_null": False},
                classification="INFORMATIONAL", severity="low",
                reason=f"adding nullable column {table}.{column} is lower-risk; readers that "
                       "SELECT * and map by name can still be surprised",
            ))
    for index in analysis.added_indexes:
        out.append(Finding(
            rule_id="PG-ADD-INDEX", rule_version=PG_RULE_VERSION,
            surface="DB_MIGRATION", location=f"CREATE INDEX {index}",
            before_value=None, after_value={"index": index},
            classification="ADDITIVE", severity="info",
            reason="additive index creation in its supported plain form",
        ))
    for offset, reason in analysis.unknowns:
        out.append(Finding(
            rule_id="PG-UNKNOWN", rule_version=PG_RULE_VERSION,
            surface="DB_MIGRATION", location=f"statement@offset:{offset}",
            before_value=None, after_value=None,
            classification="UNKNOWN", severity="medium",
            reason=f"{reason}; RippleGate's parser subset does not cover it, so it is "
                   "reported as unknown rather than assumed safe",
        ))
    return out
