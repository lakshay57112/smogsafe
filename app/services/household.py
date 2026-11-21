"""Per-person risk levels and the offline (rule-based) plan used when Gemini is unavailable."""

from __future__ import annotations

from app.services.aqi_india import category_index

RISK_LEVELS = ["low", "moderate", "high", "very_high"]
SENSITIVE_AGES = {"infant", "child", "senior"}


def member_risk(aqi: int, member: dict) -> str:
    """Deterministic risk: today's AQI band, bumped up for sensitive groups."""
    score = category_index(aqi)  # 0 good ... 5 severe
    if member.get("age_group") in SENSITIVE_AGES or member.get("conditions"):
        score += 1
    if member.get("outdoor_time") == "high":
        score += 1
    if score <= 1:
        return "low"
    if score == 2:
        return "moderate"
    if score == 3:
        return "high"
    return "very_high"


def member_tips(member: dict, aqi: int, best_label: str | None) -> list[str]:
    cat = category_index(aqi)
    tips: list[str] = []
    conds = set(member.get("conditions") or [])
    age = member.get("age_group")
    if cat >= 3:
        tips.append("Keep outdoor time short; if going out, wear a well-fitted N95.")
    elif cat == 2:
        tips.append("Fine to go out briefly; avoid hard exercise near traffic.")
    else:
        tips.append("Air is okay today. Good time for a walk.")
    if best_label and cat >= 2:
        tips.append(f"If you must go out, aim for {best_label}.")
    if conds & {"asthma", "copd"}:
        tips.append("Keep the reliever inhaler handy and follow the action plan from your doctor.")
    if "heart" in conds:
        tips.append("Avoid exertion outdoors; seek care for chest pain or unusual breathlessness.")
    if "pregnant" in conds:
        tips.append("Rest in the cleanest room at home; skip walks along busy roads.")
    if age in {"infant", "child"}:
        tips.append("Swap outdoor play for indoor games; kids breathe more air for their size.")
    if age == "senior":
        tips.append("Morning walks are the smoggiest; shift to indoor stretching or the cleanest hours.")
    return tips[:3]


def _item(item: str, why: str) -> dict:
    return {"item": item, "why": why}


def _swap(swap_from: str, swap_to: str, why: str) -> dict:
    return {"swap_from": swap_from, "swap_to": swap_to, "why": why}


def _time_of_day(iso_start: str | None) -> str:
    if not iso_start:
        return "Evening"
    hour = int(iso_start[11:13])
    if 5 <= hour < 12:
        return "Morning"
    if 12 <= hour < 17:
        return "Afternoon"
    if 17 <= hour < 21:
        return "Evening"
    return "Night"


def offline_plan(air: dict, household: dict, place: str) -> dict:
    """Rule-based plan with the same shape the AI returns."""
    aqi = air["india_aqi"]["value"]
    cat = category_index(aqi)
    best = (air.get("best_window") or {}).get("label")
    worst = (air.get("worst_window") or {}).get("label")
    mode = household.get("commute_mode")

    actions = []
    if cat >= 2 and household.get("exercises_outdoors", True):
        actions.append(
            {
                "time": "Morning",
                "category": "outdoor",
                "title": "Move your workout indoors",
                "detail": "Do yoga, skipping or a home workout instead of a road-side run.",
                "why": "You breathe 3x more air while running, so you pull in far more smoke.",
                "impact_key": "skip_outdoor_exercise",
            }
        )
    if best and cat >= 2:
        actions.append(
            {
                "time": "Anytime",
                "category": "outdoor",
                "title": f"Plan errands for {best}",
                "detail": "Group outdoor tasks such as shopping or the school pick-up into the cleanest window.",
                "why": "Smog is usually trapped near the ground on winter mornings and at night.",
                "impact_key": "shift_to_clean_hours",
            }
        )
    if mode in {"car_solo", "car_pool", "cab", "two_wheeler", "auto"}:
        actions.append(
            {
                "time": "Morning",
                "category": "commute",
                "title": "Take the metro or bus today",
                "detail": "If a route exists, swap one leg of your commute to public transport or a carpool.",
                "why": "Fewer engines means less smoke for everyone on your road.",
                "impact_key": "commute_switch",
            }
        )
    if cat >= 3:
        actions.append(
            {
                "time": "Anytime",
                "category": "health",
                "title": "Wear a fitted N95 outside",
                "detail": "Pinch the nose clip and check for leaks. Cloth masks barely help against PM2.5.",
                "why": "A good fit matters more than the brand.",
                "impact_key": "wear_n95",
            }
        )
    actions.append(
        {
            "time": _time_of_day((air.get("worst_window") or {}).get("start")),
            "category": "indoor",
            "title": f"Keep windows shut {'around ' + worst if worst else 'in the evening and at night'}",
            "detail": "Air out the house during the cleanest hours instead.",
            "why": "Smog gets trapped near the ground at night and in the early morning in winter.",
            "impact_key": "close_windows",
        }
    )
    if household.get("has_purifier"):
        actions.append(
            {
                "time": "Night",
                "category": "indoor",
                "title": "Run the purifier in the bedroom",
                "detail": "Close the door and run it on high for an hour, then auto through the night.",
                "why": "You spend 8 hours breathing that one room's air.",
                "impact_key": "use_purifier",
            }
        )
    actions.append(
        {
            "time": "Evening",
            "category": "cooking",
            "title": "Cook with the lid on and the exhaust running",
            "detail": "Go easy on deep-frying and tadka on smoggy days.",
            "why": "Cooking smoke adds to the outdoor smog that seeps inside.",
            "impact_key": "clean_cooking",
        }
    )
    actions.append(
        {
            "time": "Anytime",
            "category": "community",
            "title": "Say no to burning leaves or garbage",
            "detail": "Report open burning in your area on the CPCB Sameer app.",
            "why": "Street-level smoke hits kids and elders first.",
            "impact_key": "avoid_burning",
        }
    )

    family = []
    for m in household.get("members", []):
        family.append({"member_id": m["id"], "advice": member_tips(m, aqi, best)})

    checklist = [
        _item("Wet-mop floors and wipe surfaces instead of sweeping", "A dry broom kicks dust back into the air."),
        _item("Seal window gaps with tape or a door snake", "Gaps let smog leak in all night."),
        _item("No incense, dhoop or mosquito coils indoors", "They add smoke right where you breathe."),
        _item("Run the kitchen exhaust while cooking", "It removes cooking particles at the source."),
    ]
    if household.get("cooking_fuel") in {"biomass", "kerosene"}:
        checklist.insert(
            0,
            _item(
                "Cook near an open door with a chimney, or switch to LPG if possible",
                "Wood and kerosene smoke is far worse than LPG.",
            ),
        )

    swaps = [
        _swap("Morning road-side walk", "Indoor yoga or a mall walk", "Same exercise, much cleaner air."),
        _swap("Driving alone", "Metro, bus or carpool", "Cuts CO₂ and traffic smoke."),
        _swap("Burning dry leaves", "Composting them", "No smoke, and free fertiliser."),
    ]

    order = {"Morning": 0, "Afternoon": 1, "Evening": 2, "Night": 3, "Anytime": 4}
    actions.sort(key=lambda a: order[a["time"]])

    name = air["india_aqi"]["category"]
    return {
        "headline": f"{name} air in {place} today",
        "summary": (
            f"The Indian AQI is around {aqi} ({name}). {air['india_aqi']['health']} "
            + (f"The cleanest window is {best}." if best else "")
        ).strip(),
        "actions": actions[:7],
        "family": family,
        "indoor_checklist": checklist[:6],
        "swaps": swaps,
    }
