import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware.api_key import ApiKeyMiddleware
from app.routers import (
    elhandlare,
    events,
    generation,
    grid,
    notify,
    prices,
    simulate,
    solar,
    story,
    weather,
)
from app.routers.story import refresh_today_story
from app.services.generation_service import refresh_today_generation

log = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Swedish electricity price optimization dashboard — SE3 (Göteborg)",
    # Disable interactive docs in production (DEBUG=false) to prevent public API abuse
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Starlette processes middleware in reverse-add order (last added = outermost).
# CORSMiddleware must be outermost so CORS preflight is handled before auth.
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://unagieel.net",
        "https://namazu-el.vercel.app",  # transition: remove after migration complete
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Unagi-Key"],
)

app.include_router(prices.router, prefix="/api/v1")
app.include_router(generation.router, prefix="/api/v1")
app.include_router(simulate.router, prefix="/api/v1")
app.include_router(solar.router, prefix="/api/v1")
app.include_router(notify.router, prefix="/api/v1")
app.include_router(grid.router, prefix="/api/v1")
app.include_router(elhandlare.router, prefix="/api/v1")
app.include_router(weather.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(story.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


# Lambda handler (Mangum wraps FastAPI for AWS Lambda)
try:
    from mangum import Mangum

    _mangum = Mangum(app, lifespan="off")
except ImportError:
    _mangum = None


def handler(event, context):
    # EventBridge warmer (direct invoke, not an HTTP event): Mangum would raise on it and
    # feed the api-errors alarm, so it must never get here. Failures are swallowed for the same reason.
    if event.get("warmer"):
        # Generation first: it is bounded (~12 s) and its failure is swallowed, so the story still runs after it.
        generation = None
        try:
            generation = refresh_today_generation()
        except Exception:
            log.exception("warmer: generation refresh failed")
        refreshed = False
        try:
            refreshed = refresh_today_story()
        except Exception:
            log.exception("warmer: story refresh failed")
        return {"warmed": True, "story_refreshed": refreshed, "generation": generation}
    return _mangum(event, context)
