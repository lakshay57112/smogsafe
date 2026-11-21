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
    r = client.post(
        "/api/ask",
        json={
            **q,
            "household": HOUSEHOLD,
            "history": [{"role": "user", "text": "hi"}, {"role": "model", "text": "hello"}],
        },
    )
    body = r.json()
    assert body["mode"] == "ai"
    assert body["sources"][0]["uri"].startswith("https://")
    assert "factors" in client.app.state.gemini.last_context


def test_ask_rejects_empty_question(client):
    assert client.post("/api/ask", json={**DELHI, "question": "  "}).status_code == 422


def test_impact_endpoints(client):
    r = client.post(
        "/api/impact/commute", json={"from_mode": "car_solo", "to_mode": "bus", "km_one_way": 10, "days_per_week": 5}
    )
    assert r.status_code == 200 and r.json()["co2_saved_year_kg"] > 0
    r = client.post(
        "/api/impact/exposure",
        json={"pm25": 250, "minutes": 30, "activity": "vigorous", "to_setting": "indoors_with_purifier"},
    )
    assert r.json()["exposure_cut_pct"] == 70
    assert "sources" in client.get("/api/impact/factors").json()


def test_community_pledge_flow(client):
    device = "abcd1234-ef56-7890"
    r = client.post(
        "/api/community/pledge", json={"city": "Chandigarh", "pledge_id": "engine_off", "device_id": device}
    )
    assert r.status_code == 200 and r.json()["added"] is True
    r = client.post(
        "/api/community/pledge", json={"city": "chandigarh", "pledge_id": "engine_off", "device_id": device}
    )
    assert r.json()["added"] is False
    summary = client.get("/api/community", params={"city": "Chandigarh", "device_id": device}).json()
    assert summary["total_pledges"] == 1
    assert (
        client.post(
            "/api/community/pledge", json={"city": "Chandigarh", "pledge_id": "nope", "device_id": device}
        ).status_code
        == 400
    )


def test_advisories_offline_message(client):
    r = client.get("/api/advisories", params={"city": "Delhi"})
    assert r.status_code == 200 and r.json()["mode"] == "offline"


def test_rate_limit(client, fake_gemini):
    codes = [
        client.post("/api/ask", json={**DELHI, "question": "Is it safe to run today?"}).status_code for _ in range(15)
    ]
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


def test_extra_security_headers_and_hsts_behind_https(client):
    r = client.get("/api/health", headers={"x-forwarded-proto": "https"})
    assert r.headers["cross-origin-opener-policy"] == "same-origin"
    assert r.headers["cross-origin-resource-policy"] == "same-origin"
    assert "max-age" in r.headers["strict-transport-security"]
    assert "strict-transport-security" not in client.get("/api/health").headers


def test_responses_are_gzipped_and_static_files_cached(client):
    r = client.get("/api/air", params={"lat": 28.61, "lon": 77.21}, headers={"accept-encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/static/js/app.js").headers["cache-control"] == "public, max-age=3600"


def test_general_api_rate_limit(client, monkeypatch):
    from app.security import api_limiter

    monkeypatch.setattr(api_limiter, "limit", 3)
    codes = [client.get("/api/impact/factors").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429
    assert client.get("/api/health").status_code == 200  # health checks are never limited


def test_ai_plan_is_cached_for_identical_requests(client, fake_gemini):
    body = {**DELHI, "household": HOUSEHOLD}
    first = client.post("/api/plan", json=body).json()
    second = client.post("/api/plan", json=body).json()
    assert first == second
    assert fake_gemini.plan_calls == 1
    client.post("/api/plan", json={**body, "language": "hi"})
    assert fake_gemini.plan_calls == 2


def test_plan_falls_back_when_ai_fails(client):
    from app.services.gemini import AIUnavailable

    class Broken:
        available = True

        async def daily_plan(self, context, language):
            raise AIUnavailable("Gemini error 503", 503)

    client.app.state.gemini = Broken()
    body = client.post("/api/plan", json={**DELHI, "household": HOUSEHOLD}).json()
    assert body["mode"] == "offline"
    assert "busy" in body["notice"]


def test_geocode_endpoints_handle_upstream_errors(client, monkeypatch):
    import httpx

    from app.services import geocode

    async def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(geocode, "search_city", boom)
    monkeypatch.setattr(geocode, "reverse", boom)
    assert client.get("/api/geocode/search", params={"q": "Pune"}).status_code == 503
    assert client.get("/api/geocode/reverse", params={"lat": 18.5, "lon": 73.8}).json()["name"] == "Your location"


def test_air_endpoint_reports_upstream_outage(client, monkeypatch):
    from app import dependencies
    from app.services.air_quality import AirDataError

    async def down(*args, **kwargs):
        raise AirDataError("down")

    monkeypatch.setattr(dependencies, "get_air", down)
    r = client.get("/api/air", params={"lat": 28.6, "lon": 77.2})
    assert r.status_code == 503 and "unavailable" in r.json()["detail"]


def test_csp_has_no_unsafe_inline(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "unsafe-inline" not in csp
    assert "script-src 'self'" in csp and "style-src 'self'" in csp


def test_search_suggestions_are_served_from_an_isolated_page(client, fake_gemini):
    body = client.post("/api/ask", json={**DELHI, "question": "What if I take the metro?"}).json()
    url = body["suggestions_url"]
    assert url.startswith("/api/suggestions/") and "suggestions_html" not in body
    page = client.get(url)
    assert page.status_code == 200 and "metro co2" in page.text
    assert '<base target="_blank">' in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "SAMEORIGIN"
    assert client.get("/api/suggestions/" + "x" * 22).status_code == 404
    assert client.get("/api/suggestions/<script>").status_code in (404, 422)


def test_rate_limit_uses_the_proxy_added_ip_not_spoofed_ones():
    from types import SimpleNamespace

    from app.security import client_ip

    spoofed = SimpleNamespace(headers={"x-forwarded-for": "1.2.3.4, 203.0.113.9"}, client=None)
    direct = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.5"))
    assert client_ip(spoofed) == "203.0.113.9"
    assert client_ip(direct) == "10.0.0.5"


def test_response_models_are_documented(client):
    schemas = client.get("/api/openapi.json").json()["components"]["schemas"]
    for name in ("HealthOut", "CommuteOut", "ExposureOut", "CommunityOut", "AskOut", "AdvisoryOut"):
        assert name in schemas
