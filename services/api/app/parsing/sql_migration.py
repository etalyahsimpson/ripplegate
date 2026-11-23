"""Bounded PostgreSQL migration SQL tokenizer (analysis only, never execution).

Reads migration SQL as TEXT and extracts ALTER TABLE statements for
DROP COLUMN / RENAME COLUMN / SET NOT NULL / ADD COLUMN and additive CREATE
INDEX in their supported forms. Unknown constructs (DO blocks, EXECUTE,
function calls, dynamic SQL, PL/pgSQL, unsupported DDL) are returned as
PG-UNKNOWN findings by the rule engine, never assumed safe.

Deliberately NOT a full SQL parser; deliberately never connected to the
analysis database (spec 5.3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_SQL_BYTES = 262_144  # 256 KiB per migration text


class MigrationParseLimit(ValueError):
    pass


@dataclass
class SqlStatement:
    offset: int
    text: str


@dataclass
class MigrationAnalysis:
    statements: list[SqlStatement]
    drop_columns: list[tuple[str, str]]          # (table, column)
    renamed_columns: list[tuple[str, str, str]]  # (table, old, new)
    set_not_null: list[tuple[str, str]]          # (table, column)
    added_columns: list[tuple[str, str, bool]]   # (table, column, not_null)
    added_indexes: list[str]                    # index names (additive)
    unknowns: list[tuple[int, str]]              # (offset, reason)


_IDENT = r'"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*'

# strip comments but keep offsets honest by replacing them with spaces
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

_DROP_COLUMN = re.compile(
    rf"ALTER\s+TABLE\s+(?:ONLY\s+)?({_IDENT})\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?({_IDENT})",
    re.IGNORECASE,
)
_RENAME_COLUMN = re.compile(
    rf"ALTER\s+TABLE\s+(?:ONLY\s+)?({_IDENT})\s+RENAME\s+COLUMN\s+({_IDENT})\s+TO\s+({_IDENT})",
    re.IGNORECASE,
)
_SET_NOT_NULL = re.compile(
    rf"ALTER\s+TABLE\s+(?:ONLY\s+)?({_IDENT})\s+ALTER\s+COLUMN\s+({_IDENT})\s+SET\s+NOT\s+NULL",
    re.IGNORECASE,
)
_ADD_COLUMN = re.compile(
    rf"ALTER\s+TABLE\s+(?:ONLY\s+)?({_IDENT})\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?({_IDENT})\s+([^\n;]+)",
    re.IGNORECASE,
)
_CREATE_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"({_IDENT})\s+ON\s+({_IDENT})",
    re.IGNORECASE,
)
_KNOWN_SAFE = re.compile(
    r"^\s*(BEGIN|COMMIT|START\s+TRANSACTION|ROLLBACK|SET)\b",
    re.IGNORECASE,
)
_KNOWN_DDL = re.compile(
    r"^\s*(ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+)?INDEX|CREATE\s+TABLE|DROP\s+TABLE|"
    r"TRUNCATE|COMMENT\s+ON|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
_UNKNOWN_TRIGGERS = re.compile(
    r"\b(DO|EXECUTE|CREATE\s+FUNCTION|CREATE\s+PROCEDURE|CALL|PERFORM|"
    r"CREATE\s+TRIGGER|CREATE\s+RULE|CREATE\s+VIEW|CREATE\s+EXTENSION|"
    r"SECURITY\s+LABEL|COPY|LOCK)\b",
    re.IGNORECASE,
)


def _strip_comments(sql: str) -> str:
    """Replace comments with equivalent whitespace so offsets stay aligned."""
    def blank(m: re.Match[str]) -> str:
        return " " * len(m.group(0))
    sql = _BLOCK_COMMENT.sub(blank, sql)
    sql = _LINE_COMMENT.sub(blank, sql)
    return sql


def split_statements(sql: str) -> list[SqlStatement]:
    """Split on semicolons outside single/double-quoted strings (dollar-quoted
    bodies are treated as unknown because they usually wrap PL/pgSQL)."""
    if len(sql.encode("utf-8")) > MAX_SQL_BYTES:
        raise MigrationParseLimit(f"migration text exceeds {MAX_SQL_BYTES} bytes")
    statements: list[SqlStatement] = []
    start = 0
    i = 0
    n = len(sql)
    in_single = in_double = False
    while i < n:
        ch = sql[i]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "$" and not in_single and not in_double:
            # possible dollar-quote start: treat as opaque until matching $tag$
            m = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[i:])
            if m:
                tag = m.group(0)
                end = sql.find(tag, i + len(tag))
                if end == -1:
                    raise MigrationParseLimit("unterminated dollar-quoted string")
                i = end + len(tag)
                statements.append(SqlStatement(offset=start, text=sql[start:i]))
                if i < n and sql[i] == ";":
                    i += 1
                start = i
                continue
        elif ch == ";" and not in_single and not in_double:
            stmt = sql[start:i].strip()
            if stmt:
                statements.append(SqlStatement(offset=start, text=stmt))
            start = i + 1
        i += 1
    tail = sql[start:].strip()
    if tail:
        statements.append(SqlStatement(offset=start, text=tail))
    return statements


def analyze_migration(sql: str) -> MigrationAnalysis:
    """Analyze migration text. NEVER executes anything. Unknown constructs are
    recorded as unknowns; callers turn them into PG-UNKNOWN findings."""
    stripped = _strip_comments(sql)
    analysis = MigrationAnalysis(
        statements=[], drop_columns=[], renamed_columns=[], set_not_null=[],
        added_columns=[], added_indexes=[], unknowns=[],
    )
    for stmt in split_statements(stripped):
        analysis.statements.append(stmt)
        text = " ".join(stmt.text.split())  # normalize internal whitespace
        if _UNKNOWN_TRIGGERS.search(text):
            analysis.unknowns.append((stmt.offset, "unsupported construct (dynamic SQL / functions / procedural block)"))
            continue
        if _KNOWN_SAFE.match(text):
            continue
        m = _DROP_COLUMN.search(text)
        if m:
            analysis.drop_columns.append((_unquote(m.group(1)), _unquote(m.group(2))))
            continue
        m = _RENAME_COLUMN.search(text)
        if m:
            analysis.renamed_columns.append((_unquote(m.group(1)), _unquote(m.group(2)), _unquote(m.group(3))))
            continue
        m = _SET_NOT_NULL.search(text)
        if m:
            analysis.set_not_null.append((_unquote(m.group(1)), _unquote(m.group(2))))
            continue
        m = _ADD_COLUMN.search(text)
        if m:
            coldef = m.group(3).strip()
            not_null = bool(re.search(r"NOT\s+NULL", coldef, re.IGNORECASE))
            analysis.added_columns.append((_unquote(m.group(1)), _unquote(m.group(2)), not_null))
            continue
        m = _CREATE_INDEX.search(text)
        if m:
            analysis.added_indexes.append(_unquote(m.group(1)))
            continue
        if _KNOWN_DDL.match(text):
            analysis.unknowns.append((stmt.offset, "supported DDL family but unsupported exact form"))
            continue
        analysis.unknowns.append((stmt.offset, "unrecognized statement"))
    return analysis


def _unquote(ident: str) -> str:
    if ident.startswith('"') and ident.endswith('"'):
        return ident[1:-1].replace('""', '"')
    return ident.lower()
