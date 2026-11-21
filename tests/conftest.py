import pytest
from fastapi.testclient import TestClient

from app.schemas import AIAction, AIChecklistItem, AIMemberAdvice, AIPlan, AISwap


class FakeGemini:
    """Stands in for Gemini so tests never call the network."""

    available = True

    def __init__(self):
        self.last_context = None
        self.plan_calls = 0

    async def daily_plan(self, context, language):
        self.last_context = context
        self.plan_calls += 1
        member_ids = [m["member_id"] for m in (context["household"] or {}).get("members", [])]
        return AIPlan(
            headline="Very poor air today, plan around 2–4 PM",
            summary="Keep mornings indoors and use the afternoon window.",
            actions=[
                AIAction(
                    time="Morning",
                    category="outdoor",
                    title="Workout indoors",
                    detail="Yoga at home.",
                    why="Morning smog is the worst.",
                    impact_key="skip_outdoor_exercise",
                ),
                AIAction(
                    time="Morning",
                    category="commute",
                    title="Take the metro",
                    detail="Leave the car.",
                    why="Fewer engines.",
                    impact_key="commute_switch",
                ),
                AIAction(
                    time="Evening",
                    category="cooking",
                    title="Lid on",
                    detail="Exhaust on.",
                    why="Less smoke.",
                    impact_key="none",
                ),
            ],
            family=[AIMemberAdvice(member_id=mid, advice=["Stay in", "N95 outside"]) for mid in member_ids],
            indoor_checklist=[AIChecklistItem(item="Wet mop", why="No dust")],
            swaps=[AISwap(swap_from="Car", swap_to="Metro", why="Less CO₂")],
        )

    async def ask(self, question, context, history, language):
        self.last_context = context
        return {
            "answer": "Taking the metro saves about **6.9 kg CO₂** a week.[1]",
            "sources": [{"n": 1, "title": "teriin.org", "uri": "https://example.org/teri"}],
            "search_queries": ["metro co2 per km delhi"],
            "suggestions_html": "<div class='chip'>metro co2</div>",
        }

    async def advisories(self, place, state, today):
        return {"items": ["GRAP Stage III in force"], "sources": [], "suggestions_html": ""}


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "google_maps_api_key", "")
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))

    from app.main import app
    from app.routers.ai import advisory_cache, plan_cache, suggestion_pages
    from app.security import ai_limiter, api_limiter, pledge_limiter
    from app.services.air_quality import clear_cache

    for limiter in (ai_limiter, api_limiter, pledge_limiter):
        limiter.reset()
    for cache in (advisory_cache, plan_cache, suggestion_pages):
        cache.clear()
    clear_cache()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_gemini(client):
    fake = FakeGemini()
    client.app.state.gemini = fake
    return fake
