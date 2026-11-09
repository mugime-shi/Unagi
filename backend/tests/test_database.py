from sqlalchemy.pool import NullPool

from app.db.database import pool_options


def test_lambda_uses_null_pool():
    # Pooled connections in frozen Lambda environments exhausted Supabase's client limit.
    assert pool_options(True) == {"poolclass": NullPool}


def test_local_keeps_connection_pool():
    opts = pool_options(False)
    assert "poolclass" not in opts
    assert opts["pool_size"] == 5
    assert opts["pool_pre_ping"] is True
