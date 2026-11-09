"""
PostgreSQL connection via SQLAlchemy.

Reads DATABASE_URL from config (env var or .env file).
  - Local:  postgresql://unagi:unagi@localhost:5432/unagi  (docker-compose)
  - Prod:   Supabase connection string (set via Lambda env var)
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings

# A frozen Lambda environment keeps any pooled connection open, so a burst of
# cold starts used up Supabase's 15 session-mode clients (2026-11-09). On Lambda,
# close the connection after each session; Supavisor does the pooling.
def pool_options(on_lambda: bool) -> dict:
    if on_lambda:
        return {"poolclass": NullPool}
    return {
        "pool_pre_ping": True,  # detect stale connections
        "pool_size": 5,
        "max_overflow": 10,
    }


engine = create_engine(
    settings.database_url,
    executemany_mode="values_plus_batch",  # batch UPSERTs via psycopg2 execute_values
    **pool_options(bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
