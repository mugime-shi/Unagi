"""
SQLAlchemy ORM model for grid_operators table.

Stores electricity grid operator (nätägare) tariff data per area and dwelling type.
Rates are exkl moms. Valid periods allow historical tracking when tariffs change.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class GridOperator(Base):
    __tablename__ = "grid_operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(50), nullable=False)
    area: Mapped[str] = mapped_column(String(4), nullable=False)
    dwelling_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "apartment" | "house"
    fast_fee_sek_year: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    transfer_fee_ore: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    effect_fee_sek_kw: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("slug", "dwelling_type", "valid_from", name="uq_grid_operator_tariff"),
        Index("idx_grid_operators_area", "area"),
    )
