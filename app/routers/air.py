"""Health, live air data and geocoding routes."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.dependencies import load_air
from app.schemas import HealthOut
from app.services import geocode

router = APIRouter(prefix="/api", tags=["air"])

Lat = Query(ge=-90, le=90, description="Latitude")
Lon = Query(ge=-180, le=180, description="Longitude")


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness check; also says whether Gemini and Google Air Quality are configured."""
    return HealthOut(status="ok", ai_enabled=settings.ai_enabled, google_aq_enabled=settings.google_aq_enabled)


@router.get("/air")
async def air(request: Request, lat: float = Lat, lon: float = Lon) -> dict:
    """Indian AQI, 24-h averages, hourly forecast and the cleanest/smoggiest windows for a location."""
    return await load_air(request, lat, lon)


@router.get("/geocode/search")
async def geocode_search(request: Request, q: str = Query(min_length=2, max_length=60)) -> dict:
    """Search Indian cities by name."""
    try:
        return {"results": await geocode.search_city(q, request.app.state.http)}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="City search is unavailable right now.") from exc


@router.get("/geocode/reverse")
async def geocode_reverse(request: Request, lat: float = Lat, lon: float = Lon) -> dict:
    """City name for coordinates; falls back to "Your location" if the lookup fails."""
    try:
        return await geocode.reverse(lat, lon, request.app.state.http)
    except httpx.HTTPError:
        return {"name": "Your location", "state": "", "country_code": ""}
