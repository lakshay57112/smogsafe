"""App settings, read from environment variables (see .env.example)."""

import os
from dataclasses import dataclass, field

try:  # Load a local .env file when python-dotenv is installed (handy on Windows).
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass
class Settings:
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.5-flash"))
    gemini_fallback_model: str = field(
        default_factory=lambda: _env("GEMINI_FALLBACK_MODEL", "gemini-flash-latest")
    )
    # Optional: Google Air Quality API (500 m resolution, returns the official CPCB index)
    google_maps_api_key: str = field(default_factory=lambda: _env("GOOGLE_MAPS_API_KEY"))
    db_path: str = field(default_factory=lambda: _env("DB_PATH", "data/smogsafe.db"))
    device_salt: str = field(default_factory=lambda: _env("DEVICE_SALT", "change-me-in-production"))
    contact_email: str = field(default_factory=lambda: _env("CONTACT_EMAIL", "lakshay57112@gmail.com"))
    air_cache_seconds: int = field(default_factory=lambda: int(_env("AIR_CACHE_SECONDS", "900")))
    # Demo mode serves realistic sample air data (clearly labelled) when you have no internet at a venue.
    demo_mode: bool = field(default_factory=lambda: _env("DEMO_MODE", "false").lower() in {"1", "true", "yes"})
    ai_requests_per_minute: int = field(default_factory=lambda: int(_env("AI_REQUESTS_PER_MINUTE", "12")))

    @property
    def ai_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def google_aq_enabled(self) -> bool:
        return bool(self.google_maps_api_key)


settings = Settings()
