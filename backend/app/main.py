from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import notify, prices, simulate, solar

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Swedish electricity price optimization dashboard — SE3 (Göteborg)",
    # Disable interactive docs in production (DEBUG=false) to prevent public API abuse
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://namazu-el.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(prices.router, prefix="/api/v1")
app.include_router(simulate.router, prefix="/api/v1")
app.include_router(solar.router, prefix="/api/v1")
app.include_router(notify.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


# Lambda handler (Mangum wraps FastAPI for AWS Lambda)
try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
except ImportError:
    pass
