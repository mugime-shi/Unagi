"""
SQLAlchemy ORM model for balancing_prices table.

Stores ENTSO-E A85 imbalance prices at 15-min resolution.
Each row represents one imbalance category for one 15-min slot:
  category = 'A04'  Long  (excess supply — price ≤ DA)
  category = 'A05'  Short (supply deficit — price can spike far above DA)
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BalancingPrice(Base):
    __tablename__ = "balancing_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    area: Mapped[str] = mapped_column(String(4), nullable=False, default="SE3")
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_eur_mwh: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    price_sek_kwh: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    category: Mapped[str] = mapped_column(String(4), nullable=False)  # "A04" or "A05"
    resolution: Mapped[str] = mapped_column(String(10), default="PT15M")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "area", "timestamp_utc", "category", "resolution",
            name="uq_balancing_price",
        ),
        Index("idx_balancing_prices_area_time", "area", "timestamp_utc"),
    )
