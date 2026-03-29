"""
FloatChat NL Query Engine — SQL Executor

Safe SQL execution on the readonly database session.
Always uses the session from get_readonly_db() — never creates its own
engine (Hard Rule 2).

Original SQL is never modified after validation (Hard Rule 8).
LIMIT is applied by wrapping the original SQL as a subquery.
"""

from dataclasses import dataclass, field
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger(__name__)


@dataclass
class ExecutionResult:
    """Result of SQL execution."""
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False   # True if results were limited
    error: Optional[str] = None


def execute_sql(
    sql: str,
    db: Session,
    max_rows: int = 1000,
) -> ExecutionResult:
    """
    Execute validated SQL on the readonly session.

    The original SQL is never modified (Hard Rule 8).  If the SQL does not
    already contain a LIMIT clause, a wrapping subquery is used to cap
    the result set.

    Parameters
    ----------
    sql : str
        Validated SQL string (must have passed all 3 validation checks).
    db : Session
        A readonly SQLAlchemy session from get_readonly_db().
    max_rows : int
        Maximum rows to return.  Default 1000.

    Returns
    -------
    ExecutionResult
    """
    try:
        # Wrap with LIMIT if not already present (Hard Rule 8 — don't modify original)
        effective_sql = _apply_limit(sql, max_rows)

        result = db.execute(text(effective_sql))

        columns = list(result.keys())
        raw_rows = result.fetchall()

        # Determine if we truncated
        # If the original SQL had no LIMIT and we hit max_rows, it's truncated
        truncated = len(raw_rows) >= max_rows and not _has_limit(sql)

        rows = [dict(zip(columns, row)) for row in raw_rows]

        log.info(
            "sql_executed",
            row_count=len(rows),
            column_count=len(columns),
            truncated=truncated,
        )

        return ExecutionResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )

    except Exception as exc:
        log.error("sql_execution_failed", error=str(exc))
        return ExecutionResult(error=f"Execution error: {exc}")


def estimate_rows(sql: str, db: Session) -> Optional[int]:
    """
    Run EXPLAIN (FORMAT JSON) on the SQL and extract the estimated row count.

    Returns None on any failure — the caller should default to executing
    (Gap 8 resolution: default to execute on EXPLAIN failure).

    Parameters
    ----------
    sql : str
        The SQL to estimate.
    db : Session
        A readonly SQLAlchemy session.

    Returns
    -------
    int or None
        Estimated total rows, or None if estimation fails.
    """
    try:
        explain_sql = f"EXPLAIN (FORMAT JSON) {sql}"
        result = db.execute(text(explain_sql))
        row = result.fetchone()
        if row is None:
            return None

        # PostgreSQL returns a single row with a single column containing JSON
        plan_json = row[0]

        # plan_json may be a string or already parsed (depends on driver)
        if isinstance(plan_json, str):
            import json
            plan_json = json.loads(plan_json)

        # The structure is: [{"Plan": {"Plan Rows": N, ...}, ...}]
        if isinstance(plan_json, list) and len(plan_json) > 0:
            plan = plan_json[0].get("Plan", {})
            estimated = plan.get("Plan Rows")
            if estimated is not None:
                log.debug("row_estimation", estimated_rows=int(estimated))
                return int(estimated)

        return None

    except Exception as exc:
        log.warning("row_estimation_failed", error=str(exc))
        return None


# ── Internal helpers ────────────────────────────────────────────────────────

def _has_limit(sql: str) -> bool:
    """
    Quick check whether the SQL already contains a top-level LIMIT clause.
    Uses a simple heuristic — good enough since we've already parsed with
    sqlglot in the validator.
    """
    # Strip trailing whitespace and semicolons
    stripped = sql.strip().rstrip(";").strip()
    # Check if the last token cluster contains LIMIT
    # We look at the last ~50 characters to avoid false positives from subqueries
    tail = stripped[-80:].upper()
    return "LIMIT" in tail


def _apply_limit(sql: str, max_rows: int) -> str:
    """
    Wrap the SQL with a LIMIT if it doesn't already have one.

    Original SQL is never modified (Hard Rule 8).  Instead we wrap it
    as a subquery:  SELECT * FROM ({original}) AS _q LIMIT {max_rows}
    """
    if _has_limit(sql):
        return sql

    # Remove trailing semicolon for wrapping
    clean = sql.strip().rstrip(";").strip()
    return f"SELECT * FROM ({clean}) AS _q LIMIT {max_rows}"
