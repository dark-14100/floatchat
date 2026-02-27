"""
FloatChat NL Query Engine — SQL Validator

Three-check validation pipeline plus geography cast warning.
All checks use sqlglot AST inspection — no regex-based SQL parsing.

Checks (run sequentially):
  1. Syntax     — parse with sqlglot (postgres dialect)
  2. Read-only  — walk AST, reject anything that isn't SELECT/WITH (Hard Rule 4)
  3. Whitelist  — extract all table names, reject if any not in ALLOWED_TABLES

Additional:
  4. Geography cast warning — flag ST_DWithin / ST_MakePoint without ::geography
"""

from dataclasses import dataclass, field
from typing import Optional

import structlog
import sqlglot
from sqlglot import exp as expressions

from app.query.schema_prompt import ALLOWED_TABLES

log = structlog.get_logger(__name__)


# ── Result dataclass ────────────────────────────────────────────────────────
@dataclass
class ValidationResult:
    """Result of SQL validation."""
    valid: bool
    error: Optional[str] = None          # Human-readable error message
    check_failed: Optional[str] = None   # "syntax" | "readonly" | "whitelist" | None
    warnings: list[str] = field(default_factory=list)  # e.g., geography cast warnings


# ── Statement types that are allowed (read-only) ───────────────────────────
_READONLY_TYPES = (
    expressions.Select,
    expressions.Union,
    expressions.Intersect,
    expressions.Except,
    expressions.Subquery,
    expressions.CTE,
    expressions.With,
)

# Statement types that are explicitly forbidden
_WRITE_TYPES = (
    expressions.Insert,
    expressions.Update,
    expressions.Delete,
    expressions.Drop,
    expressions.Create,
    expressions.Alter,
    expressions.Merge,
    expressions.TruncateTable,
    expressions.Grant,
    expressions.Revoke,
    expressions.Command,  # catches other DDL/DCL commands
)


def validate_sql(sql: str, allowed_tables: Optional[set[str]] = None) -> ValidationResult:
    """
    Run the 3-check validation pipeline on a SQL string.

    Parameters
    ----------
    sql : str
        The SQL string to validate.
    allowed_tables : set[str] or None
        Table whitelist.  Defaults to ALLOWED_TABLES from schema_prompt.

    Returns
    -------
    ValidationResult
    """
    if allowed_tables is None:
        allowed_tables = ALLOWED_TABLES

    # ── Check 1: Syntax ──────────────────────────────────────────────────
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.ParseError as exc:
        return ValidationResult(
            valid=False,
            error=f"SQL syntax error: {exc}",
            check_failed="syntax",
        )

    if not parsed:
        return ValidationResult(
            valid=False,
            error="Empty SQL — no statements parsed.",
            check_failed="syntax",
        )

    # Reject multi-statement SQL
    # Filter out None entries (sqlglot may return None for trailing semicolons)
    statements = [s for s in parsed if s is not None]
    if len(statements) != 1:
        return ValidationResult(
            valid=False,
            error=f"Only a single SELECT statement is allowed. Got {len(statements)} statements.",
            check_failed="syntax",
        )

    tree = statements[0]

    # ── Check 2: Read-only (AST inspection, Hard Rule 4) ────────────────
    readonly_result = _check_readonly(tree)
    if not readonly_result.valid:
        return readonly_result

    # ── Check 3: Table whitelist ─────────────────────────────────────────
    whitelist_result = _check_whitelist(tree, allowed_tables)
    if not whitelist_result.valid:
        return whitelist_result

    # ── Additional: Geography cast warning ───────────────────────────────
    warnings = _check_geography_casts(tree)

    return ValidationResult(valid=True, warnings=warnings)


# ── Internal check functions ────────────────────────────────────────────────

def _check_readonly(tree: expressions.Expression) -> ValidationResult:
    """
    Walk the AST and reject if any node is a write operation.
    Uses AST node types, not string matching (Hard Rule 4).
    """
    # The top-level statement must be a SELECT (or WITH ... SELECT, UNION, etc.)
    if not isinstance(tree, (*_READONLY_TYPES,)):
        return ValidationResult(
            valid=False,
            error=f"Only SELECT statements are allowed. Got: {type(tree).__name__}",
            check_failed="readonly",
        )

    # Walk all descendants looking for forbidden write nodes
    for node in tree.walk():
        # node is a tuple (expression, parent, key) in walk()
        # Actually sqlglot walk yields Expression objects directly
        if isinstance(node, tuple):
            node = node[0]
        if isinstance(node, _WRITE_TYPES):
            return ValidationResult(
                valid=False,
                error=f"Write operation detected: {type(node).__name__}. Only SELECT is allowed.",
                check_failed="readonly",
            )

    return ValidationResult(valid=True)


def _check_whitelist(
    tree: expressions.Expression,
    allowed_tables: set[str],
) -> ValidationResult:
    """
    Extract all table names referenced in the AST and verify they are
    in the allowed set.
    """
    referenced_tables: set[str] = set()

    for table_node in tree.find_all(expressions.Table):
        table_name = table_node.name
        if table_name:
            referenced_tables.add(table_name.lower())

    # Exclude CTE aliases from the whitelist check — they are not real tables
    cte_aliases: set[str] = set()
    for cte_node in tree.find_all(expressions.CTE):
        alias = cte_node.alias
        if alias:
            cte_aliases.add(alias.lower())

    # Subquery aliases should also be excluded
    real_tables = referenced_tables - cte_aliases

    disallowed = real_tables - {t.lower() for t in allowed_tables}
    if disallowed:
        return ValidationResult(
            valid=False,
            error=f"Referenced tables not in whitelist: {', '.join(sorted(disallowed))}",
            check_failed="whitelist",
        )

    return ValidationResult(valid=True)


def _check_geography_casts(tree: expressions.Expression) -> list[str]:
    """
    Scan the AST for ST_DWithin / ST_MakePoint calls and warn if the
    arguments are not cast to ::geography.

    This is advisory only — not a hard failure.
    """
    warnings: list[str] = []

    for func_node in tree.find_all(expressions.Anonymous):
        func_name = func_node.name.lower() if hasattr(func_node, "name") and func_node.name else ""
        if func_name in ("st_dwithin", "st_makepoint", "st_contains", "st_within"):
            # Check if any argument is cast to geography or geometry
            sql_fragment = func_node.sql(dialect="postgres")
            if func_name == "st_dwithin" and "::geography" not in sql_fragment:
                warnings.append(
                    "ST_DWithin used without ::geography cast. "
                    "For distance calculations, cast arguments to ::geography."
                )
            if func_name in ("st_contains", "st_within") and "::geometry" not in sql_fragment:
                warnings.append(
                    f"{func_name.upper()} used without ::geometry cast. "
                    "For containment checks, cast arguments to ::geometry."
                )

    return warnings
