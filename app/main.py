"""SmogSafe: app setup. Routes live in app/routers, security in app/security.py."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import ai, air, community, impact
from app.security import install_security
from app.services.community import CommunityStore
from app.services.gemini import GeminiService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smogsafe")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create shared clients once at startup and close them cleanly on shutdown."""
    app.state.http = httpx.AsyncClient(headers={"User-Agent": "SmogSafe/1.0"}, follow_redirects=True)
    app.state.gemini = GeminiService(settings.gemini_api_key, settings.gemini_model, settings.gemini_fallback_model)
    app.state.community = CommunityStore(settings.db_path, settings.device_salt)
    if settings.device_salt_is_default:
        log.warning("DEVICE_SALT is the default value; set your own in production.")
    log.info("SmogSafe ready (AI: %s, Google AQ: %s)", settings.ai_enabled, settings.google_aq_enabled)
    yield
    await app.state.http.aclose()
    app.state.community.close()


app = FastAPI(
    title="SmogSafe API",
    description="Smog-season companion for Indian families.",
    version="1.2.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
app.add_middleware(GZipMiddleware, minimum_size=800)
install_security(app)

for module in (air, impact, ai, community):
    app.include_router(module.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
