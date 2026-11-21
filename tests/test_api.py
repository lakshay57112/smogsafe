HOUSEHOLD = {
    "members": [
        {"id": "m1", "name": "Nani", "age_group": "senior", "conditions": ["asthma"]},
        {"id": "m2", "name": "Aarav", "age_group": "child"},
    ],
    "commute_mode": "car_solo",
    "commute_km": 12,
    "commute_days": 5,
    "has_purifier": False,
}
DELHI = {"lat": 28.61, "lon": 77.21, "place_name": "New Delhi"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ai_enabled"] is False


def test_index_served_with_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "SmogSafe" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_air_endpoint(client):
    r = client.get("/api/air", params={"lat": 28.61, "lon": 77.21})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "demo"
    assert body["india_aqi"]["value"] > 0
    assert len(body["forecast"]) == 24


def test_air_rejects_bad_coordinates(client):
    assert client.get("/api/air", params={"lat": 200, "lon": 77}).status_code == 422


def test_plan_offline_when_no_ai_key(client):
    r = client.post("/api/plan", json={**DELHI, "household": HOUSEHOLD})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "offline"
    assert body["notice"]
    assert {f["member_id"] for f in body["family"]} == {"m1", "m2"}
    nani = next(f for f in body["family"] if f["member_id"] == "m1")
    assert nani["risk_level"] in {"high", "very_high"}


def test_plan_with_ai_attaches_computed_impacts(client, fake_gemini):
    r = client.post("/api/plan", json={**DELHI, "household": HOUSEHOLD, "language": "hinglish"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "ai"
    commute = next(a for a in body["actions"] if a["impact_key"] == "commute_switch")
    assert commute["impact"]["co2_saved_year_kg"] > 0
    lid = next(a for a in body["actions"] if a["impact_key"] == "none")
    assert lid["impact"] is None
    # The model gets live data and pre-computed impacts, not raw guesses.
    assert "impacts" in fake_gemini.last_context
    assert fake_gemini.last_context["air"]["indian_aqi"] == body["air"]["indian_aqi"]


def test_plan_validates_household(client):
    bad = {**HOUSEHOLD, "commute_mode": "rocket"}
    assert client.post("/api/plan", json={**DELHI, "household": bad}).status_code == 422


def test_ask_offline_and_ai(client):
    q = {**DELHI, "question": "What if I take the metro 3 days a week?"}
    r = client.post("/api/ask", json=q)
    assert r.json()["mode"] == "offline"

    client.app.state.gemini = __import__("tests.conftest", fromlist=["FakeGemini"]).FakeGemini()
    r = client.post("/api/ask", json={**q, "household": HOUSEHOLD, "history": [{"role": "user", "text": "hi"}, {"role": "model", "text": "hello"}]})
    body = r.json()
    assert body["mode"] == "ai"
    assert body["sources"][0]["uri"].startswith("https://")
    assert "factors" in client.app.state.gemini.last_context


def test_ask_rejects_empty_question(client):
    assert client.post("/api/ask", json={**DELHI, "question": "  "}).status_code == 422


def test_impact_endpoints(client):
    r = client.post("/api/impact/commute", json={"from_mode": "car_solo", "to_mode": "bus", "km_one_way": 10, "days_per_week": 5})
    assert r.status_code == 200 and r.json()["co2_saved_year_kg"] > 0
    r = client.post("/api/impact/exposure", json={"pm25": 250, "minutes": 30, "activity": "vigorous", "to_setting": "indoors_with_purifier"})
    assert r.json()["exposure_cut_pct"] == 70
    assert "sources" in client.get("/api/impact/factors").json()


def test_community_pledge_flow(client):
    device = "abcd1234-ef56-7890"
    r = client.post("/api/community/pledge", json={"city": "Chandigarh", "pledge_id": "engine_off", "device_id": device})
    assert r.status_code == 200 and r.json()["added"] is True
    r = client.post("/api/community/pledge", json={"city": "chandigarh", "pledge_id": "engine_off", "device_id": device})
    assert r.json()["added"] is False
    summary = client.get("/api/community", params={"city": "Chandigarh", "device_id": device}).json()
    assert summary["total_pledges"] == 1
    assert client.post("/api/community/pledge", json={"city": "Chandigarh", "pledge_id": "nope", "device_id": device}).status_code == 400


def test_advisories_offline_message(client):
    r = client.get("/api/advisories", params={"city": "Delhi"})
    assert r.status_code == 200 and r.json()["mode"] == "offline"


def test_rate_limit(client, fake_gemini):
    codes = [client.post("/api/ask", json={**DELHI, "question": "Is it safe to run today?"}).status_code for _ in range(15)]
    assert 429 in codes


def test_large_body_rejected(client):
    r = client.post("/api/ask", content="x" * 20000, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_advisories_explain_when_search_is_blocked(client):
    from app.services.gemini import AIUnavailable

    class BlockedGemini:
        available = True

        async def advisories(self, place, state, today):
            raise AIUnavailable("Gemini error 403", 403)

    client.app.state.gemini = BlockedGemini()
    r = client.get("/api/advisories", params={"city": "Delhi", "state": "Delhi"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "unavailable"
    assert "free-tier" in body["items"][0]
    assert body["sources"][0]["uri"].startswith("https://")
