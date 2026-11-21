"""Impact engine: turns choices into numbers people can feel.

All maths is deterministic and lives here (not in the LLM), so every number
shown in the app can be explained and tested. Values are rough, rounded
estimates and the UI says so.
"""

from __future__ import annotations

# --- Assumptions -----------------------------------------------------------

# Berkeley Earth: breathing ~22 ug/m3 of PM2.5 for a day is roughly as harmful as 1 cigarette.
CIGARETTE_PM25_UGM3 = 22.0
# An adult breathes roughly 15 m3 of air per day, so 1 cigarette is about 330 ug of PM2.5 inhaled.
DAILY_AIR_M3 = 15.0
UG_PER_CIGARETTE = CIGARETTE_PM25_UGM3 * DAILY_AIR_M3

# Typical adult breathing rates (m3 of air per hour).
BREATHING_M3_PER_HOUR = {
    "rest": 0.5,       # sleeping, sitting
    "light": 1.0,      # walking slowly, chores, waiting at a bus stop
    "moderate": 1.6,   # brisk walk, cycling to work
    "vigorous": 3.0,   # running, sports
}

# Share of outdoor PM2.5 found in each setting (rough mid-range values).
SETTING_FACTOR = {
    "outdoors": 1.0,
    "indoors_windows_open": 0.9,
    "indoors_windows_closed": 0.6,
    "indoors_with_purifier": 0.3,
}

# Share of PM2.5 that gets past each mask in real-world use (fit matters a lot).
MASK_FACTOR = {
    "none": 1.0,
    "cloth": 0.8,
    "surgical": 0.6,
    "n95": 0.2,
}

# kg CO2 per passenger-km. Mostly from TERI's Delhi per-passenger estimates (2023).
CO2_KG_PER_PKM = {
    "car_solo": 0.140,      # TERI private car 87.7 g/pkm at 1.6 occupancy = ~140 g per car-km
    "car_pool": 0.070,      # same car shared by two people
    "cab": 0.099,           # TERI cab/taxi
    "auto": 0.064,          # TERI three-wheeler
    "two_wheeler": 0.041,   # TERI two-wheeler
    "e_two_wheeler": 0.017, # ITF: electric 2W emit ~28-57% of petrol ones
    "bus": 0.029,           # TERI DTC/cluster bus
    "metro": 0.025,         # TERI metro, midpoint of 20.7-29.3 g/pkm
    "walk_cycle": 0.0,
    "work_from_home": 0.0,
}

MODE_LABELS = {
    "car_solo": "Car (alone)",
    "car_pool": "Carpool (2 people)",
    "cab": "Cab / taxi",
    "auto": "Auto-rickshaw",
    "two_wheeler": "Petrol two-wheeler",
    "e_two_wheeler": "Electric two-wheeler",
    "bus": "Bus",
    "metro": "Metro",
    "walk_cycle": "Walk / cycle",
    "work_from_home": "Work from home",
}

SETTING_LABELS = {
    "outdoors": "outdoors",
    "indoors_windows_open": "indoors, windows open",
    "indoors_windows_closed": "indoors, windows closed",
    "indoors_with_purifier": "indoors with an air purifier",
}

MASK_LABELS = {"none": "no mask", "cloth": "a cloth mask", "surgical": "a surgical mask", "n95": "a well-fitted N95"}

SOURCES = [
    {"label": "Berkeley Earth: Air pollution and cigarette equivalence", "url": "https://berkeleyearth.org/air-pollution-and-cigarette-equivalence"},
    {"label": "TERI: Per-passenger emissions of transport modes in Delhi", "url": "https://teriin.org/sites/default/transport/Per_passenger_emission_in_Delhi_Different_Modes.pdf"},
    {"label": "ITF/OECD: Life-cycle assessment of passenger transport in India", "url": "https://www.itf-oecd.org/sites/default/files/docs/life-cycle-assessment-passenger-transport-india.pdf"},
    {"label": "CPCB: National Air Quality Index", "url": "https://cpcb.nic.in/national-air-quality-index/"},
]


# --- Core calculations ------------------------------------------------------

def cigarettes_for_day(avg_pm25: float | None) -> float | None:
    """Cigarette-equivalent of breathing this PM2.5 level for a full day."""
    if avg_pm25 is None:
        return None
    return round(max(avg_pm25, 0) / CIGARETTE_PM25_UGM3, 1)


def inhaled_dose_ug(pm25: float, minutes: float, activity: str, setting: str, mask: str = "none") -> float:
    """Micrograms of PM2.5 breathed in during an activity."""
    rate = BREATHING_M3_PER_HOUR[activity]
    effective = max(pm25, 0) * SETTING_FACTOR[setting] * MASK_FACTOR[mask]
    return effective * rate * (minutes / 60.0)


def cigarettes_from_dose(dose_ug: float) -> float:
    return dose_ug / UG_PER_CIGARETTE


def compare_exposure(
    pm25: float,
    minutes: float,
    activity: str,
    from_setting: str,
    to_setting: str,
    from_mask: str = "none",
    to_mask: str = "none",
    to_pm25: float | None = None,
) -> dict:
    """Compare two ways of doing the same activity. `to_pm25` lets the second
    option happen at a different time of day (e.g. the cleanest hours)."""
    after_pm = pm25 if to_pm25 is None else to_pm25
    before = inhaled_dose_ug(pm25, minutes, activity, from_setting, from_mask)
    after = inhaled_dose_ug(after_pm, minutes, activity, to_setting, to_mask)
    cut = before - after
    pct = round(cut / before * 100) if before > 0 else 0
    rate = BREATHING_M3_PER_HOUR[activity]
    math = (
        f"{pm25:.0f} µg/m³ × {SETTING_FACTOR[from_setting]} (setting) × {MASK_FACTOR[from_mask]} (mask) × "
        f"{rate} m³/h × {minutes / 60:.2f} h = {before:.0f} µg  →  "
        f"{after_pm:.0f} × {SETTING_FACTOR[to_setting]} × {MASK_FACTOR[to_mask]} × {rate} × {minutes / 60:.2f} = {after:.0f} µg"
    )
    return {
        "dose_before_ug": round(before),
        "dose_after_ug": round(after),
        "dose_avoided_ug": round(cut),
        "exposure_cut_pct": pct,
        "cigarettes_before": round(cigarettes_from_dose(before), 2),
        "cigarettes_after": round(cigarettes_from_dose(after), 2),
        "cigarettes_avoided": round(cigarettes_from_dose(cut), 2),
        "math": math,
        "explanation": (
            f"Doing this {SETTING_LABELS[to_setting]} with {MASK_LABELS[to_mask]} instead of "
            f"{SETTING_LABELS[from_setting]} with {MASK_LABELS[from_mask]} means breathing about "
            f"{pct}% less PM2.5 (≈{cigarettes_from_dose(cut):.2f} cigarettes avoided)."
        ),
    }


def commute_switch(from_mode: str, to_mode: str, km_one_way: float, days_per_week: int) -> dict:
    """CO2 saved by switching commute mode. Round trip = 2 × one-way distance."""
    km_week = km_one_way * 2 * days_per_week
    before_week = CO2_KG_PER_PKM[from_mode] * km_week
    after_week = CO2_KG_PER_PKM[to_mode] * km_week
    saved_week = before_week - after_week
    saved_year = saved_week * 52
    return {
        "km_per_week": round(km_week, 1),
        "co2_before_week_kg": round(before_week, 2),
        "co2_after_week_kg": round(after_week, 2),
        "co2_saved_week_kg": round(saved_week, 2),
        "co2_saved_month_kg": round(saved_week * 52 / 12, 1),
        "co2_saved_year_kg": round(saved_year, 1),
        "reduction_pct": round(saved_week / before_week * 100) if before_week > 0 else 0,
        "if_1000_people_tonnes_year": round(saved_year * 1000 / 1000, 1),
        "math": (
            f"{km_one_way:g} km × 2 × {days_per_week} days = {km_week:g} km/week. "
            f"{MODE_LABELS[from_mode]}: {CO2_KG_PER_PKM[from_mode]} kg/km → "
            f"{MODE_LABELS[to_mode]}: {CO2_KG_PER_PKM[to_mode]} kg/km. "
            f"Saved = ({CO2_KG_PER_PKM[from_mode]} − {CO2_KG_PER_PKM[to_mode]}) × {km_week:g} = {saved_week:.2f} kg/week."
        ),
        "explanation": (
            f"Switching from {MODE_LABELS[from_mode].lower()} to {MODE_LABELS[to_mode].lower()} "
            f"saves about {saved_year:.0f} kg CO₂ a year. If 1,000 people in your city did the same, "
            f"that's about {saved_year:.0f} tonnes a year, and fewer engines idling in the smog."
        ),
    }


def factors_table() -> dict:
    """Everything the UI needs for a 'How we calculate' panel."""
    return {
        "cigarette_pm25_ugm3": CIGARETTE_PM25_UGM3,
        "daily_air_m3": DAILY_AIR_M3,
        "ug_per_cigarette": UG_PER_CIGARETTE,
        "breathing_m3_per_hour": BREATHING_M3_PER_HOUR,
        "setting_factor": SETTING_FACTOR,
        "mask_factor": MASK_FACTOR,
        "co2_kg_per_pkm": CO2_KG_PER_PKM,
        "mode_labels": MODE_LABELS,
        "setting_labels": SETTING_LABELS,
        "mask_labels": MASK_LABELS,
        "sources": SOURCES,
    }


# --- Impacts attached to plan actions --------------------------------------

IMPACT_KEYS = [
    "skip_outdoor_exercise",
    "shift_to_clean_hours",
    "wear_n95",
    "close_windows",
    "use_purifier",
    "commute_switch",
    "avoid_incense",
    "avoid_burning",
    "clean_cooking",
    "none",
]

GREENER_MODE = {
    "car_solo": "metro",
    "car_pool": "metro",
    "cab": "metro",
    "auto": "bus",
    "two_wheeler": "metro",
}


def plan_impacts(air: dict, household: dict) -> dict[str, dict]:
    """Pre-compute the impact of each kind of action for this household and today's air.

    The LLM only picks which impact_key fits an action; the numbers come from here.
    """
    avg_day = (air.get("avg24") or {}).get("pm2_5") or (air.get("current") or {}).get("pm2_5") or 0
    periods = air.get("period_avgs") or {}
    pm_morning = periods.get("morning") or avg_day
    pm_night = periods.get("night") or avg_day
    best = air.get("best_window") or {}
    has_purifier = bool(household.get("has_purifier"))
    indoor_target = "indoors_with_purifier" if has_purifier else "indoors_windows_closed"
    impacts: dict[str, dict] = {}

    if avg_day > 0:
        ex = compare_exposure(pm_morning, 45, "moderate", "outdoors", indoor_target)
        impacts["skip_outdoor_exercise"] = {"label": "45 min morning workout moved indoors", "kind": "exposure", **ex}
        if best.get("avg_pm2_5") is not None and best["avg_pm2_5"] < pm_morning:
            ex = compare_exposure(pm_morning, 60, "light", "outdoors", "outdoors", to_pm25=best["avg_pm2_5"])
            impacts["shift_to_clean_hours"] = {
                "label": f"1 hour of errands moved from morning to {best.get('label', 'the cleanest hours')}",
                "kind": "exposure",
                **ex,
            }
        ex = compare_exposure(avg_day, 60, "light", "outdoors", "outdoors", "none", "n95")
        impacts["wear_n95"] = {"label": "1 hour outside with a fitted N95", "kind": "exposure", **ex}
        ex = compare_exposure(pm_night, 8 * 60, "rest", "indoors_windows_open", "indoors_windows_closed")
        impacts["close_windows"] = {"label": "Windows shut for 8 hours of sleep", "kind": "exposure", **ex}
        ex = compare_exposure(pm_night, 8 * 60, "rest", "indoors_windows_closed", "indoors_with_purifier")
        impacts["use_purifier"] = {"label": "Purifier running through the night", "kind": "exposure", **ex}

    mode = household.get("commute_mode")
    km = float(household.get("commute_km") or 0)
    days = int(household.get("commute_days") or 0)
    if mode in GREENER_MODE and km > 0 and days > 0:
        sw = commute_switch(mode, GREENER_MODE[mode], km, days)
        impacts["commute_switch"] = {
            "label": f"{MODE_LABELS[mode]} → {MODE_LABELS[GREENER_MODE[mode]]}",
            "kind": "emissions",
            **sw,
        }

    impacts["avoid_incense"] = {
        "label": "No incense, dhoop or mosquito coils indoors",
        "kind": "qualitative",
        "explanation": "Incense and coils release fine smoke right where you breathe. With windows shut in smog season, it builds up indoors.",
    }
    impacts["avoid_burning"] = {
        "label": "No burning of leaves or garbage",
        "kind": "qualitative",
        "explanation": "Open burning releases several grams of fine particles per kg burned, right at street level where kids and elders breathe it.",
    }
    impacts["clean_cooking"] = {
        "label": "Lid on, exhaust on, less deep-frying",
        "kind": "qualitative",
        "explanation": "Frying and tadka throw up a burst of fine particles. A chimney or exhaust fan with a lid on the pan removes most of it at the source.",
    }
    return impacts
