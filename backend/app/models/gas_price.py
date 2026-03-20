"""
SQLAlchemy ORM model for gas_price table.
Stores daily THE1 gas settlement prices from Bundesnetzagentur.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class GasPrice(Base):
    __tablename__ = "gas_price"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date(), nullable=False)
    price_eur_mwh: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="bundesnetzagentur")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("trade_date", "source", name="uq_gas_price"),
        Index("idx_gas_price_date", "trade_date"),
    )
