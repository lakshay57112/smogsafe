"""SmogSafe API + static frontend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.config import settings
from app.schemas import AskRequest, CommuteRequest, ExposureRequest, PlanRequest, PledgeRequest
from app.services import geocode
from app.services.air_quality import AirDataError, get_air
from app.services.cache import RateLimiter, TTLCache
from app.services.community import CommunityStore
from app.services.gemini import AIUnavailable, GeminiService
from app.services.household import member_tips, member_risk, offline_plan
from app.services.impact import (
    BREATHING_M3_PER_HOUR,
    CIGARETTE_PM25_UGM3,
    CO2_KG_PER_PKM,
    MASK_FACTOR,
    SETTING_FACTOR,
    commute_switch,
    compare_exposure,
    factors_table,
    plan_impacts,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smogsafe")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
MAX_BODY_BYTES = 16 * 1024

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; connect-src 'self'; frame-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)

ai_limiter = RateLimiter(settings.ai_requests_per_minute, 60)
pledge_limiter = RateLimiter(20, 60)
advisory_cache = TTLCache(30 * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(headers={"User-Agent": "SmogSafe/1.0"}, follow_redirects=True)
    app.state.gemini = GeminiService(settings.gemini_api_key, settings.gemini_model, settings.gemini_fallback_model)
    app.state.community = CommunityStore(settings.db_path, settings.device_salt)
    log.info("SmogSafe ready (AI: %s, Google AQ: %s)", settings.ai_enabled, settings.google_aq_enabled)
    yield
    await app.state.http.aclose()


app = FastAPI(
    title="SmogSafe API",
    description="Smog-season companion for Indian families.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def security_and_limits(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    if not request.url.path.startswith("/api/docs"):
        response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=()"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate(limiter: RateLimiter, request: Request) -> None:
    if not limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")


async def load_air(request: Request, lat: float, lon: float) -> dict:
    try:
        return await get_air(lat, lon, request.app.state.http)
    except AirDataError as exc:
        log.warning("Air data failed: %s", exc)
        raise HTTPException(status_code=503, detail="Live air data is unavailable right now. Please try again shortly.")


def air_brief(air: dict) -> dict:
    a = air["india_aqi"]
    return {
        "indian_aqi": a["value"],
        "category": a["category"],
        "health_note": a["health"],
        "dominant_pollutant": a["dominant_label"],
        "pm2_5_now_ugm3": air["current"].get("pm2_5"),
        "pm2_5_24h_avg_ugm3": air["avg24"].get("pm2_5"),
        "cigarettes_equivalent_today": air["cigarettes_today"],
        "best_window": air.get("best_window"),
        "worst_window": air.get("worst_window"),
        "next_24h_pm2_5_every_3h": [[f["hour_label"], f["pm2_5"]] for f in air["forecast"][::3]],
        "local_time": air["updated_local"],
        "data_note": "Model-based estimate; official CPCB station readings may differ.",
    }


def compact_impacts(impacts: dict) -> dict:
    keep = ("label", "kind", "exposure_cut_pct", "cigarettes_avoided", "co2_saved_year_kg", "explanation")
    return {k: {f: v[f] for f in keep if f in v} for k, v in impacts.items()}


def household_brief(household: dict | None) -> dict | None:
    if not household:
        return None
    return {
        "members": [
            {
                "member_id": m["id"],
                "name": m["name"],
                "age_group": m["age_group"],
                "conditions": m["conditions"],
                "outdoor_time": m["outdoor_time"],
                "risk_level": m.get("risk"),
            }
            for m in household.get("members", [])
        ],
        "commute": f"{household['commute_mode']}, {household['commute_km']} km one way, {household['commute_days']} days/week",
        "cooking_fuel": household["cooking_fuel"],
        "has_air_purifier": household["has_purifier"],
        "lives_near_busy_road": household["near_busy_road"],
        "exercises_outdoors": household["exercises_outdoors"],
    }


# --- Routes ------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "ai_enabled": settings.ai_enabled, "google_aq_enabled": settings.google_aq_enabled}


@app.get("/api/air")
async def air(request: Request, lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)):
    return await load_air(request, lat, lon)


@app.get("/api/geocode/search")
async def geocode_search(request: Request, q: str = Query(min_length=2, max_length=60)):
    try:
        return {"results": await geocode.search_city(q, request.app.state.http)}
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="City search is unavailable right now.")


@app.get("/api/geocode/reverse")
async def geocode_reverse(request: Request, lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)):
    try:
        return await geocode.reverse(lat, lon, request.app.state.http)
    except httpx.HTTPError:
        return {"name": "Your location", "state": "", "country_code": ""}


@app.get("/api/impact/factors")
async def impact_factors():
    return factors_table()


@app.post("/api/impact/exposure")
async def impact_exposure(req: ExposureRequest):
    return compare_exposure(req.pm25, req.minutes, req.activity, req.from_setting, req.to_setting, req.from_mask, req.to_mask)


@app.post("/api/impact/commute")
async def impact_commute(req: CommuteRequest):
    return commute_switch(req.from_mode, req.to_mode, req.km_one_way, req.days_per_week)


@app.post("/api/plan")
async def plan(req: PlanRequest, request: Request):
    check_rate(ai_limiter, request)
    air_data = await load_air(request, req.lat, req.lon)
    household = req.household.model_dump()
    aqi = air_data["india_aqi"]["value"]
    for m in household["members"]:
        m["risk"] = member_risk(aqi, m)
    impacts = plan_impacts(air_data, household)

    gemini: GeminiService = request.app.state.gemini
    mode, notice = "ai", None
    raw = None
    if gemini.available:
        context = {
            "place": req.place_name,
            "air": air_brief(air_data),
            "household": household_brief(household),
            "impacts": compact_impacts(impacts),
        }
        try:
            raw = (await gemini.daily_plan(context, req.language)).model_dump()
        except (AIUnavailable, ValidationError, ValueError) as exc:
            log.warning("AI plan failed, using offline plan: %s", exc)
            notice = "The AI is busy right now, so these are SmogSafe's built-in tips for today's air."
    else:
        notice = "AI is not configured, so these are SmogSafe's built-in tips for today's air."
    if raw is None:
        mode = "offline"
        raw = offline_plan(air_data, household, req.place_name)

    actions = []
    for a in raw["actions"][:8]:
        key = a.get("impact_key", "none")
        actions.append({**a, "impact": impacts.get(key) if key != "none" else None})

    advice = {f["member_id"]: f["advice"] for f in raw.get("family", [])}
    best_label = (air_data.get("best_window") or {}).get("label")
    family = [
        {
            "member_id": m["id"],
            "name": m["name"],
            "age_group": m["age_group"],
            "conditions": m["conditions"],
            "risk_level": m["risk"],
            "advice": (advice.get(m["id"]) or member_tips(m, aqi, best_label))[:4],
        }
        for m in household["members"]
    ]
    return {
        "mode": mode,
        "notice": notice,
        "headline": raw["headline"],
        "summary": raw["summary"],
        "actions": actions,
        "family": family,
        "indoor_checklist": raw["indoor_checklist"][:6],
        "swaps": raw["swaps"][:3],
        "air": air_brief(air_data),
        "generated_at": datetime.now().isoformat(timespec="minutes"),
    }


@app.post("/api/ask")
async def ask(req: AskRequest, request: Request):
    check_rate(ai_limiter, request)
    gemini: GeminiService = request.app.state.gemini
    if not gemini.available:
        return {
            "mode": "offline",
            "answer": "The AI chat needs a Gemini API key on the server. Meanwhile, the calculators next to this chat show the impact of common choices.",
            "sources": [],
            "search_queries": [],
            "suggestions_html": "",
        }
    air_data = await load_air(request, req.lat, req.lon)
    household = req.household.model_dump() if req.household else None
    if household:
        for m in household["members"]:
            m["risk"] = member_risk(air_data["india_aqi"]["value"], m)
    context = {
        "place": req.place_name,
        "air_today": air_brief(air_data),
        "household": household_brief(household),
        "precomputed_impacts": compact_impacts(plan_impacts(air_data, household or {})),
        "factors": {
            "cigarette_rule": f"{CIGARETTE_PM25_UGM3} µg/m³ of PM2.5 breathed for a day ≈ 1 cigarette (Berkeley Earth)",
            "co2_kg_per_passenger_km": CO2_KG_PER_PKM,
            "breathing_m3_per_hour": BREATHING_M3_PER_HOUR,
            "indoor_share_of_outdoor_pm25": SETTING_FACTOR,
            "mask_pass_through": MASK_FACTOR,
        },
    }
    history = [t.model_dump() for t in req.history]
    try:
        result = await gemini.ask(req.question, context, history, req.language)
    except AIUnavailable as exc:
        log.warning("AI ask failed: %s", exc)
        raise HTTPException(status_code=503, detail="The AI is busy right now. Please try again in a minute.")
    if not result["answer"]:
        result["answer"] = "Sorry, I couldn't put together an answer for that. Try asking it a little differently."
    return {"mode": "ai", **result}


@app.get("/api/advisories")
async def advisories(
    request: Request,
    city: str = Query(min_length=2, max_length=80),
    state: str = Query(default="", max_length=60),
):
    city_c = " ".join(city.split())
    state_c = " ".join(state.split())
    key = (city_c.lower(), state_c.lower())
    cached = advisory_cache.get(key)
    if cached:
        return cached
    gemini: GeminiService = request.app.state.gemini
    if not gemini.available:
        return {
            "mode": "offline",
            "items": ["Live advisories need the AI key. Meanwhile, check CPCB's Sameer app or your state pollution board for official alerts."],
            "sources": [],
            "suggestions_html": "",
        }
    check_rate(ai_limiter, request)
    try:
        result = await gemini.advisories(city_c, state_c, datetime.now().strftime("%d %B %Y"))
    except AIUnavailable as exc:
        log.warning("Advisories failed: %s", exc)
        raise HTTPException(status_code=503, detail="Couldn't fetch advisories right now.")
    payload = {"mode": "ai", **result}
    advisory_cache.set(key, payload)
    return payload


@app.get("/api/community")
def community(
    request: Request,
    city: str = Query(min_length=2, max_length=80),
    device_id: str | None = Query(default=None, max_length=64, pattern=r"^[A-Za-z0-9-]+$"),
):
    return request.app.state.community.summary(city, device_id)


@app.post("/api/community/pledge")
def pledge(req: PledgeRequest, request: Request):
    check_rate(pledge_limiter, request)
    store: CommunityStore = request.app.state.community
    try:
        added = store.add_pledge(req.city, req.pledge_id, req.device_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown pledge")
    return {"added": added, **store.summary(req.city, req.device_id)}


# --- Frontend ------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
