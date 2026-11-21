"""Smog Circle: anonymous city pledges."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.dependencies import StoreDep
from app.schemas import CommunityOut, PledgeOut, PledgeRequest
from app.security import check_rate, pledge_limiter

router = APIRouter(prefix="/api/community", tags=["community"])


@router.get("", response_model=CommunityOut)
def community(
    store: StoreDep,
    city: str = Query(min_length=2, max_length=80),
    device_id: str | None = Query(default=None, max_length=64, pattern=r"^[A-Za-z0-9-]+$"),
) -> dict:
    """Pledge counts and the shared CO₂ estimate for a city."""
    return store.summary(city, device_id)


@router.post("/pledge", response_model=PledgeOut)
def pledge(req: PledgeRequest, request: Request, store: StoreDep) -> dict:
    """Add one anonymous pledge (one per device, per pledge, per city)."""
    check_rate(pledge_limiter, request)
    try:
        added = store.add_pledge(req.city, req.pledge_id, req.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown pledge") from exc
    return {"added": added, **store.summary(req.city, req.device_id)}
