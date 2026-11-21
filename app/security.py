"""HTTP security: headers, request limits and rate limiting."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.cache import RateLimiter

MAX_BODY_BYTES = 16 * 1024

# No 'unsafe-inline' anywhere: scripts and styles come only from our own files.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
    "form-action 'self'; object-src 'none'"
)
# Google Search suggestions arrive as HTML with inline styles. They get their own page with
# this policy, shown in a sandboxed iframe, so the main app never needs 'unsafe-inline'.
SUGGESTIONS_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; "
    "frame-ancestors 'self'; base-uri 'self'; form-action 'none'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
TOO_MANY = "Too many requests. Please wait a minute and try again."

api_limiter = RateLimiter(120, 60)  # every /api route, per client
ai_limiter = RateLimiter(settings.ai_requests_per_minute, 60)  # Gemini-backed routes
pledge_limiter = RateLimiter(20, 60)


def client_ip(request: Request) -> str:
    """The client's address as seen by our own proxy.

    Render and Cloud Run append the real client IP as the *last* X-Forwarded-For entry.
    Earlier entries are sent by the client and can be faked, so they are ignored.
    """
    hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]
    if hops:
        return hops[-1]
    return request.client.host if request.client else "unknown"


def check_rate(limiter: RateLimiter, request: Request) -> None:
    if not limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail=TOO_MANY)


def _apply_headers(request: Request, response) -> None:
    path = request.url.path
    response.headers.update(SECURITY_HEADERS)
    if not path.startswith("/api/docs"):
        response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"


def install_security(app: FastAPI) -> None:
    """Size limit and API rate limit before the route runs; security headers after."""

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        path = request.url.path
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        if path.startswith("/api/") and path != "/api/health" and not api_limiter.allow(client_ip(request)):
            return JSONResponse({"detail": TOO_MANY}, status_code=429)
        response = await call_next(request)
        _apply_headers(request, response)
        return response
