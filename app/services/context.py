"""Compact, model-friendly summaries of live data. This is exactly what Gemini sees."""

from __future__ import annotations

from app.services.household import member_risk
from app.services.impact import (
    BREATHING_M3_PER_HOUR,
    CIGARETTE_PM25_UGM3,
    CO2_KG_PER_PKM,
    MASK_FACTOR,
    SETTING_FACTOR,
)

_IMPACT_FIELDS = ("label", "kind", "exposure_cut_pct", "cigarettes_avoided", "co2_saved_year_kg", "explanation")


def with_risk(household: dict | None, aqi: int) -> dict | None:
    """Attach a deterministic risk level to every household member."""
    if household:
        for member in household.get("members", []):
            member["risk"] = member_risk(aqi, member)
    return household


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
    """Drop the long maths strings; the model only needs labels and headline numbers."""
    return {key: {f: value[f] for f in _IMPACT_FIELDS if f in value} for key, value in impacts.items()}


def household_brief(household: dict | None) -> dict | None:
    if not household:
        return None
    commute = (
        f"{household['commute_mode']}, {household['commute_km']} km one way, {household['commute_days']} days/week"
    )
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
        "commute": commute,
        "cooking_fuel": household["cooking_fuel"],
        "has_air_purifier": household["has_purifier"],
        "lives_near_busy_road": household["near_busy_road"],
        "exercises_outdoors": household["exercises_outdoors"],
    }


def ask_factors() -> dict:
    """The same factors the impact engine uses, so chat estimates match the calculators."""
    return {
        "cigarette_rule": f"{CIGARETTE_PM25_UGM3} µg/m³ of PM2.5 breathed for a day ≈ 1 cigarette (Berkeley Earth)",
        "co2_kg_per_passenger_km": CO2_KG_PER_PKM,
        "breathing_m3_per_hour": BREATHING_M3_PER_HOUR,
        "indoor_share_of_outdoor_pm25": SETTING_FACTOR,
        "mask_pass_through": MASK_FACTOR,
    }
