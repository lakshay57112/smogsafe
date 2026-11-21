"""Shared helpers for routers: access to app-wide services and live air data."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.services.air_quality import AirDataError, get_air
from app.services.community import CommunityStore
from app.services.gemini import GeminiService

log = logging.getLogger("smogsafe")


def gemini_service(request: Request) -> GeminiService:
    return request.app.state.gemini


def community_store(request: Request) -> CommunityStore:
    return request.app.state.community


GeminiDep = Annotated[GeminiService, Depends(gemini_service)]
StoreDep = Annotated[CommunityStore, Depends(community_store)]


async def load_air(request: Request, lat: float, lon: float) -> dict:
    """Live air snapshot for a location, or a friendly 503 if the data source is down."""
    try:
        return await get_air(lat, lon, request.app.state.http)
    except AirDataError as exc:
        log.warning("Air data failed: %s", exc)
        detail = "Live air data is unavailable right now. Please try again shortly."
        raise HTTPException(status_code=503, detail=detail) from exc
