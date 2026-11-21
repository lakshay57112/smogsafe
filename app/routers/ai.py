"""Gemini-backed routes: daily plan, what-if chat, local advisories and Search suggestions."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app.dependencies import GeminiDep, load_air
from app.schemas import AdvisoryOut, AskOut, AskRequest, PlanRequest
from app.security import SUGGESTIONS_CSP, ai_limiter, check_rate
from app.services.cache import TTLCache
from app.services.context import air_brief, ask_factors, compact_impacts, household_brief, with_risk
from app.services.gemini import SEARCH_BLOCKED_CODES, AIUnavailable
from app.services.household import offline_plan
from app.services.impact import plan_impacts
from app.services.planner import NOTICE_AI_BUSY, NOTICE_NO_AI, assemble_plan, plan_cache_key

log = logging.getLogger("smogsafe")
router = APIRouter(prefix="/api", tags=["ai"])

plan_cache = TTLCache(15 * 60, max_items=256)
advisory_cache = TTLCache(30 * 60)
suggestion_pages = TTLCache(60 * 60, max_items=1024)

OFFICIAL_SOURCES = [
    {"n": 1, "title": "CPCB live AQI dashboard", "uri": "https://airquality.cpcb.gov.in/AQI_India/"},
    {"n": 2, "title": "CAQM (GRAP orders for Delhi NCR)", "uri": "https://caqm.nic.in/"},
]
NO_KEY_ANSWER = (
    "The AI chat needs a Gemini API key on the server. Meanwhile, the calculators next to this chat "
    "show the impact of common choices."
)
NO_KEY_ADVISORY = (
    "Live advisories need the AI key. Meanwhile, check CPCB's Sameer app or your state pollution board "
    "for official alerts."
)
SEARCH_BLOCKED_ADVISORY = (
    "Live advisories use Google Search inside Gemini, which this API key can't use right now "
    "(free-tier keys don't include it)."
)
OFFICIAL_ALERTS_TIP = (
    "For official alerts, check CPCB's Sameer app, your State Pollution Control Board, or CAQM's GRAP orders "
    "if you're in Delhi NCR."
)


def stash_suggestions(html: str) -> str:
    """Keep Google's Search-suggestions HTML server-side and return a URL to show it in an iframe."""
    if not html:
        return ""
    token = secrets.token_urlsafe(16)
    suggestion_pages.set(token, html)
    return f"/api/suggestions/{token}"


def _with_suggestion_url(result: dict) -> dict:
    out = {k: v for k, v in result.items() if k != "suggestions_html"}
    out["suggestions_url"] = stash_suggestions(result.get("suggestions_html", ""))
    return out


@router.post("/plan")
async def plan(req: PlanRequest, request: Request, gemini: GeminiDep) -> dict:
    """Today's plan for the household: Gemini picks the actions, the impact engine adds the numbers."""
    check_rate(ai_limiter, request)
    household = req.household.model_dump()
    cache_key = plan_cache_key(req.lat, req.lon, req.place_name, household, req.language)
    if cached := plan_cache.get(cache_key):
        return cached

    air_data = await load_air(request, req.lat, req.lon)
    with_risk(household, air_data["india_aqi"]["value"])
    impacts = plan_impacts(air_data, household)

    raw, notice = None, NOTICE_NO_AI
    if gemini.available:
        context = {
            "place": req.place_name,
            "air": air_brief(air_data),
            "household": household_brief(household),
            "impacts": compact_impacts(impacts),
        }
        try:
            raw, notice = (await gemini.daily_plan(context, req.language)).model_dump(), None
        except (AIUnavailable, ValidationError, ValueError) as exc:
            log.warning("AI plan failed, using offline plan: %s", exc)
            notice = NOTICE_AI_BUSY

    mode = "ai" if raw else "offline"
    result = assemble_plan(
        raw or offline_plan(air_data, household, req.place_name), impacts, household, air_data, mode, notice
    )
    if mode == "ai":  # only cache real AI plans, so a temporary outage isn't remembered
        plan_cache.set(cache_key, result)
    return result


@router.post("/ask", response_model=AskOut)
async def ask(req: AskRequest, request: Request, gemini: GeminiDep) -> dict:
    """What-if chat grounded with Google Search, using today's air and the impact factors as context."""
    check_rate(ai_limiter, request)
    if not gemini.available:
        return {"mode": "offline", "answer": NO_KEY_ANSWER}

    air_data = await load_air(request, req.lat, req.lon)
    household = with_risk(req.household.model_dump() if req.household else None, air_data["india_aqi"]["value"])
    context = {
        "place": req.place_name,
        "air_today": air_brief(air_data),
        "household": household_brief(household),
        "precomputed_impacts": compact_impacts(plan_impacts(air_data, household or {})),
        "factors": ask_factors(),
    }
    try:
        result = await gemini.ask(req.question, context, [t.model_dump() for t in req.history], req.language)
    except AIUnavailable as exc:
        log.warning("AI ask failed: %s", exc)
        raise HTTPException(status_code=503, detail="The AI is busy right now. Please try again in a minute.") from exc
    if not result["answer"]:
        result["answer"] = "Sorry, I couldn't put together an answer for that. Try asking it a little differently."
    return {"mode": "ai", **_with_suggestion_url(result)}


@router.get("/advisories", response_model=AdvisoryOut)
async def advisories(
    request: Request,
    gemini: GeminiDep,
    city: str = Query(min_length=2, max_length=80),
    state: str = Query(default="", max_length=60),
) -> dict:
    """Latest local air-pollution advisories via Google Search grounding, cached for 30 minutes."""
    city_c, state_c = " ".join(city.split()), " ".join(state.split())
    key = (city_c.lower(), state_c.lower())
    if cached := advisory_cache.get(key):
        return cached
    if not gemini.available:
        return {"mode": "offline", "items": [NO_KEY_ADVISORY]}

    check_rate(ai_limiter, request)
    try:
        result = await gemini.advisories(city_c, state_c, datetime.now().strftime("%d %B %Y"))
    except AIUnavailable as exc:
        log.warning("Advisories failed (code %s): %s", exc.code, exc)
        reason = (
            SEARCH_BLOCKED_ADVISORY
            if exc.code in SEARCH_BLOCKED_CODES
            else "Live advisories couldn't be fetched right now."
        )
        return {"mode": "unavailable", "items": [reason, OFFICIAL_ALERTS_TIP], "sources": OFFICIAL_SOURCES}
    payload = {"mode": "ai", **_with_suggestion_url(result)}
    advisory_cache.set(key, payload)
    return payload


@router.get("/suggestions/{token}", include_in_schema=False)
def suggestions(token: str = Path(pattern=r"^[A-Za-z0-9_-]{16,32}$")) -> HTMLResponse:
    """Google Search suggestions page, isolated with its own CSP and shown in a sandboxed iframe."""
    html = suggestion_pages.get(token)
    if html is None:
        raise HTTPException(status_code=404, detail="Not found")
    page = f'<!doctype html><html><head><meta charset="utf-8"><base target="_blank"></head><body>{html}</body></html>'
    headers = {
        "Content-Security-Policy": SUGGESTIONS_CSP,
        "X-Frame-Options": "SAMEORIGIN",
        "Cache-Control": "private, max-age=3600",
    }
    return HTMLResponse(page, headers=headers)
