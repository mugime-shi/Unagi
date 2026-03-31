from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ForecastAccuracy(Base):
    """
    Stores hourly forecast predictions alongside actuals for accuracy scoring.

    Predictions are recorded when the forecast is generated (e.g. Day N-1).
    Actuals are filled in after real prices are published (Day N or later).
    MAE/RMSE can then be computed per model over any date range.
    """

    __tablename__ = "forecast_accuracy"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    area: Mapped[str] = mapped_column(String(4), nullable=False, default="SE3")
    model_name: Mapped[str] = mapped_column(String(30), nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23 Stockholm hour
    predicted_sek_kwh: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    predicted_low_sek_kwh: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    predicted_high_sek_kwh: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    actual_sek_kwh: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    shap_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "target_date",
            "area",
            "model_name",
            "hour",
            name="uq_forecast_accuracy",
        ),
        Index("idx_forecast_accuracy_date_area", "target_date", "area"),
    )
