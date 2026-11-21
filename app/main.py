"""SmogSafe API + static frontend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.config import settings
from app.schemas import AskRequest, CommuteRequest, ExposureRequest, PlanRequest, PledgeRequest
from app.services import geocode
from app.services.air_quality import AirDataError, get_air
from app.services.cache import RateLimiter, TTLCache
from app.services.community import CommunityStore
from app.services.context import air_brief, ask_factors, compact_impacts, household_brief, with_risk
from app.services.gemini import SEARCH_BLOCKED_CODES, AIUnavailable, GeminiService
from app.services.household import offline_plan
from app.services.impact import commute_switch, compare_exposure, factors_table, plan_impacts
from app.services.planner import NOTICE_AI_BUSY, NOTICE_NO_AI, assemble_plan, plan_cache_key

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
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=()",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

api_limiter = RateLimiter(120, 60)  # every /api route, per client
ai_limiter = RateLimiter(settings.ai_requests_per_minute, 60)  # Gemini-backed routes
pledge_limiter = RateLimiter(20, 60)
advisory_cache = TTLCache(30 * 60)
plan_cache = TTLCache(15 * 60, max_items=256)

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
OFFICIAL_ALERTS_TIP = (
    "For official alerts, check CPCB's Sameer app, your State Pollution Control Board, or CAQM's GRAP orders "
    "if you're in Delhi NCR."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(headers={"User-Agent": "SmogSafe/1.0"}, follow_redirects=True)
    app.state.gemini = GeminiService(settings.gemini_api_key, settings.gemini_model, settings.gemini_fallback_model)
    app.state.community = CommunityStore(settings.db_path, settings.device_salt)
    if settings.device_salt_is_default:
        log.warning("DEVICE_SALT is the default value; set your own in production.")
    log.info("SmogSafe ready (AI: %s, Google AQ: %s)", settings.ai_enabled, settings.google_aq_enabled)
    yield
    await app.state.http.aclose()
    app.state.community.close()


app = FastAPI(
    title="SmogSafe API",
    description="Smog-season companion for Indian families.",
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
app.add_middleware(GZipMiddleware, minimum_size=800)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def security_and_limits(request: Request, call_next):
    path = request.url.path
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    if path.startswith("/api/") and path != "/api/health" and not api_limiter.allow(client_ip(request)):
        return JSONResponse({"detail": "Too many requests. Please wait a minute and try again."}, status_code=429)

    response = await call_next(request)
    if not path.startswith("/api/docs"):
        response.headers["Content-Security-Policy"] = CSP
    response.headers.update(SECURITY_HEADERS)
    if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


def check_rate(limiter: RateLimiter, request: Request) -> None:
    if not limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")


async def load_air(request: Request, lat: float, lon: float) -> dict:
    try:
        return await get_air(lat, lon, request.app.state.http)
    except AirDataError as exc:
        log.warning("Air data failed: %s", exc)
        detail = "Live air data is unavailable right now. Please try again shortly."
        raise HTTPException(status_code=503, detail=detail) from exc


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
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="City search is unavailable right now.") from exc


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
    return compare_exposure(
        req.pm25, req.minutes, req.activity, req.from_setting, req.to_setting, req.from_mask, req.to_mask
    )


@app.post("/api/impact/commute")
async def impact_commute(req: CommuteRequest):
    return commute_switch(req.from_mode, req.to_mode, req.km_one_way, req.days_per_week)


@app.post("/api/plan")
async def plan(req: PlanRequest, request: Request):
    check_rate(ai_limiter, request)
    household = req.household.model_dump()
    cache_key = plan_cache_key(req.lat, req.lon, req.place_name, household, req.language)
    cached = plan_cache.get(cache_key)
    if cached:
        return cached

    air_data = await load_air(request, req.lat, req.lon)
    with_risk(household, air_data["india_aqi"]["value"])
    impacts = plan_impacts(air_data, household)

    gemini: GeminiService = request.app.state.gemini
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
    raw = raw or offline_plan(air_data, household, req.place_name)
    result = assemble_plan(raw, impacts, household, air_data, mode, notice)
    if mode == "ai":  # only cache real AI plans, so a temporary outage isn't remembered
        plan_cache.set(cache_key, result)
    return result


@app.post("/api/ask")
async def ask(req: AskRequest, request: Request):
    check_rate(ai_limiter, request)
    gemini: GeminiService = request.app.state.gemini
    if not gemini.available:
        return {"mode": "offline", "answer": NO_KEY_ANSWER, "sources": [], "search_queries": [], "suggestions_html": ""}

    air_data = await load_air(request, req.lat, req.lon)
    household = with_risk(req.household.model_dump() if req.household else None, air_data["india_aqi"]["value"])
    context = {
        "place": req.place_name,
        "air_today": air_brief(air_data),
        "household": household_brief(household),
        "precomputed_impacts": compact_impacts(plan_impacts(air_data, household or {})),
        "factors": ask_factors(),
    }
    history = [t.model_dump() for t in req.history]
    try:
        result = await gemini.ask(req.question, context, history, req.language)
    except AIUnavailable as exc:
        log.warning("AI ask failed: %s", exc)
        raise HTTPException(status_code=503, detail="The AI is busy right now. Please try again in a minute.") from exc
    if not result["answer"]:
        result["answer"] = "Sorry, I couldn't put together an answer for that. Try asking it a little differently."
    return {"mode": "ai", **result}


@app.get("/api/advisories")
async def advisories(
    request: Request,
    city: str = Query(min_length=2, max_length=80),
    state: str = Query(default="", max_length=60),
):
    city_c, state_c = " ".join(city.split()), " ".join(state.split())
    key = (city_c.lower(), state_c.lower())
    cached = advisory_cache.get(key)
    if cached:
        return cached
    gemini: GeminiService = request.app.state.gemini
    if not gemini.available:
        return {"mode": "offline", "items": [NO_KEY_ADVISORY], "sources": [], "suggestions_html": ""}

    check_rate(ai_limiter, request)
    try:
        result = await gemini.advisories(city_c, state_c, datetime.now().strftime("%d %B %Y"))
    except AIUnavailable as exc:
        log.warning("Advisories failed (code %s): %s", exc.code, exc)
        reason = (
            "Live advisories use Google Search inside Gemini, which this API key can't use right now "
            "(free-tier keys don't include it)."
            if exc.code in SEARCH_BLOCKED_CODES
            else "Live advisories couldn't be fetched right now."
        )
        return {
            "mode": "unavailable",
            "items": [reason, OFFICIAL_ALERTS_TIP],
            "sources": OFFICIAL_SOURCES,
            "suggestions_html": "",
        }
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown pledge") from exc
    return {"added": added, **store.summary(req.city, req.device_id)}


# --- Frontend ------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
