"""Per-person risk levels and the offline (rule-based) plan used when Gemini is unavailable."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.services.aqi_india import category_index

SENSITIVE_AGES = {"infant", "child", "senior"}
POLLUTING_MODES = {"car_solo", "car_pool", "cab", "two_wheeler", "auto"}
TIME_ORDER = {"Morning": 0, "Afternoon": 1, "Evening": 2, "Night": 3, "Anytime": 4}
MAX_OFFLINE_ACTIONS = 7

# AQI band index (0 good ... 5 severe) at which each kind of advice starts to apply.
MODERATE, POOR = 2, 3


def member_risk(aqi: int, member: dict) -> str:
    """Deterministic risk: today's AQI band, bumped up for sensitive groups and lots of time outdoors."""
    score = category_index(aqi)
    if member.get("age_group") in SENSITIVE_AGES or member.get("conditions"):
        score += 1
    if member.get("outdoor_time") == "high":
        score += 1
    if score <= 1:
        return "low"
    return {2: "moderate", 3: "high"}.get(score, "very_high")


def member_tips(member: dict, aqi: int, best_label: str | None) -> list[str]:
    """Up to three short tips for one person, used when the AI didn't return advice for them."""
    cat = category_index(aqi)
    conditions = set(member.get("conditions") or [])
    age = member.get("age_group")
    if cat >= POOR:
        tips = ["Keep outdoor time short; if going out, wear a well-fitted N95."]
    elif cat == MODERATE:
        tips = ["Fine to go out briefly; avoid hard exercise near traffic."]
    else:
        tips = ["Air is okay today. Good time for a walk."]
    rules = [
        (bool(best_label) and cat >= MODERATE, f"If you must go out, aim for {best_label}."),
        (
            bool(conditions & {"asthma", "copd"}),
            "Keep the reliever inhaler handy and follow the action plan from your doctor.",
        ),
        ("heart" in conditions, "Avoid exertion outdoors; seek care for chest pain or unusual breathlessness."),
        ("pregnant" in conditions, "Rest in the cleanest room at home; skip walks along busy roads."),
        (age in {"infant", "child"}, "Swap outdoor play for indoor games; kids breathe more air for their size."),
        (age == "senior", "Morning walks are the smoggiest; shift to indoor stretching or the cleanest hours."),
    ]
    tips += [tip for applies, tip in rules if applies]
    return tips[:3]


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


def _action(time: str, category: str, title: str, detail: str, why: str, impact_key: str) -> dict:
    return {"time": time, "category": category, "title": title, "detail": detail, "why": why, "impact_key": impact_key}


@dataclass(frozen=True)
class ActionRule:
    """One offline tip: when it applies (given today's context) and how to word it."""

    applies: Callable[[dict], bool]
    build: Callable[[dict], dict]


OFFLINE_RULES = [
    ActionRule(
        lambda c: c["cat"] >= MODERATE and c["household"].get("exercises_outdoors", True),
        lambda c: _action(
            "Morning",
            "outdoor",
            "Move your workout indoors",
            "Do yoga, skipping or a home workout instead of a road-side run.",
            "You breathe 3x more air while running, so you pull in far more smoke.",
            "skip_outdoor_exercise",
        ),
    ),
    ActionRule(
        lambda c: bool(c["best"]) and c["cat"] >= MODERATE,
        lambda c: _action(
            "Anytime",
            "outdoor",
            f"Plan errands for {c['best']}",
            "Group outdoor tasks such as shopping or the school pick-up into the cleanest window.",
            "Smog is usually trapped near the ground on winter mornings and at night.",
            "shift_to_clean_hours",
        ),
    ),
    ActionRule(
        lambda c: c["household"].get("commute_mode") in POLLUTING_MODES,
        lambda c: _action(
            "Morning",
            "commute",
            "Take the metro or bus today",
            "If a route exists, swap one leg of your commute to public transport or a carpool.",
            "Fewer engines means less smoke for everyone on your road.",
            "commute_switch",
        ),
    ),
    ActionRule(
        lambda c: c["cat"] >= POOR,
        lambda c: _action(
            "Anytime",
            "health",
            "Wear a fitted N95 outside",
            "Pinch the nose clip and check for leaks. Cloth masks barely help against PM2.5.",
            "A good fit matters more than the brand.",
            "wear_n95",
        ),
    ),
    ActionRule(
        lambda c: True,
        lambda c: _action(
            _time_of_day(c["worst_start"]),
            "indoor",
            f"Keep windows shut {'around ' + c['worst'] if c['worst'] else 'in the evening and at night'}",
            "Air out the house during the cleanest hours instead.",
            "Smog gets trapped near the ground at night and in the early morning in winter.",
            "close_windows",
        ),
    ),
    ActionRule(
        lambda c: bool(c["household"].get("has_purifier")),
        lambda c: _action(
            "Night",
            "indoor",
            "Run the purifier in the bedroom",
            "Close the door and run it on high for an hour, then auto through the night.",
            "You spend 8 hours breathing that one room's air.",
            "use_purifier",
        ),
    ),
    ActionRule(
        lambda c: True,
        lambda c: _action(
            "Evening",
            "cooking",
            "Cook with the lid on and the exhaust running",
            "Go easy on deep-frying and tadka on smoggy days.",
            "Cooking smoke adds to the outdoor smog that seeps inside.",
            "clean_cooking",
        ),
    ),
    ActionRule(
        lambda c: True,
        lambda c: _action(
            "Anytime",
            "community",
            "Say no to burning leaves or garbage",
            "Report open burning in your area on the CPCB Sameer app.",
            "Street-level smoke hits kids and elders first.",
            "avoid_burning",
        ),
    ),
]


def offline_actions(air: dict, household: dict) -> list[dict]:
    """Pick the rules that apply to today's air and this household, ordered through the day."""
    worst = air.get("worst_window") or {}
    context = {
        "cat": category_index(air["india_aqi"]["value"]),
        "best": (air.get("best_window") or {}).get("label"),
        "worst": worst.get("label"),
        "worst_start": worst.get("start"),
        "household": household,
    }
    actions = [rule.build(context) for rule in OFFLINE_RULES if rule.applies(context)]
    return sorted(actions, key=lambda a: TIME_ORDER[a["time"]])[:MAX_OFFLINE_ACTIONS]


BASE_CHECKLIST = [
    {
        "item": "Wet-mop floors and wipe surfaces instead of sweeping",
        "why": "A dry broom kicks dust back into the air.",
    },
    {"item": "Seal window gaps with tape or a door snake", "why": "Gaps let smog leak in all night."},
    {"item": "No incense, dhoop or mosquito coils indoors", "why": "They add smoke right where you breathe."},
    {"item": "Run the kitchen exhaust while cooking", "why": "It removes cooking particles at the source."},
]
SOLID_FUEL_TIP = {
    "item": "Cook near an open door with a chimney, or switch to LPG if possible",
    "why": "Wood and kerosene smoke is far worse than LPG.",
}
OFFLINE_SWAPS = [
    {
        "swap_from": "Morning road-side walk",
        "swap_to": "Indoor yoga or a mall walk",
        "why": "Same exercise, much cleaner air.",
    },
    {"swap_from": "Driving alone", "swap_to": "Metro, bus or carpool", "why": "Cuts CO₂ and traffic smoke."},
    {"swap_from": "Burning dry leaves", "swap_to": "Composting them", "why": "No smoke, and free fertiliser."},
]


def offline_checklist(household: dict) -> list[dict]:
    extra = [SOLID_FUEL_TIP] if household.get("cooking_fuel") in {"biomass", "kerosene"} else []
    return (extra + BASE_CHECKLIST)[:6]


def offline_plan(air: dict, household: dict, place: str) -> dict:
    """Rule-based plan with the same shape the AI returns, so the app works without Gemini."""
    aqi_info = air["india_aqi"]
    best = (air.get("best_window") or {}).get("label")
    summary = f"The Indian AQI is around {aqi_info['value']} ({aqi_info['category']}). {aqi_info['health']}"
    if best:
        summary += f" The cleanest window is {best}."
    return {
        "headline": f"{aqi_info['category']} air in {place} today",
        "summary": summary,
        "actions": offline_actions(air, household),
        "family": [
            {"member_id": m["id"], "advice": member_tips(m, aqi_info["value"], best)}
            for m in household.get("members", [])
        ],
        "indoor_checklist": offline_checklist(household),
        "swaps": OFFLINE_SWAPS,
    }
