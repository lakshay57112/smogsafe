"""Sample winter-smog data in the same shape as Open-Meteo, for offline demos.

Only used when DEMO_MODE=true. The UI labels it as demo data.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

IST = timedelta(hours=5, minutes=30)


def _smog_curve(hour: float) -> float:
    """Winter pattern: worst late night to early morning, cleanest mid-afternoon."""
    morning = math.exp(-((hour - 7.5) ** 2) / 8)
    night = math.exp(-((hour - 22.5) ** 2) / 10) + math.exp(-((hour + 1.5) ** 2) / 10)
    afternoon_dip = math.exp(-((hour - 15) ** 2) / 6)
    return 0.75 + 0.35 * morning + 0.4 * night - 0.35 * afternoon_dip


def sample_open_meteo(lat: float, lon: float, now_utc: datetime | None = None) -> dict:
    now_utc = now_utc or datetime.now(UTC)
    now_local = now_utc + IST
    start = (now_local - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    # Small, stable variation per location so different cities don't look identical.
    base = 210 + (abs(lat * 7 + lon * 3) % 60) - 30
    times, pm25, pm10, no2, so2, o3, co = [], [], [], [], [], [], []
    for i in range(24 * 3):
        t = start + timedelta(hours=i)
        f = _smog_curve(t.hour)
        p = round(base * f, 1)
        times.append(t.strftime("%Y-%m-%dT%H:%M"))
        pm25.append(p)
        pm10.append(round(p * 1.65, 1))
        no2.append(round(55 + 30 * f, 1))
        so2.append(round(14 + 6 * f, 1))
        o3.append(round(25 + 45 * math.exp(-((t.hour - 14) ** 2) / 10), 1))
        co.append(round(1400 + 1500 * f, 1))
    return {
        "latitude": lat,
        "longitude": lon,
        "utc_offset_seconds": int(IST.total_seconds()),
        "timezone": "Asia/Kolkata",
        "hourly": {
            "time": times,
            "pm2_5": pm25,
            "pm10": pm10,
            "nitrogen_dioxide": no2,
            "sulphur_dioxide": so2,
            "ozone": o3,
            "carbon_monoxide": co,
        },
    }
