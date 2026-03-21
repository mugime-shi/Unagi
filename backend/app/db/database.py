"""
PostgreSQL connection via SQLAlchemy.

Reads DATABASE_URL from config (env var or .env file).
  - Local:  postgresql://unagi:unagi@localhost:5432/unagi  (docker-compose)
  - Prod:   Supabase connection string (set via Lambda env var)
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # detect stale connections
    pool_size=5,
    max_overflow=10,
    executemany_mode="values_plus_batch",  # batch UPSERTs via psycopg2 execute_values
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
