"""
SQLAlchemy ORM model for push_subscriptions table.

Each row represents a browser's Web Push subscription (endpoint + encryption keys).
Subscriptions are created when a user enables notifications in the UI, and deleted
when they disable them or when the push service returns a 404/410 (expired).
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Browser-assigned push endpoint URL (unique per browser/device)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    # ECDH public key from the browser (base64url), used to encrypt push payload
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    # Authentication secret (base64url), used with p256dh for ECDH-ES encryption
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    # Price area for which this subscription receives notifications
    area: Mapped[str] = mapped_column(String(4), nullable=False, default="SE3")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_push_subscription_endpoint"),
    )
