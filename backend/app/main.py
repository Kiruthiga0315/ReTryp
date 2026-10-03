"""ReTryp API.

FastAPI application: REST with OpenAPI docs, plus Server-Sent Events for live
journey updates.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .settings_store import current_data_status
from .middleware import DisplayCurrencyMiddleware
from .routers import auth, bookings, journey, recovery, trips
from .routers.deps import bus  # noqa: F401 - re-exported for tests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("retryp")

settings = get_settings()

app = FastAPI(
    title="ReTryp API",
    version="1.0.0",
    description=(
        "Trip recovery platform API. Every data point carries provenance "
        "(LIVE, CACHED, REFERENCE, SIMULATED or UNAVAILABLE). The API is "
        "fully functional with no external API keys configured."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    # The FX provenance header is read by the client to show which rate was
    # applied and when it was published.
    expose_headers=["X-Retryp-FX"],
)

# Outermost: resolves the viewer's display currency before routing so every
# serializer converts consistently within a request.
app.add_middleware(DisplayCurrencyMiddleware)

app.include_router(auth.router)
app.include_router(trips.router)
app.include_router(journey.router)
app.include_router(recovery.router)
app.include_router(bookings.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "data_status": current_data_status()["mode"],
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak internals to the client. The detail stays in the log."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Something went wrong handling that request.",
            "path": request.url.path,
        },
    )
