from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.air_quality import build_snapshot, parse_google_current
from app.services.aqi_india import category_for, compute_aqi, sub_index
from app.services.community import CommunityStore
from app.services.demo import sample_open_meteo
from app.services.gemini import add_citations, extract_grounded, parse_bullets
from app.services.household import member_risk, offline_plan
from app.services.impact import (
    cigarettes_for_day,
    commute_switch,
    compare_exposure,
    plan_impacts,
)

NOW = datetime(2026, 11, 21, 9, 40, tzinfo=timezone.utc)  # 3:10 PM IST


# --- Indian AQI ---------------------------------------------------------------

@pytest.mark.parametrize(
    "pollutant,conc,expected",
    [
        ("pm2_5", 0, 0),
        ("pm2_5", 30, 50),
        ("pm2_5", 60, 100),
        ("pm2_5", 75, 150),
        ("pm2_5", 250, 400),
        ("pm2_5", 1200, 500),
        ("pm10", 100, 100),
        ("pm10", 350, 300),
        ("carbon_monoxide", 2, 100),
    ],
)
def test_sub_index_breakpoints(pollutant, conc, expected):
    assert sub_index(pollutant, conc) == expected


def test_sub_index_handles_missing_and_negative():
    assert sub_index("pm2_5", None) is None
    assert sub_index("pm2_5", -5) is None
    assert sub_index("unknown", 10) is None


@pytest.mark.parametrize("aqi,name", [(40, "Good"), (100, "Satisfactory"), (150, "Moderate"),
                                      (250, "Poor"), (350, "Very Poor"), (480, "Severe")])
def test_categories(aqi, name):
    assert category_for(aqi)["name"] == name


def test_compute_aqi_picks_worst_pollutant():
    result = compute_aqi({"pm2_5": 180, "pm10": 200, "nitrogen_dioxide": 50, "ozone": None})
    assert result["dominant"] == "pm2_5"
    assert result["category"] == "Very Poor"
    assert result["value"] == sub_index("pm2_5", 180)
    assert compute_aqi({"pm2_5": None}) is None


# --- Impact maths -------------------------------------------------------------

def test_cigarette_rule():
    assert cigarettes_for_day(22) == 1.0
    assert cigarettes_for_day(220) == 10.0
    assert cigarettes_for_day(None) is None


def test_exposure_indoors_and_mask():
    indoor = compare_exposure(200, 60, "light", "outdoors", "indoors_windows_closed")
    assert indoor["exposure_cut_pct"] == 40
    assert indoor["dose_before_ug"] == 200  # 200 µg/m3 × 1.0 m3/h × 1 h
    mask = compare_exposure(200, 60, "light", "outdoors", "outdoors", "none", "n95")
    assert mask["exposure_cut_pct"] == 80
    assert mask["cigarettes_avoided"] > 0


def test_commute_switch_numbers():
    r = commute_switch("car_solo", "metro", 10, 5)
    assert r["km_per_week"] == 100
    assert r["co2_saved_week_kg"] == pytest.approx(11.5, abs=0.01)
    assert r["co2_saved_year_kg"] == pytest.approx(598, abs=1)
    assert r["reduction_pct"] == 82


def test_plan_impacts_only_suggest_commute_switch_for_polluting_modes():
    snap = build_snapshot(sample_open_meteo(28.6, 77.2, NOW), NOW)
    car = plan_impacts(snap, {"commute_mode": "car_solo", "commute_km": 10, "commute_days": 5})
    metro = plan_impacts(snap, {"commute_mode": "metro", "commute_km": 10, "commute_days": 5})
    assert "commute_switch" in car
    assert "commute_switch" not in metro
    assert car["use_purifier"]["exposure_cut_pct"] == 50


# --- Air snapshot -------------------------------------------------------------

def test_snapshot_from_sample_data():
    snap = build_snapshot(sample_open_meteo(28.6, 77.2, NOW), NOW)
    assert snap["updated_local"] == "2026-11-21T15:00:00"
    assert len(snap["forecast"]) == 24
    assert 0 < snap["india_aqi"]["value"] <= 500
    assert snap["cigarettes_today"] == round(snap["avg24"]["pm2_5"] / 22, 1)
    best, worst = snap["best_window"], snap["worst_window"]
    assert best["avg_pm2_5"] < worst["avg_pm2_5"]
    assert 6 <= datetime.fromisoformat(best["start"]).hour <= 20


def test_snapshot_rejects_empty_data():
    from app.services.air_quality import AirDataError

    with pytest.raises(AirDataError):
        build_snapshot({"hourly": {"time": []}}, NOW)


def test_google_current_converts_ppb():
    data = {
        "indexes": [{"code": "uaqi", "aqi": 20}, {"code": "ind_cpcb", "aqi": 342, "dominantPollutant": "pm25"}],
        "pollutants": [
            {"code": "pm25", "concentration": {"value": 190.0, "units": "MICROGRAMS_PER_CUBIC_METER"}},
            {"code": "no2", "concentration": {"value": 24.45, "units": "PARTS_PER_BILLION"}},
        ],
    }
    out = parse_google_current(data)
    assert out["india_aqi"]["value"] == 342
    assert out["india_aqi"]["category"] == "Very Poor"
    assert out["current"]["pm2_5"] == 190.0
    assert out["current"]["nitrogen_dioxide"] == pytest.approx(46.0, abs=0.1)


# --- Household ------------------------------------------------------------------

def test_member_risk_is_higher_for_sensitive_people():
    adult = {"age_group": "adult", "conditions": [], "outdoor_time": "medium"}
    nani = {"age_group": "senior", "conditions": ["asthma"], "outdoor_time": "medium"}
    assert member_risk(150, adult) == "moderate"
    assert member_risk(150, nani) == "high"
    assert member_risk(40, adult) == "low"
    assert member_risk(450, adult) == "very_high"


def test_offline_plan_shape():
    snap = build_snapshot(sample_open_meteo(28.6, 77.2, NOW), NOW)
    hh = {"members": [{"id": "m1", "name": "Aarav", "age_group": "child", "conditions": [], "outdoor_time": "high"}],
          "commute_mode": "car_solo", "has_purifier": True, "cooking_fuel": "lpg", "exercises_outdoors": True}
    plan = offline_plan(snap, hh, "Delhi")
    assert 3 <= len(plan["actions"]) <= 7
    assert plan["family"][0]["member_id"] == "m1"
    assert len(plan["swaps"]) == 3
    assert all("impact_key" in a for a in plan["actions"])


# --- Gemini helpers -------------------------------------------------------------

def test_add_citations_uses_byte_offsets():
    text = "धुंध खराब है। Metro saves CO2."
    first_end = len("धुंध खराब है।".encode("utf-8"))
    supports = [
        SimpleNamespace(segment=SimpleNamespace(end_index=first_end), grounding_chunk_indices=[0]),
        SimpleNamespace(segment=SimpleNamespace(end_index=len(text.encode())), grounding_chunk_indices=[1, 0]),
    ]
    out = add_citations(text, supports, {0: 1, 1: 2})
    assert out == "धुंध खराब है।[1] Metro saves CO2.[1][2]"


def test_extract_grounded_dedupes_sources():
    web = lambda uri, title: SimpleNamespace(web=SimpleNamespace(uri=uri, title=title, domain=title))
    gm = SimpleNamespace(
        grounding_chunks=[web("https://a", "a.org"), web("https://a", "a.org"), web("https://b", "b.org")],
        grounding_supports=[SimpleNamespace(segment=SimpleNamespace(end_index=5), grounding_chunk_indices=[1, 2])],
        web_search_queries=["delhi grap"],
        search_entry_point=SimpleNamespace(rendered_content="<div>chips</div>"),
    )
    resp = SimpleNamespace(text="Hello world", candidates=[SimpleNamespace(grounding_metadata=gm)])
    out = extract_grounded(resp)
    assert [s["n"] for s in out["sources"]] == [1, 2]
    assert out["answer"] == "Hello[1][2] world"
    assert out["search_queries"] == ["delhi grap"]
    assert out["suggestions_html"] == "<div>chips</div>"


def test_parse_bullets():
    assert parse_bullets("Intro\n- One\n* Two\n2) Three") == ["One", "Two", "Three"]
    assert parse_bullets("No bullets here") == ["No bullets here"]


# --- Community store ------------------------------------------------------------

def test_pledges_are_deduplicated_per_device():
    store = CommunityStore(":memory:", "salt")
    assert store.add_pledge("delhi", "metro_2x", "device-aaaa-1111") is True
    assert store.add_pledge("Delhi ", "metro_2x", "device-aaaa-1111") is False
    assert store.add_pledge("Delhi", "metro_2x", "device-bbbb-2222") is True
    summary = store.summary("DELHI", "device-aaaa-1111")
    metro = next(p for p in summary["pledges"] if p["id"] == "metro_2x")
    assert metro["count"] == 2 and metro["pledged_by_me"] is True
    assert summary["people_pledging_co2_kg_year"] == 2 * 239
    with pytest.raises(ValueError):
        store.add_pledge("Delhi", "not-a-pledge", "device-aaaa-1111")


def test_chat_falls_back_without_search_when_grounding_is_blocked():
    import asyncio

    from google.genai import errors

    from app.services.gemini import GeminiService

    seen_tools = []

    class Models:
        async def generate_content(self, model, contents, config):
            seen_tools.append(bool(config.tools))
            if config.tools:
                raise errors.ClientError(403, {"error": {"code": 403, "message": "Search not allowed", "status": "PERMISSION_DENIED"}})
            return SimpleNamespace(text="Metro saves CO2.", candidates=[])

    svc = GeminiService("key", "model-a", "model-b")
    svc._client = SimpleNamespace(aio=SimpleNamespace(models=Models()))
    out = asyncio.run(svc.ask("What if I take the metro?", {}, [], "en"))
    assert out["grounded"] is False
    assert out["answer"] == "Metro saves CO2."
    assert seen_tools == [True, False]
