"""Deterministic impact calculators (no AI involved)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import CommuteOut, CommuteRequest, ExposureOut, ExposureRequest
from app.services.impact import commute_switch, compare_exposure, factors_table

router = APIRouter(prefix="/api/impact", tags=["impact"])


@router.get("/factors")
async def impact_factors() -> dict:
    """Every factor and source used in the impact maths (powers the "How we calculate" panel)."""
    return factors_table()


@router.post("/exposure", response_model=ExposureOut)
async def impact_exposure(req: ExposureRequest) -> dict:
    """PM2.5 breathed in two ways of doing the same activity, plus cigarette equivalents."""
    return compare_exposure(
        req.pm25, req.minutes, req.activity, req.from_setting, req.to_setting, req.from_mask, req.to_mask
    )


@router.post("/commute", response_model=CommuteOut)
async def impact_commute(req: CommuteRequest) -> dict:
    """CO₂ saved by switching commute mode, per week, month and year."""
    return commute_switch(req.from_mode, req.to_mode, req.km_one_way, req.days_per_week)
