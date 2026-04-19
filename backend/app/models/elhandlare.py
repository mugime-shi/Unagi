"""
SQLAlchemy ORM model for elhandlare table.

Stores Swedish electricity retailer (elhandlare) pricing data. Rates are exkl moms.
Valid periods allow historical tracking when tariffs change.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Elhandlare(Base):
    __tablename__ = "elhandlare"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    area: Mapped[str] = mapped_column(String(4), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "rorligt" | "kvartspris" | "fast"
    paslag_ore_kwh: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)  # exkl moms
    monthly_fee_sek: Mapped[float] = mapped_column(
        Numeric(8, 2), nullable=False
    )  # inkl moms (as advertised to consumers)
    elcert_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    binding_months: Mapped[int] = mapped_column(nullable=False, default=0)
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("slug", "area", "contract_type", "valid_from", name="uq_elhandlare_tariff"),
        Index("idx_elhandlare_area", "area"),
    )
