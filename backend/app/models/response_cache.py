from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ResponseCache(Base):
    """
    Precomputed JSON responses shared by every Lambda instance.

    Global (non per-user) endpoints are slow to compute (several seconds); the warmer
    stores the result here so a request is one primary-key read. computed_at is UTC.
    """

    __tablename__ = "response_cache"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
