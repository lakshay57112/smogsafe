"""Indian National Air Quality Index (CPCB, 2014).

Each pollutant gets a sub-index by linear interpolation between breakpoints.
The overall AQI is the worst (highest) sub-index.
PM2.5, PM10, NO2 and SO2 use 24-hour averages; O3 and CO use 8-hour averages.
CO breakpoints are in mg/m3, everything else in ug/m3.
"""

from __future__ import annotations

INDEX_BANDS = [(0, 50), (50, 100), (100, 200), (200, 300), (300, 400), (400, 500)]

# Concentration bands that line up with INDEX_BANDS. The last band is open-ended
# in the CPCB table, so an upper value is used only to keep the scale going up to 500.
BREAKPOINTS: dict[str, list[tuple[float, float]]] = {
    "pm2_5": [(0, 30), (30, 60), (60, 90), (90, 120), (120, 250), (250, 380)],
    "pm10": [(0, 50), (50, 100), (100, 250), (250, 350), (350, 430), (430, 600)],
    "nitrogen_dioxide": [(0, 40), (40, 80), (80, 180), (180, 280), (280, 400), (400, 800)],
    "sulphur_dioxide": [(0, 40), (40, 80), (80, 380), (380, 800), (800, 1600), (1600, 2100)],
    "ozone": [(0, 50), (50, 100), (100, 168), (168, 208), (208, 748), (748, 1000)],
    "carbon_monoxide": [(0, 1), (1, 2), (2, 10), (10, 17), (17, 34), (34, 50)],  # mg/m3
}

POLLUTANT_LABELS = {
    "pm2_5": "PM2.5",
    "pm10": "PM10",
    "nitrogen_dioxide": "NO₂",
    "sulphur_dioxide": "SO₂",
    "ozone": "O₃",
    "carbon_monoxide": "CO",
}

CATEGORIES = [
    {
        "key": "good",
        "name": "Good",
        "max": 50,
        "color": "#2E7D32",
        "text_color": "#FFFFFF",
        "health": "Minimal impact. A great day to be outside.",
    },
    {
        "key": "satisfactory",
        "name": "Satisfactory",
        "max": 100,
        "color": "#7CB342",
        "text_color": "#10210A",
        "health": "Minor breathing discomfort is possible for sensitive people.",
    },
    {
        "key": "moderate",
        "name": "Moderate",
        "max": 200,
        "color": "#F9C623",
        "text_color": "#2B2100",
        "health": "Breathing discomfort for people with asthma, lung or heart disease, children and older adults.",
    },
    {
        "key": "poor",
        "name": "Poor",
        "max": 300,
        "color": "#EF6C00",
        "text_color": "#1F0E00",
        "health": "Breathing discomfort for most people on prolonged exposure.",
    },
    {
        "key": "very_poor",
        "name": "Very Poor",
        "max": 400,
        "color": "#C62828",
        "text_color": "#FFFFFF",
        "health": "Respiratory illness likely on prolonged exposure. Limit time outdoors.",
    },
    {
        "key": "severe",
        "name": "Severe",
        "max": 500,
        "color": "#5D1A1A",
        "text_color": "#FFFFFF",
        "health": "Affects healthy people and seriously impacts anyone with existing illness. Stay indoors.",
    },
]


def sub_index(pollutant: str, concentration: float | None) -> int | None:
    """Return the CPCB sub-index (0-500) for one pollutant, or None if unknown."""
    if concentration is None or pollutant not in BREAKPOINTS:
        return None
    if concentration < 0:
        return None
    bands = BREAKPOINTS[pollutant]
    for (c_lo, c_hi), (i_lo, i_hi) in zip(bands, INDEX_BANDS, strict=True):
        if concentration <= c_hi:
            value = (i_hi - i_lo) / (c_hi - c_lo) * (concentration - c_lo) + i_lo
            return round(value)
    return 500  # above the top of the scale; CPCB caps the index at 500


def category_for(aqi: int) -> dict:
    """Return the CPCB category dict for an AQI value."""
    for cat in CATEGORIES:
        if aqi <= cat["max"]:
            return cat
    return CATEGORIES[-1]


def category_index(aqi: int) -> int:
    """0 = Good ... 5 = Severe."""
    return CATEGORIES.index(category_for(aqi))


def compute_aqi(concentrations: dict[str, float | None]) -> dict | None:
    """Compute the overall Indian AQI from averaged concentrations.

    `concentrations` uses the keys in BREAKPOINTS (CO in mg/m3).
    Returns None when no pollutant has data.
    """
    subs = {p: sub_index(p, c) for p, c in concentrations.items() if p in BREAKPOINTS}
    subs = {p: v for p, v in subs.items() if v is not None}
    if not subs:
        return None
    dominant = max(subs, key=lambda p: subs[p])
    value = subs[dominant]
    cat = category_for(value)
    return {
        "value": value,
        "category": cat["name"],
        "category_key": cat["key"],
        "color": cat["color"],
        "text_color": cat["text_color"],
        "health": cat["health"],
        "dominant": dominant,
        "dominant_label": POLLUTANT_LABELS[dominant],
        "sub_indices": {POLLUTANT_LABELS[p]: v for p, v in subs.items()},
    }
