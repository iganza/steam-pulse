"""Tests for admin handler — init/status/query actions and SQL safety rules."""

from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.autocommit = False
    cursor = MagicMock()
    cursor.__enter__ = lambda s: s
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn, cursor


@pytest.fixture(autouse=True)
def patch_get_conn(mock_conn):
    conn, _ = mock_conn
    with patch("library_layer.utils.db.get_conn", return_value=conn):
        import importlib
        import lambda_functions.admin.handler as h
        importlib.reload(h)
        yield h


def test_init_calls_create_all(patch_get_conn, mock_conn):
    h = patch_get_conn
    conn, _ = mock_conn
    with patch("lambda_functions.admin.handler.create_all") as mock_create:
        result = h.handler({"action": "init"}, None)
    assert result["status"] == "ok"
    mock_create.assert_called_once_with(conn)


def test_status_returns_tables(patch_get_conn, mock_conn):
    h = patch_get_conn
    _, cur = mock_conn
    cur.fetchall.return_value = [{"tablename": "games"}, {"tablename": "reports"}]
    cur.fetchone.side_effect = [{"cnt": 42}, {"cnt": 7}]
    result = h.handler({"action": "status"}, None)
    assert result["status"] == "ok"
    assert result["tables"] == [{"table": "games", "rows": 42}, {"table": "reports", "rows": 7}]


def test_query_select_allowed(patch_get_conn, mock_conn):
    h = patch_get_conn
    _, cur = mock_conn
    cur.description = [("appid",), ("name",)]
    cur.fetchmany.return_value = [{"appid": 440, "name": "TF2"}]
    result = h.handler({"action": "query", "sql": "SELECT appid, name FROM games"}, None)
    assert result["status"] == "ok"
    assert result["columns"] == ["appid", "name"]
    assert result["count"] == 1


def test_query_rejects_insert(patch_get_conn):
    h = patch_get_conn
    result = h.handler({"action": "query", "sql": "INSERT INTO games VALUES (1)"}, None)
    assert result["status"] == "error"
    assert "read-only" in result["message"]


def test_query_rejects_semicolon(patch_get_conn):
    h = patch_get_conn
    result = h.handler({"action": "query", "sql": "SELECT 1; DROP TABLE games"}, None)
    assert result["status"] == "error"
    assert "Multiple" in result["message"]


def test_query_rejects_explain_analyze(patch_get_conn):
    h = patch_get_conn
    result = h.handler({"action": "query", "sql": "EXPLAIN ANALYZE SELECT 1"}, None)
    assert result["status"] == "error"
    assert "EXPLAIN ANALYZE" in result["message"]


def test_query_rejects_cte_with_delete(patch_get_conn):
    h = patch_get_conn
    sql = "WITH x AS (DELETE FROM games RETURNING *) SELECT * FROM x"
    result = h.handler({"action": "query", "sql": sql}, None)
    assert result["status"] == "error"
    assert "read-only" in result["message"]


def test_query_empty_sql(patch_get_conn):
    h = patch_get_conn
    result = h.handler({"action": "query", "sql": ""}, None)
    assert result["status"] == "error"
    assert "No SQL" in result["message"]


def test_unknown_action(patch_get_conn):
    h = patch_get_conn
    result = h.handler({"action": "explode"}, None)
    assert result["status"] == "error"
    assert "explode" in result["message"]
