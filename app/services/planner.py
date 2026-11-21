"""Turns a raw plan (from Gemini or the offline rules) into the API response.

Impact numbers are attached here from the deterministic impact engine, never from the model.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.services.context import air_brief
from app.services.household import member_tips

MAX_ACTIONS = 8
NOTICE_NO_AI = "AI is not configured, so these are SmogSafe's built-in tips for today's air."
NOTICE_AI_BUSY = "The AI is busy right now, so these are SmogSafe's built-in tips for today's air."


def plan_cache_key(lat: float, lon: float, place: str, household: dict, language: str) -> str:
    """Same location (to ~1 km), household and language -> same cached plan."""
    payload = {"lat": round(lat, 2), "lon": round(lon, 2), "place": place, "hh": household, "lang": language}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def assemble_plan(raw: dict, impacts: dict, household: dict, air: dict, mode: str, notice: str | None) -> dict:
    aqi = air["india_aqi"]["value"]
    actions = []
    for action in raw["actions"][:MAX_ACTIONS]:
        key = action.get("impact_key", "none")
        actions.append({**action, "impact": impacts.get(key) if key != "none" else None})

    advice = {f["member_id"]: f["advice"] for f in raw.get("family", [])}
    best_label = (air.get("best_window") or {}).get("label")
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
        "air": air_brief(air),
        "generated_at": datetime.now().isoformat(timespec="minutes"),
    }
