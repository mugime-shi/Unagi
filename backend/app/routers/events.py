"""
/api/v1/events — first-party usage events (see app/models/usage_event.py).

POST /events → record one event; 204 No Content
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.usage_event import UsageEvent

router = APIRouter(prefix="/events", tags=["events"])

DbDep = Annotated[Session, Depends(get_db)]

# ~10 years; anything larger is a broken client clock, not a real visitor
_MAX_DAYS = 3650


class EventRequest(BaseModel):
    event: Literal["visit", "layer_view", "tab_view", "area_select"]
    # Hostnames and short identifiers only — rejects free text so the table
    # cannot be used to store arbitrary (or personal) data.
    label: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    days_since_first: int | None = Field(default=None, ge=0, le=_MAX_DAYS)
    days_since_last: int | None = Field(default=None, ge=0, le=_MAX_DAYS)

    @model_validator(mode="after")
    def _visit_offsets(self):
        if self.event != "visit":
            self.days_since_first = None
            self.days_since_last = None
        elif self.days_since_first is None:
            raise ValueError("visit requires days_since_first")
        elif self.days_since_last is not None and self.days_since_last > self.days_since_first:
            raise ValueError("days_since_last cannot exceed days_since_first")
        return self


@router.post("", status_code=204)
def record_event(data: EventRequest, db: DbDep) -> Response:
    db.add(
        UsageEvent(
            event=data.event,
            label=data.label.lower() if data.label else None,
            days_since_first=data.days_since_first,
            days_since_last=data.days_since_last,
        )
    )
    db.commit()
    return Response(status_code=204)
