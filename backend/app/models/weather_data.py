"""
SQLAlchemy ORM model for weather_data table.
Schema matches ARCHITECTURE.md § 4.2
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class WeatherData(Base):
    __tablename__ = "weather_data"

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False, default=71420)
    area: Mapped[str] = mapped_column(String(4), nullable=False, default="SE3", server_default="SE3")
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature_c: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    global_radiation_wm2: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    sunshine_hours: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="smhi")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("station_id", "timestamp_utc", "source", "area", name="uq_weather_data"),
        Index("idx_weather_data_station_time", "station_id", "timestamp_utc"),
        Index("idx_weather_data_area_time", "area", "timestamp_utc"),
    )
