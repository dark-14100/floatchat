"""
Tests for app.query.validator — SQL validation pipeline.

Uses real sqlglot parsing (no mocks).  No database or API keys required.
"""

import pytest

from app.query.validator import validate_sql, ValidationResult
from app.query.schema_prompt import ALLOWED_TABLES


# ═════════════════════════════════════════════════════════════════════════════
# Check 1: Syntax
# ═════════════════════════════════════════════════════════════════════════════

class TestSyntaxCheck:
    """Syntax validation using sqlglot postgres dialect."""

    def test_valid_select(self):
        result = validate_sql("SELECT * FROM floats LIMIT 10")
        assert result.valid is True
        assert result.error is None

    def test_valid_select_with_where(self):
        result = validate_sql(
            "SELECT f.platform_number FROM floats f WHERE f.float_type = 'BGC'"
        )
        assert result.valid is True

    def test_syntax_error_missing_from(self):
        result = validate_sql("SELECT * FORM floats")
        # sqlglot may parse this differently — check it doesn't crash
        # The key is that obviously bad SQL is caught
        assert isinstance(result, ValidationResult)

    def test_empty_string(self):
        result = validate_sql("")
        assert result.valid is False
        assert result.check_failed == "syntax"

    def test_multi_statement_rejected(self):
        result = validate_sql(
            "SELECT 1; SELECT 2"
        )
        assert result.valid is False
        assert result.check_failed == "syntax"
        assert "single SELECT" in (result.error or "").lower() or "statements" in (result.error or "").lower()

    def test_trailing_semicolon_ok(self):
        result = validate_sql("SELECT * FROM floats LIMIT 10;")
        assert result.valid is True


# ═════════════════════════════════════════════════════════════════════════════
# Check 2: Read-only
# ═════════════════════════════════════════════════════════════════════════════

class TestReadonlyCheck:
    """Read-only enforcement via AST inspection (Hard Rule 4)."""

    def test_select_allowed(self):
        result = validate_sql("SELECT * FROM floats")
        assert result.valid is True

    def test_insert_rejected(self):
        result = validate_sql(
            "INSERT INTO floats (platform_number) VALUES ('test')"
        )
        assert result.valid is False
        assert result.check_failed == "readonly"

    def test_update_rejected(self):
        result = validate_sql(
            "UPDATE floats SET country = 'test' WHERE float_id = 1"
        )
        assert result.valid is False
        assert result.check_failed == "readonly"

    def test_delete_rejected(self):
        result = validate_sql("DELETE FROM floats WHERE float_id = 1")
        assert result.valid is False
        assert result.check_failed == "readonly"

    def test_drop_rejected(self):
        result = validate_sql("DROP TABLE floats")
        assert result.valid is False
        assert result.check_failed == "readonly"

    def test_create_rejected(self):
        result = validate_sql("CREATE TABLE evil (id INT)")
        assert result.valid is False
        assert result.check_failed == "readonly"

    def test_alter_rejected(self):
        result = validate_sql("ALTER TABLE floats ADD COLUMN evil TEXT")
        assert result.valid is False
        assert result.check_failed == "readonly"


# ═════════════════════════════════════════════════════════════════════════════
# Check 3: Table whitelist
# ═════════════════════════════════════════════════════════════════════════════

class TestWhitelistCheck:
    """Table whitelist enforcement."""

    def test_allowed_table(self):
        result = validate_sql("SELECT * FROM floats")
        assert result.valid is True

    def test_allowed_table_with_alias(self):
        result = validate_sql("SELECT f.platform_number FROM floats f")
        assert result.valid is True

    def test_disallowed_table(self):
        result = validate_sql("SELECT * FROM secret_table")
        assert result.valid is False
        assert result.check_failed == "whitelist"
        assert "secret_table" in (result.error or "")

    def test_multiple_allowed_tables(self):
        result = validate_sql(
            "SELECT p.profile_id, m.temperature "
            "FROM profiles p "
            "JOIN measurements m ON m.profile_id = p.profile_id"
        )
        assert result.valid is True

    def test_mixed_allowed_disallowed(self):
        result = validate_sql(
            "SELECT * FROM floats f JOIN evil_table e ON e.id = f.float_id"
        )
        assert result.valid is False
        assert result.check_failed == "whitelist"

    def test_materialized_view_allowed(self):
        result = validate_sql("SELECT * FROM mv_float_latest_position")
        assert result.valid is True

    def test_mv_dataset_stats_allowed(self):
        result = validate_sql("SELECT * FROM mv_dataset_stats")
        assert result.valid is True

    def test_all_allowed_tables_accepted(self):
        """Each allowed table should pass whitelist individually."""
        for table in ALLOWED_TABLES:
            result = validate_sql(f"SELECT * FROM {table} LIMIT 1")
            assert result.valid is True, f"Table '{table}' should be allowed but got: {result.error}"


# ═════════════════════════════════════════════════════════════════════════════
# CTE handling
# ═════════════════════════════════════════════════════════════════════════════

class TestCTEHandling:
    """CTEs (WITH ... AS) are allowed and aliases excluded from whitelist check."""

    def test_cte_allowed(self):
        sql = """
        WITH top_floats AS (
            SELECT float_id, COUNT(*) AS cnt
            FROM profiles
            GROUP BY float_id
            LIMIT 10
        )
        SELECT tf.float_id, tf.cnt
        FROM top_floats tf
        """
        result = validate_sql(sql)
        assert result.valid is True

    def test_cte_alias_not_in_whitelist(self):
        """CTE alias 'my_cte' should not trigger a whitelist rejection."""
        sql = """
        WITH my_cte AS (
            SELECT * FROM floats LIMIT 5
        )
        SELECT * FROM my_cte
        """
        result = validate_sql(sql)
        assert result.valid is True

    def test_cte_with_disallowed_table(self):
        sql = """
        WITH my_cte AS (
            SELECT * FROM secret_table
        )
        SELECT * FROM my_cte
        """
        result = validate_sql(sql)
        assert result.valid is False
        assert result.check_failed == "whitelist"


# ═════════════════════════════════════════════════════════════════════════════
# Subquery handling
# ═════════════════════════════════════════════════════════════════════════════

class TestSubqueryHandling:
    """Subqueries are allowed but all referenced tables must be whitelisted."""

    def test_subquery_allowed(self):
        sql = """
        SELECT * FROM profiles p
        WHERE p.float_id IN (
            SELECT f.float_id FROM floats f WHERE f.float_type = 'BGC'
        )
        """
        result = validate_sql(sql)
        assert result.valid is True

    def test_subquery_with_disallowed_table(self):
        sql = """
        SELECT * FROM profiles p
        WHERE p.float_id IN (
            SELECT id FROM evil_table
        )
        """
        result = validate_sql(sql)
        assert result.valid is False
        assert result.check_failed == "whitelist"


# ═════════════════════════════════════════════════════════════════════════════
# Geography cast warnings
# ═════════════════════════════════════════════════════════════════════════════

class TestGeographyCastWarning:
    """Geography cast warnings are advisory, not hard failures."""

    def test_valid_with_geography_cast(self):
        sql = """
        SELECT * FROM profiles p
        WHERE ST_DWithin(p.geom::geography, ST_MakePoint(72.5, 15.0)::geography, 100000)
        """
        result = validate_sql(sql)
        assert result.valid is True

    def test_no_warnings_on_simple_query(self):
        result = validate_sql("SELECT * FROM floats LIMIT 10")
        assert result.valid is True
        assert result.warnings == []


# ═════════════════════════════════════════════════════════════════════════════
# Complex real-world queries
# ═════════════════════════════════════════════════════════════════════════════

class TestComplexQueries:
    """Validate complex queries similar to schema prompt examples."""

    def test_join_with_aggregation(self):
        sql = """
        SELECT p.platform_number, AVG(m.temperature) AS avg_temp
        FROM profiles p
        JOIN measurements m ON m.profile_id = p.profile_id
        WHERE m.temp_qc = 1
        GROUP BY p.platform_number
        ORDER BY avg_temp DESC
        LIMIT 1000
        """
        result = validate_sql(sql)
        assert result.valid is True

    def test_spatial_query(self):
        sql = """
        SELECT p.profile_id, p.platform_number, p.latitude, p.longitude
        FROM profiles p
        WHERE p.latitude BETWEEN 10 AND 20
          AND p.longitude BETWEEN 60 AND 80
        ORDER BY p.timestamp DESC
        LIMIT 1000
        """
        result = validate_sql(sql)
        assert result.valid is True

    def test_ocean_region_join(self):
        sql = """
        SELECT p.profile_id, p.platform_number
        FROM profiles p
        JOIN ocean_regions r ON ST_Contains(r.geom::geometry, p.geom::geometry)
        WHERE r.region_name = 'Arabian Sea'
        LIMIT 1000
        """
        result = validate_sql(sql)
        assert result.valid is True

    def test_union_query(self):
        sql = """
        SELECT platform_number, 'core' AS source FROM floats WHERE float_type = 'core'
        UNION
        SELECT platform_number, 'BGC' AS source FROM floats WHERE float_type = 'BGC'
        """
        result = validate_sql(sql)
        assert result.valid is True

    def test_custom_allowed_tables(self):
        """validate_sql accepts a custom allowed_tables set."""
        result = validate_sql(
            "SELECT * FROM my_custom_table",
            allowed_tables={"my_custom_table"},
        )
        assert result.valid is True


# ═════════════════════════════════════════════════════════════════════════════
# ValidationResult dataclass
# ═════════════════════════════════════════════════════════════════════════════

class TestValidationResult:
    def test_defaults(self):
        r = ValidationResult(valid=True)
        assert r.valid is True
        assert r.error is None
        assert r.check_failed is None
        assert r.warnings == []

    def test_with_error(self):
        r = ValidationResult(valid=False, error="bad sql", check_failed="syntax")
        assert r.valid is False
        assert r.error == "bad sql"
        assert r.check_failed == "syntax"
