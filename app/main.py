"""Audit HTTP service: union area and exposed perimeter of rectangles."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .geometry import compute_metrics
from .validation import ValidationError, parse_and_validate

logger = logging.getLogger("audit")


class Readiness:
    """Tracks whether the request validator and scan engine are ready.

    Health checks succeed only once *both* components report ready.
    """

    def __init__(self) -> None:
        self.validator_ready = False
        self.engine_ready = False

    def mark_validator_ready(self) -> None:
        self.validator_ready = True

    def mark_engine_ready(self) -> None:
        self.engine_ready = True

    def status(self) -> dict[str, bool]:
        return {
            "request_validator": self.validator_ready,
            "scan_engine": self.engine_ready,
        }

    def is_ready(self) -> bool:
        return self.validator_ready and self.engine_ready


readiness = Readiness()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Exercise both components once during startup.  Only flag a component
    # ready if its self-check succeeds; any failure leaves /health at 503
    # instead of advertising a half-working service.
    try:
        probe = parse_and_validate(
            b'{"rectangles":[{"id":"__health__","x0":0,"y0":0,"x1":1,"y1":1}]}'
        )
        readiness.mark_validator_ready()
    except Exception:  # pragma: no cover - defensive startup guard
        logger.exception("request validator self-check failed")
        probe = []
    if readiness.validator_ready:
        try:
            compute_metrics(probe)
            readiness.mark_engine_ready()
        except Exception:  # pragma: no cover - defensive startup guard
            logger.exception("scan engine self-check failed")
    logger.info("audit service ready: %s", readiness.status())
    yield


app = FastAPI(title="photomask-defect-audit", lifespan=lifespan)


@app.get("/health")
async def health() -> Response:
    body = {"status": "ok" if readiness.is_ready() else "initializing",
            "components": readiness.status()}
    if readiness.is_ready():
        return JSONResponse(body, status_code=200)
    return JSONResponse(body, status_code=503)


@app.post("/api/audit")
async def audit(request: Request) -> Response:
    if not readiness.is_ready():
        return JSONResponse(
            {"error": "service_unavailable", "message": "service is still initializing"},
            status_code=503,
        )
    raw = await request.body()
    try:
        rects = parse_and_validate(raw)
    except ValidationError as exc:
        # Stable, position-tagged errors; no partial computation results.
        return JSONResponse(
            {
                "error": "validation_failed",
                "message": "request validation failed",
                "errors": exc.errors,
            },
            status_code=422,
        )

    metrics = compute_metrics(rects)
    return JSONResponse(
        {
            "count": len(rects),
            "area": str(metrics.area),
            "perimeter": str(metrics.perimeter),
        },
        status_code=200,
    )
