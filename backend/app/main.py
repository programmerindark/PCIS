"""PCIS API — FastAPI service that serves the validated engine.

Run (from the repo root, so the `pcis` package is importable):
    pip install -r backend/requirements.txt
    uvicorn backend.app.main:app --reload

The frontend (Next.js on Vercel) calls these endpoints. This service
owns NO science: it delegates everything to `pcis.core` via
`engine_api`, so the cited, unit-tested engine is the single source of
truth on the web exactly as on the desktop.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import engine_api
from backend.app.schemas import RecommendRequest, ScheduleRequest

app = FastAPI(
    title="PCIS API",
    version="1.0.0",
    description="Poultry Climate Intelligence System — climate engine over HTTP.",
)

# CORS: the Vercel frontend origin(s). Comma-separated env override for
# production; permissive default for local development.
_origins = os.getenv("PCIS_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "pcis-api", "version": app.version}


@app.get("/catalog")
def catalog() -> dict:
    """Everything the UI needs to populate its dropdowns."""
    return {
        "fans": engine_api.list_fans(),
        "pads": engine_api.list_pads(),
        "insulation": engine_api.insulation_levels(),
    }


@app.post("/recommend")
def recommend(req: RecommendRequest) -> dict:
    """Single-moment recommendation for the current conditions."""
    return engine_api.recommend(req)


@app.post("/schedule")
def schedule(req: ScheduleRequest) -> dict:
    """Full-day fan/pad/heater schedule from an entered weather profile."""
    return engine_api.schedule(req)
