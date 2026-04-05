from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class HydroReservoir(Base):
    """
    Weekly hydro reservoir stored energy (MWh) from ENTSO-E A72.

    Used as a feature for price forecasting: high reservoir levels
    (especially during spring snowmelt) correlate with low prices.
    Data is published weekly (P7D resolution).
    """

    __tablename__ = "hydro_reservoir"

    id: Mapped[int] = mapped_column(primary_key=True)
    area: Mapped[str] = mapped_column(String(4), nullable=False, default="SE3")
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    stored_energy_mwh: Mapped[float] = mapped_column(Numeric(12, 0), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("area", "week_start", name="uq_hydro_reservoir"),
        Index("idx_hydro_reservoir_area_week", "area", "week_start"),
    )
