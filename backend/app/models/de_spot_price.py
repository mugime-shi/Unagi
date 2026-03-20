"""
SQLAlchemy ORM model for de_spot_price table.
Stores DE-LU day-ahead spot prices from ENTSO-E A44.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class DeSpotPrice(Base):
    __tablename__ = "de_spot_price"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_eur_mwh: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    resolution: Mapped[str] = mapped_column(String(10), default="PT60M")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("timestamp_utc", "resolution", name="uq_de_spot_price"),
        Index("idx_de_spot_price_time", "timestamp_utc"),
    )
