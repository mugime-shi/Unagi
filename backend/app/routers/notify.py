"""
/api/v1/notify — Web Push notification endpoints.

GET  /vapid-public-key    → return VAPID public key for the frontend to subscribe
POST /subscribe           → save (or update) a push subscription
DELETE /subscribe         → remove a subscription (user disabled notifications)
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.models.push_subscription import PushSubscription

router = APIRouter(prefix="/notify", tags=["notify"])

DbDep = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class SubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    area: str = "SE3"


class UnsubscribeRequest(BaseModel):
    endpoint: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/vapid-public-key")
def get_vapid_public_key():
    """
    Return the VAPID public key so the frontend can call pushManager.subscribe().
    The key is base64url-encoded uncompressed EC point (65 bytes, no padding).
    """
    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe", status_code=201)
def subscribe(data: SubscribeRequest, db: DbDep):
    """
    Save or update a browser's push subscription.
    UPSERT on endpoint: if the same browser re-subscribes (key rotation), update keys.
    """
    sub = db.query(PushSubscription).filter_by(endpoint=data.endpoint).first()
    if sub:
        sub.p256dh = data.p256dh
        sub.auth = data.auth
        sub.area = data.area
    else:
        sub = PushSubscription(
            endpoint=data.endpoint,
            p256dh=data.p256dh,
            auth=data.auth,
            area=data.area,
        )
        db.add(sub)
    db.commit()
    return {"status": "subscribed", "area": data.area}


@router.delete("/subscribe")
def unsubscribe(data: UnsubscribeRequest, db: DbDep):
    """Remove a push subscription (user turned off notifications)."""
    sub = db.query(PushSubscription).filter_by(endpoint=data.endpoint).first()
    if sub:
        db.delete(sub)
        db.commit()
    return {"status": "unsubscribed"}


@router.post("/test")
def send_test_notification(db: DbDep, area: str = "SE3"):
    """Dev/debug: trigger Web Push for all subscribers of this area. Only available when DEBUG=true."""
    if not settings.debug:
        raise HTTPException(status_code=404, detail="Not found")
    from app.services.notify_service import notify_subscribers
    return notify_subscribers(db, area)


@router.post("/telegram-test")
def send_telegram_test(db: DbDep, area: str = "SE3"):
    """Dev/debug: send a Telegram message immediately. Only available when DEBUG=true."""
    if not settings.debug:
        raise HTTPException(status_code=404, detail="Not found")
    from app.services.telegram_service import send_telegram_alert
    return send_telegram_alert(db, area)
