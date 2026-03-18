"""
SQLAlchemy ORM model for weather_forecast table.

Stores weather forecast data as-issued (not actuals) for ML features.
Each row is one hourly forecast slot, tagged with the date it was issued.
This preserves backtest validity: predictions use the forecast that was
available at prediction time, not hindsight actuals.
"""

from datetime import datetime, timezone

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class WeatherForecast(Base):
    __tablename__ = "weather_forecast"

    id: Mapped[int] = mapped_column(primary_key=True)
    issued_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    target_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature_c: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    wind_speed_10m: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)
    wind_speed_100m: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)
    global_radiation_wm2: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="open-meteo")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("issued_date", "target_utc", "source", name="uq_weather_forecast"),
        Index("idx_weather_forecast_issued", "issued_date", "target_utc"),
    )
