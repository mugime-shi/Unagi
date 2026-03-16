"""
SQLAlchemy ORM model for generation_mix table.

Stores ENTSO-E A75 actual generation per production type at 15-min resolution.
Each row = one psr_type for one 15-min slot.

PSR type codes (relevant for SE3):
  B04  Fossil Gas
  B12  Hydro Water Reservoir  (dominant in SE3)
  B14  Nuclear
  B16  Solar
  B19  Wind Onshore
  B20  Other
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class GenerationMix(Base):
    __tablename__ = "generation_mix"

    id: Mapped[int] = mapped_column(primary_key=True)
    area: Mapped[str] = mapped_column(String(4), nullable=False, default="SE3")
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    psr_type: Mapped[str] = mapped_column(String(4), nullable=False)   # "B12", "B14", etc.
    value_mw: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    resolution: Mapped[str] = mapped_column(String(10), default="PT15M")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "area", "timestamp_utc", "psr_type",
            name="uq_generation_mix",
        ),
        Index("idx_generation_mix_area_time", "area", "timestamp_utc"),
    )
