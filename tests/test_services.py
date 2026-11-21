"""Service-level tests with the network mocked out (httpx.MockTransport)."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.config import settings
from app.schemas import AIPlan
from app.services import air_quality, geocode
from app.services.cache import RateLimiter, TTLCache
from app.services.demo import sample_open_meteo
from app.services.gemini import AIUnavailable, GeminiService
from app.services.household import member_tips

NOW = datetime(2026, 11, 21, 9, 40, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- Geocoding ------------------------------------------------------------------


def test_city_search_parses_and_caches():
    calls = []

    def handler(request):
        calls.append(request.url)
        assert request.url.params["countryCode"] == "IN"
        results = [
            {"name": "Lucknow", "admin1": "Uttar Pradesh", "admin2": "Lucknow", "latitude": 26.8, "longitude": 80.9}
        ]
        return httpx.Response(200, json={"results": results})

    geocode._search_cache.clear()

    async def go():
        async with client_for(handler) as c:
            first = await geocode.search_city("Lucknow", c)
            second = await geocode.search_city("lucknow ", c)
            return first, second

    first, second = run(go())
    assert (
        first
        == second
        == [{"name": "Lucknow", "state": "Uttar Pradesh", "district": "Lucknow", "lat": 26.8, "lon": 80.9}]
    )
    assert len(calls) == 1


def test_reverse_geocode_sends_user_agent_and_falls_back():
    def handler(request):
        assert request.headers["user-agent"].startswith("SmogSafe/")
        return httpx.Response(200, json={"address": {"town": "Mohali", "state": "Punjab", "country_code": "in"}})

    geocode._reverse_cache.clear()

    async def go():
        async with client_for(handler) as c:
            return await geocode.reverse(30.7, 76.7, c)

    assert run(go()) == {"name": "Mohali", "state": "Punjab", "country_code": "IN"}
    assert geocode.parse_reverse({})["name"] == "Your location"


# --- Air data -------------------------------------------------------------------


@pytest.fixture
def live_mode(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "google_maps_api_key", "")
    air_quality.clear_cache()
    yield
    air_quality.clear_cache()


def test_get_air_fetches_once_then_uses_cache(live_mode):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        assert request.url.params["timezone"] == "auto"
        return httpx.Response(200, json=sample_open_meteo(28.6, 77.2))

    async def go():
        async with client_for(handler) as c:
            a = await air_quality.get_air(28.6, 77.2, c)
            b = await air_quality.get_air(28.601, 77.199, c)  # same ~1 km cell
            return a, b

    a, b = run(go())
    assert a is b
    assert calls == ["air-quality-api.open-meteo.com"]
    assert a["source"] == "open-meteo"


def test_get_air_raises_friendly_error_when_upstream_fails(live_mode):
    async def go():
        async with client_for(lambda r: httpx.Response(500)) as c:
            await air_quality.get_air(19.07, 72.87, c)

    with pytest.raises(air_quality.AirDataError):
        run(go())


def test_get_air_merges_google_cpcb_index(live_mode, monkeypatch):
    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")

    def handler(request):
        if request.url.host == "airquality.googleapis.com":
            body = json.loads(request.content)
            assert body["extraComputations"][0] == "LOCAL_AQI"
            return httpx.Response(
                200,
                json={
                    "indexes": [{"code": "ind_cpcb", "aqi": 412, "dominantPollutant": "pm25"}],
                    "pollutants": [
                        {"code": "pm25", "concentration": {"value": 260, "units": "MICROGRAMS_PER_CUBIC_METER"}}
                    ],
                },
            )
        return httpx.Response(200, json=sample_open_meteo(28.6, 77.2))

    async def go():
        async with client_for(handler) as c:
            return await air_quality.get_air(28.7, 77.1, c)

    snap = run(go())
    assert snap["india_aqi"]["value"] == 412
    assert snap["india_aqi"]["category"] == "Severe"
    assert snap["current"]["pm2_5"] == 260
    assert snap["source"] == "google+open-meteo"


def test_get_air_survives_google_failure(live_mode, monkeypatch):
    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")

    def handler(request):
        if request.url.host == "airquality.googleapis.com":
            return httpx.Response(403)
        return httpx.Response(200, json=sample_open_meteo(28.6, 77.2))

    async def go():
        async with client_for(handler) as c:
            return await air_quality.get_air(12.97, 77.59, c)

    assert run(go())["source"] == "open-meteo"


# --- Caches and limits ----------------------------------------------------------


def test_ttl_cache_expires_and_evicts(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.services.cache.time.monotonic", lambda: clock[0])
    cache = TTLCache(ttl_seconds=10, max_items=2)
    cache.set("a", 1)
    clock[0] += 1
    cache.set("b", 2)
    cache.set("c", 3)  # evicts the oldest ("a")
    assert cache.get("a") is None and cache.get("c") == 3
    clock[0] += 11
    assert cache.get("b") is None


def test_rate_limiter_window_and_memory_bound(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.services.cache.time.monotonic", lambda: clock[0])
    limiter = RateLimiter(limit=2, window=60, max_keys=2)
    assert limiter.allow("ip1") and limiter.allow("ip1")
    assert not limiter.allow("ip1")
    clock[0] += 61
    assert limiter.allow("ip1")
    assert limiter.allow("ip2")
    assert not limiter.allow("ip3")  # table full of active clients
    clock[0] += 61
    assert limiter.allow("ip3")  # idle clients were swept out


# --- Gemini service -------------------------------------------------------------

PLAN_JSON = {
    "headline": "h",
    "summary": "s",
    "actions": [
        {"time": "Morning", "category": "outdoor", "title": "t", "detail": "d", "why": "w", "impact_key": "none"}
    ],
    "family": [],
    "indoor_checklist": [],
    "swaps": [],
}


def fake_service(handler):
    svc = GeminiService("key", "primary-model", "fallback-model")

    class Models:
        async def generate_content(self, model, contents, config):
            return handler(model, config)

    svc._client = SimpleNamespace(aio=SimpleNamespace(models=Models()))
    return svc


def test_daily_plan_falls_back_to_second_model():
    models = []

    def handler(model, config):
        models.append(model)
        if model == "primary-model":
            raise errors.ClientError(404, {"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}})
        return SimpleNamespace(parsed=None, text=json.dumps(PLAN_JSON))

    plan = run(fake_service(handler).daily_plan({"a": 1}, "hi"))
    assert isinstance(plan, AIPlan)
    assert models == ["primary-model", "fallback-model"]


def test_quota_error_is_reported_with_code():
    def handler(model, config):
        raise errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})

    with pytest.raises(AIUnavailable) as info:
        run(fake_service(handler).daily_plan({}, "en"))
    assert info.value.code == 429


def test_service_without_key_is_unavailable():
    svc = GeminiService("", "m", "f")
    assert not svc.available
    with pytest.raises(AIUnavailable):
        run(svc.advisories("Delhi", "", "21 November 2026"))


def test_advisories_return_bullets_and_sources():
    def handler(model, config):
        assert config.tools  # grounded with Google Search
        chunk = SimpleNamespace(web=SimpleNamespace(uri="https://cpcb.example", title="cpcb", domain="cpcb"))
        gm = SimpleNamespace(
            grounding_chunks=[chunk], grounding_supports=[], web_search_queries=[], search_entry_point=None
        )
        return SimpleNamespace(
            text="- GRAP Stage III in force\n- Schools online", candidates=[SimpleNamespace(grounding_metadata=gm)]
        )

    out = run(fake_service(handler).advisories("Delhi", "Delhi", "21 November 2026"))
    assert out["items"] == ["GRAP Stage III in force", "Schools online"]
    assert out["sources"][0]["uri"] == "https://cpcb.example"


# --- Household tips -------------------------------------------------------------


@pytest.mark.parametrize(
    "member,aqi,expected",
    [
        ({"age_group": "adult", "conditions": ["heart"]}, 350, "chest pain"),
        ({"age_group": "adult", "conditions": ["pregnant"]}, 350, "cleanest room"),
        ({"age_group": "senior", "conditions": []}, 250, "Morning walks"),
        ({"age_group": "adult", "conditions": []}, 40, "Good time for a walk"),
        ({"age_group": "child", "conditions": []}, 150, "indoor games"),
    ],
)
def test_member_tips_cover_each_group(member, aqi, expected):
    tips = " ".join(member_tips(member, aqi, "2 PM–4 PM today"))
    assert expected in tips
