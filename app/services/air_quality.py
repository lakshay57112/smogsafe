"""Live air data for any location.

Primary source: Open-Meteo Air Quality API (free, no key; CAMS global model, ~45 km).
Optional: Google Air Quality API for current conditions (finer resolution and the
official CPCB index) when GOOGLE_MAPS_API_KEY is set. The hourly forecast always
comes from Open-Meteo.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from statistics import mean

import httpx

from app.config import settings
from app.services.aqi_india import category_for, compute_aqi, sub_index
from app.services.cache import TTLCache
from app.services.demo import sample_open_meteo
from app.services.impact import cigarettes_for_day

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GOOGLE_AQ_URL = "https://airquality.googleapis.com/v1/currentConditions:lookup"

POLLUTANTS = ["pm2_5", "pm10", "nitrogen_dioxide", "sulphur_dioxide", "ozone", "carbon_monoxide"]

# Waking hours used when looking for the cleanest / dirtiest window.
DAY_START_HOUR = 6
DAY_END_HOUR = 22
WINDOW_HOURS = 2

_cache = TTLCache(settings.air_cache_seconds)


class AirDataError(RuntimeError):
    pass


def _clean(values: list) -> list[float]:
    return [float(v) for v in values if v is not None]


def _avg(values: list) -> float | None:
    vals = _clean(values)
    return round(mean(vals), 1) if vals else None


def _hour_label(dt: datetime) -> str:
    h = dt.hour % 12 or 12
    return f"{h} {'AM' if dt.hour < 12 else 'PM'}"


def _find_window(points: list[dict], pick_min: bool, today) -> dict | None:
    """Find the 2-hour daytime window with the lowest (or highest) average PM2.5."""
    best = None
    for i in range(len(points) - WINDOW_HOURS + 1):
        chunk = points[i : i + WINDOW_HOURS]
        if any(p["pm2_5"] is None for p in chunk):
            continue
        start = chunk[0]["dt"]
        if not (DAY_START_HOUR <= start.hour <= DAY_END_HOUR - WINDOW_HOURS):
            continue
        if chunk[-1]["dt"] - start != timedelta(hours=WINDOW_HOURS - 1):
            continue
        avg = mean(p["pm2_5"] for p in chunk)
        if best is None or (avg < best[0] if pick_min else avg > best[0]):
            best = (avg, start)
    if best is None:
        return None
    avg, start = best
    end = start + timedelta(hours=WINDOW_HOURS)
    day = "today" if start.date() == today else "tomorrow"
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "label": f"{_hour_label(start)}–{_hour_label(end)} {day}",
        "avg_pm2_5": round(avg, 1),
    }


PERIOD_HOURS = {
    "morning": {6, 7, 8, 9, 10},
    "afternoon": {11, 12, 13, 14, 15, 16},
    "evening": {17, 18, 19, 20, 21},
    "night": {22, 23, 0, 1, 2, 3, 4, 5},
}


def _round(value) -> float | None:
    return round(float(value), 1) if value is not None else None


def _india_aqi_from_averages(avg24: dict, avg8: dict) -> dict:
    """CPCB uses 24-h averages for particles/NO2/SO2 and 8-h averages for O3/CO (CO in mg/m3)."""
    co_ug = avg8["carbon_monoxide"]
    inputs = {**avg24, "ozone": avg8["ozone"], "carbon_monoxide": co_ug / 1000 if co_ug is not None else None}
    india_aqi = compute_aqi(inputs)
    if india_aqi is None:
        raise AirDataError("Air data had no usable pollutant values")
    return india_aqi


def _forecast_point(time: str, stamp: datetime, pm25, pm10) -> dict:
    subs = [s for s in (sub_index("pm2_5", pm25), sub_index("pm10", pm10)) if s is not None]
    pm_index = max(subs) if subs else None
    return {
        "time": time,
        "dt": stamp,
        "hour_label": _hour_label(stamp),
        "pm2_5": _round(pm25),
        "pm_index": pm_index,
        "category_key": category_for(pm_index)["key"] if pm_index is not None else None,
    }


def build_snapshot(raw: dict, now_utc: datetime | None = None) -> dict:
    """Turn an Open-Meteo response into the app's air snapshot. Pure function (tested)."""
    hourly = raw.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise AirDataError("No hourly air data returned")

    now_utc = now_utc or datetime.now(UTC)
    now_local = (now_utc + timedelta(seconds=raw.get("utc_offset_seconds", 0))).replace(tzinfo=None)
    stamps = [datetime.fromisoformat(t) for t in times]
    idx = max((i for i, t in enumerate(stamps) if t <= now_local), default=0)  # latest hour that has started

    def series(name: str) -> list:
        return hourly.get(name) or [None] * len(times)

    def last_hours(name: str, hours: int) -> list:
        return series(name)[max(0, idx - hours + 1) : idx + 1]

    avg24 = {p: _avg(last_hours(p, 24)) for p in ("pm2_5", "pm10", "nitrogen_dioxide", "sulphur_dioxide")}
    avg8 = {p: _avg(last_hours(p, 8)) for p in ("ozone", "carbon_monoxide")}
    current_block = raw.get("current") or {}
    current = {p: _round(current_block[p] if current_block.get(p) is not None else series(p)[idx]) for p in POLLUTANTS}

    upcoming = range(idx + 1, min(idx + 25, len(times)))  # next 24 hours
    forecast = [_forecast_point(times[i], stamps[i], series("pm2_5")[i], series("pm10")[i]) for i in upcoming]
    period_avgs = {
        name: _avg([f["pm2_5"] for f in forecast if f["dt"].hour in hours]) or avg24["pm2_5"]
        for name, hours in PERIOD_HOURS.items()
    }
    best = _find_window(forecast, pick_min=True, today=now_local.date())
    worst = _find_window(forecast, pick_min=False, today=now_local.date())
    for point in forecast:
        point.pop("dt")

    return {
        "source": "open-meteo",
        "source_label": "Open-Meteo (CAMS global model, ~45 km grid)",
        "is_model_estimate": True,
        "updated_local": stamps[idx].isoformat(),
        "timezone": raw.get("timezone", "GMT"),
        "india_aqi": _india_aqi_from_averages(avg24, avg8),
        "avg24": avg24,
        "current": current,
        "cigarettes_today": cigarettes_for_day(avg24["pm2_5"]),
        "forecast": forecast,
        "period_avgs": period_avgs,
        "best_window": best,
        "worst_window": worst,
    }


async def fetch_open_meteo(lat: float, lon: float, client: httpx.AsyncClient) -> dict:
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": ",".join(POLLUTANTS),
        "current": ",".join(POLLUTANTS),
        "past_days": 1,
        "forecast_days": 2,
        "timezone": "auto",
    }
    resp = await client.get(OPEN_METEO_URL, params=params, timeout=12.0)
    resp.raise_for_status()
    return resp.json()


# Molecular weights for ppb -> ug/m3 conversion (at 25 °C: ug/m3 = ppb × MW / 24.45).
_MW = {"no2": 46.01, "o3": 48.0, "so2": 64.07, "co": 28.01}
_GOOGLE_CODES = {
    "pm25": "pm2_5",
    "pm10": "pm10",
    "no2": "nitrogen_dioxide",
    "o3": "ozone",
    "so2": "sulphur_dioxide",
    "co": "carbon_monoxide",
}


def parse_google_current(data: dict) -> dict:
    """Extract the CPCB index and pollutant concentrations (ug/m3) from a Google AQ response."""
    out: dict = {"current": {}}
    for index in data.get("indexes", []):
        if index.get("code") == "ind_cpcb" and index.get("aqi") is not None:
            value = int(index["aqi"])
            cat = category_for(value)
            dom = index.get("dominantPollutant", "")
            out["india_aqi"] = {
                "value": value,
                "category": cat["name"],
                "category_key": cat["key"],
                "color": cat["color"],
                "text_color": cat["text_color"],
                "health": cat["health"],
                "dominant": _GOOGLE_CODES.get(dom, dom),
                "dominant_label": dom.upper().replace("PM25", "PM2.5"),
                "sub_indices": {},
            }
    for pol in data.get("pollutants", []):
        key = _GOOGLE_CODES.get(pol.get("code", ""))
        conc = pol.get("concentration") or {}
        if not key or conc.get("value") is None:
            continue
        value = float(conc["value"])
        if conc.get("units") == "PARTS_PER_BILLION":
            value = value * _MW[pol["code"]] / 24.45
        out["current"][key] = round(value, 1)
    return out


async def fetch_google_current(lat: float, lon: float, client: httpx.AsyncClient) -> dict:
    body = {
        "location": {"latitude": lat, "longitude": lon},
        "extraComputations": ["LOCAL_AQI", "POLLUTANT_CONCENTRATION", "DOMINANT_POLLUTANT_CONCENTRATION"],
        "languageCode": "en",
    }
    resp = await client.post(GOOGLE_AQ_URL, params={"key": settings.google_maps_api_key}, json=body, timeout=10.0)
    resp.raise_for_status()
    return parse_google_current(resp.json())


async def get_air(lat: float, lon: float, client: httpx.AsyncClient) -> dict:
    key = (round(lat, 2), round(lon, 2))
    cached = _cache.get(key)
    if cached:
        return cached

    if settings.demo_mode:
        snapshot = build_snapshot(sample_open_meteo(lat, lon))
        snapshot["source"] = "demo"
        snapshot["source_label"] = "Demo data (sample winter smog, not live)"
        return snapshot

    # Fetch both sources at the same time when Google Air Quality is enabled.
    tasks = [fetch_open_meteo(lat, lon, client)]
    if settings.google_aq_enabled:
        tasks.append(fetch_google_current(lat, lon, client))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    raw = results[0]
    if isinstance(raw, httpx.HTTPError):
        raise AirDataError(f"Air data service unavailable: {raw.__class__.__name__}") from raw
    if isinstance(raw, BaseException):
        raise raw
    snapshot = build_snapshot(raw)

    if len(results) > 1:
        google = results[1]
        if isinstance(google, BaseException):
            log.warning("Google Air Quality lookup failed, using Open-Meteo only: %s", google)
        elif google.get("india_aqi"):
            snapshot["india_aqi"] = google["india_aqi"]
            snapshot["current"].update({k: v for k, v in google["current"].items() if v is not None})
            snapshot["source"] = "google+open-meteo"
            snapshot["source_label"] = "Google Air Quality API (now) + Open-Meteo (forecast)"

    _cache.set(key, snapshot)
    return snapshot


def clear_cache() -> None:
    _cache.clear()
