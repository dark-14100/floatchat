"""
Tests for app.query.executor — SQL execution on readonly session.

Uses mocked SQLAlchemy sessions — no live database required.
"""

from unittest.mock import MagicMock, patch
import json

import pytest

from app.query.executor import (
    ExecutionResult,
    execute_sql,
    estimate_rows,
    _has_limit,
    _apply_limit,
)


# ═════════════════════════════════════════════════════════════════════════════
# _has_limit helper
# ═════════════════════════════════════════════════════════════════════════════

class TestHasLimit:
    def test_has_limit(self):
        assert _has_limit("SELECT * FROM floats LIMIT 10") is True

    def test_has_limit_with_semicolon(self):
        assert _has_limit("SELECT * FROM floats LIMIT 10;") is True

    def test_no_limit(self):
        assert _has_limit("SELECT * FROM floats") is False

    def test_limit_in_subquery_in_tail(self):
        # _has_limit checks last 80 chars heuristically; LIMIT in tail → True
        sql = "SELECT * FROM (SELECT * FROM floats LIMIT 5) AS sub WHERE 1=1 ORDER BY platform_number"
        assert _has_limit(sql) is True

    def test_limit_in_subquery_far_from_tail(self):
        # LIMIT buried deep enough in subquery falls outside the tail-80 window
        sql = ("SELECT * FROM (SELECT * FROM floats LIMIT 5) AS sub "
               "WHERE 1=1 ORDER BY platform_number, float_type, float_serial_number, deploy_date")
        assert _has_limit(sql) is False

    def test_limit_at_end(self):
        sql = "SELECT * FROM floats f JOIN profiles p ON p.float_id = f.float_id LIMIT 1000"
        assert _has_limit(sql) is True


# ═════════════════════════════════════════════════════════════════════════════
# _apply_limit helper
# ═════════════════════════════════════════════════════════════════════════════

class TestApplyLimit:
    def test_wraps_when_no_limit(self):
        sql = "SELECT * FROM floats"
        result = _apply_limit(sql, 500)
        assert "LIMIT 500" in result
        assert "AS _q" in result
        assert sql.strip() in result

    def test_no_wrap_when_limit_present(self):
        sql = "SELECT * FROM floats LIMIT 10"
        result = _apply_limit(sql, 500)
        assert result == sql  # unchanged

    def test_strips_trailing_semicolon(self):
        sql = "SELECT * FROM floats  ;  "
        result = _apply_limit(sql, 100)
        assert "LIMIT 100" in result
        assert result.count(";") == 0  # semicolon removed


# ═════════════════════════════════════════════════════════════════════════════
# execute_sql
# ═════════════════════════════════════════════════════════════════════════════

class TestExecuteSql:
    def _mock_db(self, rows, columns):
        """Create a mock DB session that returns the given rows/columns."""
        mock_result = MagicMock()
        mock_result.keys.return_value = columns
        mock_result.fetchall.return_value = [
            tuple(row[c] for c in columns) for row in rows
        ]
        db = MagicMock()
        db.execute.return_value = mock_result
        return db

    def test_successful_execution(self):
        rows = [
            {"platform_number": "F001", "float_type": "core"},
            {"platform_number": "F002", "float_type": "BGC"},
        ]
        columns = ["platform_number", "float_type"]
        db = self._mock_db(rows, columns)

        result = execute_sql("SELECT * FROM floats", db, max_rows=100)

        assert result.error is None
        assert result.row_count == 2
        assert result.columns == columns
        assert len(result.rows) == 2
        assert result.rows[0]["platform_number"] == "F001"
        assert result.truncated is False

    def test_truncated_results(self):
        # Simulate max_rows = 2, with 2 rows returned (implies truncation)
        rows = [{"id": 1}, {"id": 2}]
        columns = ["id"]
        db = self._mock_db(rows, columns)

        result = execute_sql("SELECT id FROM floats", db, max_rows=2)

        assert result.row_count == 2
        assert result.truncated is True

    def test_empty_result(self):
        db = self._mock_db([], ["id"])
        result = execute_sql("SELECT * FROM floats WHERE 1=0", db)
        assert result.row_count == 0
        assert result.rows == []
        assert result.truncated is False

    def test_execution_error(self):
        db = MagicMock()
        db.execute.side_effect = Exception("connection refused")

        result = execute_sql("SELECT * FROM floats", db)

        assert result.error is not None
        assert "connection refused" in result.error
        assert result.row_count == 0

    def test_limit_already_present(self):
        rows = [{"id": 1}]
        columns = ["id"]
        db = self._mock_db(rows, columns)

        execute_sql("SELECT * FROM floats LIMIT 5", db, max_rows=1000)

        # Check that the executed SQL was NOT wrapped
        call_args = db.execute.call_args
        executed_sql = str(call_args[0][0])
        assert "AS _q" not in executed_sql


# ═════════════════════════════════════════════════════════════════════════════
# estimate_rows
# ═════════════════════════════════════════════════════════════════════════════

class TestEstimateRows:
    def test_successful_estimation(self):
        plan_json = [{"Plan": {"Plan Rows": 42000, "Node Type": "Seq Scan"}}]

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (plan_json,)
        db = MagicMock()
        db.execute.return_value = mock_result

        result = estimate_rows("SELECT * FROM floats", db)
        assert result == 42000

    def test_estimation_from_json_string(self):
        plan_json = json.dumps([{"Plan": {"Plan Rows": 500}}])

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (plan_json,)
        db = MagicMock()
        db.execute.return_value = mock_result

        result = estimate_rows("SELECT * FROM floats", db)
        assert result == 500

    def test_estimation_returns_none_on_error(self):
        db = MagicMock()
        db.execute.side_effect = Exception("explain failed")

        result = estimate_rows("SELECT * FROM floats", db)
        assert result is None

    def test_estimation_returns_none_on_empty_result(self):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        db = MagicMock()
        db.execute.return_value = mock_result

        result = estimate_rows("SELECT * FROM floats", db)
        assert result is None

    def test_estimation_returns_none_on_bad_json(self):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("not json at all",)
        db = MagicMock()
        db.execute.return_value = mock_result

        result = estimate_rows("SELECT * FROM floats", db)
        assert result is None


# ═════════════════════════════════════════════════════════════════════════════
# ExecutionResult dataclass
# ═════════════════════════════════════════════════════════════════════════════

class TestExecutionResult:
    def test_defaults(self):
        r = ExecutionResult()
        assert r.columns == []
        assert r.rows == []
        assert r.row_count == 0
        assert r.truncated is False
        assert r.error is None

    def test_with_error(self):
        r = ExecutionResult(error="boom")
        assert r.error == "boom"
        assert r.row_count == 0
