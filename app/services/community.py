"""Smog Circle: anonymous city-level pledges with a shared impact counter.

No accounts and no personal data. Each browser sends a random device id, stored
only as a salted hash, so one device can't pledge the same thing twice per city.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timezone

# Yearly CO2 numbers are rough per-household estimates; the note says what was assumed.
PLEDGES = [
    {
        "id": "metro_2x",
        "icon": "🚇",
        "title": "Swap the car for metro or bus 2 days a week",
        "yearly_co2_kg": 239,
        "note": "10 km each way, car (~0.14 kg/km) → metro (~0.025 kg/km), 52 weeks.",
    },
    {
        "id": "engine_off",
        "icon": "🚦",
        "title": "Engine off at red lights longer than 10 seconds",
        "yearly_co2_kg": 91,
        "note": "~10 min less idling a day at ~0.8 L/hour, 2.27 kg CO₂ per litre of petrol, 300 days.",
    },
    {
        "id": "wfh_1x",
        "icon": "🏠",
        "title": "Work or study from home 1 day a week, if you can",
        "yearly_co2_kg": 146,
        "note": "10 km each way by car, 52 days a year.",
    },
    {
        "id": "puc_tyres",
        "icon": "🛞",
        "title": "Keep PUC valid and tyres properly inflated",
        "yearly_co2_kg": 42,
        "note": "~3% better fuel use on 10,000 km a year by car.",
    },
    {
        "id": "no_burning",
        "icon": "🔥",
        "title": "Never burn leaves, garbage or crop waste",
        "yearly_co2_kg": None,
        "note": "Removes one of the biggest street-level smoke sources in winter.",
    },
    {
        "id": "report_burning",
        "icon": "📣",
        "title": "Report open burning on the CPCB Sameer app",
        "yearly_co2_kg": None,
        "note": "Complaints go to the local authority, who can act on the smoke.",
    },
    {
        "id": "no_incense",
        "icon": "🕯️",
        "title": "No incense or mosquito coils indoors on smog days",
        "yearly_co2_kg": None,
        "note": "Keeps indoor air cleaner for kids and elders while windows are shut.",
    },
]
PLEDGE_IDS = {p["id"] for p in PLEDGES}


class CommunityStore:
    def __init__(self, db_path: str, salt: str):
        self.db_path = db_path
        self.salt = salt
        self._lock = threading.Lock()
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS pledges (
                city TEXT NOT NULL,
                pledge_id TEXT NOT NULL,
                device_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(city, pledge_id, device_hash)
            )"""
        )
        self._conn.commit()

    @staticmethod
    def normalise_city(city: str) -> str:
        return " ".join(city.strip().split()).title()[:80]

    def _hash(self, device_id: str) -> str:
        return hashlib.sha256(f"{self.salt}:{device_id}".encode()).hexdigest()

    def add_pledge(self, city: str, pledge_id: str, device_id: str) -> bool:
        """Returns True if this was a new pledge, False if the device already made it."""
        if pledge_id not in PLEDGE_IDS:
            raise ValueError("Unknown pledge")
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO pledges VALUES (?, ?, ?, ?)",
                (self.normalise_city(city), pledge_id, self._hash(device_id), datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def summary(self, city: str, device_id: str | None = None) -> dict:
        city_n = self.normalise_city(city)
        with self._lock:
            rows = self._conn.execute(
                "SELECT pledge_id, COUNT(*) FROM pledges WHERE city = ? GROUP BY pledge_id", (city_n,)
            ).fetchall()
            mine = set()
            if device_id:
                mine = {
                    r[0]
                    for r in self._conn.execute(
                        "SELECT pledge_id FROM pledges WHERE city = ? AND device_hash = ?",
                        (city_n, self._hash(device_id)),
                    ).fetchall()
                }
        counts = dict(rows)
        pledges = []
        total_co2 = 0.0
        for p in PLEDGES:
            n = counts.get(p["id"], 0)
            if p["yearly_co2_kg"]:
                total_co2 += n * p["yearly_co2_kg"]
            pledges.append({**p, "count": n, "pledged_by_me": p["id"] in mine})
        return {
            "city": city_n,
            "total_pledges": sum(counts.values()),
            "people_pledging_co2_kg_year": round(total_co2),
            "pledges": pledges,
        }
