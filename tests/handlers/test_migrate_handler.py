"""Tests for migrate_handler — ensures yoyo MigrationList is passed correctly."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.function_name = "test-migration"
    ctx.function_version = "$LATEST"
    ctx.invoked_function_arn = "arn:aws:lambda:us-west-2:123456789012:function:test-migration"
    ctx.memory_limit_in_mb = 256
    ctx.aws_request_id = "test-request-id"
    ctx.log_group_name = "/aws/lambda/test-migration"
    ctx.log_stream_name = "2024/01/01/[$LATEST]test"
    return ctx


@pytest.fixture(autouse=True)
def patch_db_url():
    with patch(
        "library_layer.utils.db.get_db_url", return_value="postgresql://test:test@localhost/test"
    ):
        import importlib
        import lambda_functions.admin.migrate_handler as mh

        importlib.reload(mh)
        yield mh


def test_apply_migrations_receives_migration_list_not_plain_list(patch_db_url, mock_context):
    """Regression test: backend.apply_migrations must receive the yoyo MigrationList
    (returned by to_apply), not a plain list — plain lists lack post_apply attribute."""
    mh = patch_db_url

    migration_list = MagicMock()
    migration_list.__len__ = lambda s: 2
    migration_list.__iter__ = lambda s: iter(
        [MagicMock(id="0001_initial"), MagicMock(id="0002_second")]
    )

    mock_backend = MagicMock()
    mock_backend.to_apply.return_value = migration_list
    mock_backend.lock.return_value.__enter__ = lambda s: s
    mock_backend.lock.return_value.__exit__ = MagicMock(return_value=False)

    with patch("lambda_functions.admin.migrate_handler.get_backend", return_value=mock_backend):
        with patch("lambda_functions.admin.migrate_handler.read_migrations"):
            result = mh.handler({}, mock_context)

    # apply_migrations must be called with the MigrationList object, NOT a plain list
    mock_backend.apply_migrations.assert_called_once_with(migration_list)
    assert result["status"] == "ok"
    assert result["count"] == 2
    assert result["applied"] == ["0001_initial", "0002_second"]


def test_no_pending_migrations_returns_empty(patch_db_url, mock_context):
    """When there are no pending migrations, handler returns empty applied list."""
    mh = patch_db_url

    empty_migration_list = MagicMock()
    empty_migration_list.__len__ = lambda s: 0
    empty_migration_list.__iter__ = lambda s: iter([])

    mock_backend = MagicMock()
    mock_backend.to_apply.return_value = empty_migration_list
    mock_backend.lock.return_value.__enter__ = lambda s: s
    mock_backend.lock.return_value.__exit__ = MagicMock(return_value=False)

    with patch("lambda_functions.admin.migrate_handler.get_backend", return_value=mock_backend):
        with patch("lambda_functions.admin.migrate_handler.read_migrations"):
            result = mh.handler({}, mock_context)

    assert result["status"] == "ok"
    assert result["count"] == 0
    assert result["applied"] == []
