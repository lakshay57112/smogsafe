"""City search (Open-Meteo geocoding, India only) and reverse geocoding (OpenStreetMap Nominatim)."""

from __future__ import annotations

import httpx

from app.config import settings
from app.services.cache import TTLCache

SEARCH_URL = "https://geocoding-api.open-meteo.com/v1/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

_reverse_cache = TTLCache(24 * 3600)
_search_cache = TTLCache(24 * 3600)


async def search_city(query: str, client: httpx.AsyncClient) -> list[dict]:
    q = query.strip()
    cached = _search_cache.get(q.lower())
    if cached is not None:
        return cached
    params = {"name": q, "count": 6, "language": "en", "countryCode": "IN", "format": "json"}
    resp = await client.get(SEARCH_URL, params=params, timeout=8.0)
    resp.raise_for_status()
    results = []
    for r in resp.json().get("results", []) or []:
        results.append(
            {
                "name": r.get("name"),
                "state": r.get("admin1") or "",
                "district": r.get("admin2") or "",
                "lat": r.get("latitude"),
                "lon": r.get("longitude"),
            }
        )
    _search_cache.set(q.lower(), results)
    return results


def parse_reverse(data: dict) -> dict:
    addr = data.get("address") or {}
    name = (
        addr.get("city")
        or addr.get("town")
        or addr.get("municipality")
        or addr.get("state_district")
        or addr.get("county")
        or addr.get("village")
        or "Your location"
    )
    return {"name": name, "state": addr.get("state", ""), "country_code": (addr.get("country_code") or "").upper()}


async def reverse(lat: float, lon: float, client: httpx.AsyncClient) -> dict:
    key = (round(lat, 2), round(lon, 2))
    cached = _reverse_cache.get(key)
    if cached:
        return cached
    params = {"format": "jsonv2", "lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "zoom": 10, "accept-language": "en"}
    headers = {"User-Agent": f"SmogSafe/1.0 (smog companion; {settings.contact_email})"}
    resp = await client.get(REVERSE_URL, params=params, headers=headers, timeout=8.0)
    resp.raise_for_status()
    place = parse_reverse(resp.json())
    _reverse_cache.set(key, place)
    return place
