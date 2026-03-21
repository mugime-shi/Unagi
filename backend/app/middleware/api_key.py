import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

EXEMPT_PATHS = {"/health"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests missing a valid X-Unagi-Key header.

    Behaviour:
    - OPTIONS (CORS preflight) and EXEMPT_PATHS always pass through.
    - If ``settings.api_key`` is empty the middleware is a no-op
      (local dev / test environment).
    """

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        if settings.api_key:
            provided = request.headers.get("x-unagi-key", "")
            if not hmac.compare_digest(provided, settings.api_key):
                return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        return await call_next(request)
