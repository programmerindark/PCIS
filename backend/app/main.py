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

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.app import ecowitt as ecowitt_client
from backend.app import engine_api
from backend.app.schemas import (
    EcowittCloudRequest, EcowittKeysRequest, EcowittLocalRequest,
    GCPositionRequest, MortalityRequest, RecommendRequest, ScheduleRequest,
)

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


@app.get("/")
def root() -> dict:
    """Friendly landing payload so the bare URL isn't a 404."""
    return {
        "service": "pcis-api",
        "version": app.version,
        "try": "/docs",
        "endpoints": ["/health", "/catalog", "/recommend", "/schedule"],
    }


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


@app.get("/growth-curve")
def growth_curve() -> dict:
    """The cited Aviagen Ross 308 body-weight curve, days 0-56."""
    return {"points": engine_api.growth_curve()}


@app.post("/recommend")
def recommend(req: RecommendRequest) -> dict:
    """Single-moment recommendation for the current conditions."""
    return engine_api.recommend(req)


@app.post("/schedule")
def schedule(req: ScheduleRequest) -> dict:
    """Full-day fan/pad/heater schedule from an entered weather profile."""
    return engine_api.schedule(req)


@app.post("/advise")
def advise(req: RecommendRequest) -> dict:
    """AI Advisor: the single most important action + its predicted effect."""
    return engine_api.advise(req)


@app.post("/mortality")
def mortality(req: MortalityRequest) -> dict:
    """Assess flock mortality vs the cited EU cumulative-mortality ceiling."""
    return engine_api.mortality(req)


@app.post("/gc-position")
def gc_position(req: GCPositionRequest) -> dict:
    """Where the crop sits against the IB Group GC slab tables today.

    A position, not a forecast. See pcis/core/gc_policy.py for why this is
    the only endpoint permitted to return a money figure, and for what it
    deliberately will not compute.
    """
    return engine_api.gc_position(req)


@app.post("/sensor/ecowitt/cloud")
async def ecowitt_cloud(req: EcowittCloudRequest) -> dict:
    """Live house conditions from an Ecowitt gateway via the cloud API."""
    try:
        res = await ecowitt_client.fetch_cloud(
            req.application_key, req.api_key, req.mac, include_raw=req.include_raw
        )
    except Exception as exc:  # transport / DNS / timeout
        return {"ok": False, "error": f"Could not reach Ecowitt: {exc}", "blocks": {}}
    picked = ecowitt_client.select_house_conditions(
        res["blocks"], req.indoor_block, req.outdoor_block
    )
    return {
        "ok": res["raw_code"] == 0 and picked["indoor_t_c"] is not None,
        "error": None if res["raw_code"] == 0 else res["message"],
        "blocks": res["blocks"],
        "pressure_hpa": res.get("pressure_hpa"),
        "cross_checks": res.get("cross_checks"),
        "raw": res.get("raw"),
        **picked,
    }


@app.post("/sensor/ecowitt/local")
async def ecowitt_local(req: EcowittLocalRequest) -> dict:
    """Live house conditions straight from the gateway on the farm LAN."""
    try:
        res = await ecowitt_client.fetch_local(req.gateway_ip)
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach gateway: {exc}", "blocks": {}}
    picked = ecowitt_client.select_house_conditions(
        res["blocks"], req.indoor_block, req.outdoor_block
    )
    return {"ok": picked["indoor_t_c"] is not None, "error": None,
            "blocks": res["blocks"], **picked}


@app.post("/sensor/ecowitt/devices")
async def ecowitt_devices(req: EcowittKeysRequest) -> dict:
    """List gateways on the account so the user need not find a MAC."""
    try:
        return await ecowitt_client.list_devices(req.application_key, req.api_key)
    except Exception as exc:
        return {"devices": [], "message": f"Could not reach Ecowitt: {exc}"}


# ---------------------------------------------------------------------------
# Browser-friendly GET variants.
# Pasting JSON by hand is error-prone (a stray newline inside a copied key
# produces "Invalid control character"), so these accept plain query
# parameters and can be opened directly in a browser address bar.
# ---------------------------------------------------------------------------

def _clean(v: str) -> str:
    """Strip whitespace/newlines that survive a copy-paste."""
    return "".join(v.split())


@app.get("/sensor/ecowitt/devices")
async def ecowitt_devices_get(
    application_key: str = Query(...),
    api_key: str = Query(...),
) -> dict:
    try:
        return await ecowitt_client.list_devices(_clean(application_key), _clean(api_key))
    except Exception as exc:
        return {"devices": [], "message": f"Could not reach Ecowitt: {exc}"}


@app.get("/sensor/ecowitt/cloud")
async def ecowitt_cloud_get(
    application_key: str = Query(...),
    api_key: str = Query(...),
    mac: str = Query(...),
    indoor_block: str = Query("outdoor"),
    outdoor_block: str | None = Query(None),
    include_raw: bool = Query(True),
) -> dict:
    try:
        res = await ecowitt_client.fetch_cloud(
            _clean(application_key), _clean(api_key), _clean(mac), include_raw=include_raw
        )
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach Ecowitt: {exc}", "blocks": {}}
    picked = ecowitt_client.select_house_conditions(
        res["blocks"], indoor_block, outdoor_block
    )
    return {
        "ok": res["raw_code"] == 0 and picked["indoor_t_c"] is not None,
        "error": None if res["raw_code"] == 0 else res["message"],
        "blocks": res["blocks"],
        "pressure_hpa": res.get("pressure_hpa"),
        "cross_checks": res.get("cross_checks"),
        "raw": res.get("raw"),
        **picked,
    }
