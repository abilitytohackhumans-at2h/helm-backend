import asyncio
import logging
import time
import html
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from routers import tasks, agents, hitl, metrics, memory, admin, profile, flows, onboarding, notifications, admin_analytics, integrations, outreach, chat
from config import settings
from scheduler import scheduler_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("helm.security")

# ══════════════════════════════════════════════════════
# RATE LIMITER — Per-IP based limiting
# ══════════════════════════════════════════════════════
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(scheduler_loop())
    logging.info("🚀 HELM API started with scheduler + security hardening")
    yield
    task.cancel()


app = FastAPI(
    title="HELM API",
    version="1.0.0",
    lifespan=lifespan,
    # Hide docs in production
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ══════════════════════════════════════════════════════
# CORS — Restrictive, only allow known origins
# ══════════════════════════════════════════════════════
ALLOWED_ORIGINS = [
    "https://helm.i7b.eu",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ══════════════════════════════════════════════════════
# SECURITY HEADERS MIDDLEWARE
# ══════════════════════════════════════════════════════
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)

    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"
    # Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # XSS protection (legacy browsers)
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Force HTTPS
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    # Control referrer info leaks
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Content Security Policy
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
    # Prevent caching of sensitive data
    if "/admin" in str(request.url) or "/profile" in str(request.url):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
    # Remove server header
    response.headers["Server"] = "HELM"

    # Log slow requests (potential abuse)
    duration = time.time() - start_time
    if duration > 10:
        logger.warning(f"Slow request: {request.method} {request.url.path} took {duration:.2f}s from {request.client.host}")

    return response


# ══════════════════════════════════════════════════════
# REQUEST SIZE LIMITER — Prevent large payload attacks
# ══════════════════════════════════════════════════════
MAX_BODY_SIZE = 5 * 1024 * 1024  # 5MB

@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_SIZE:
        return JSONResponse(status_code=413, content={"detail": "Request too large"})
    return await call_next(request)


# ══════════════════════════════════════════════════════
# FAILED AUTH TRACKER — Brute force protection
# ══════════════════════════════════════════════════════
_failed_auths: dict[str, list[float]] = {}
MAX_FAILED_AUTHS = 10  # per IP
FAILED_AUTH_WINDOW = 300  # 5 minutes

@app.middleware("http")
async def brute_force_protection(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    response = await call_next(request)

    # Track 401 responses (failed auth)
    if response.status_code == 401:
        now = time.time()
        if client_ip not in _failed_auths:
            _failed_auths[client_ip] = []
        _failed_auths[client_ip].append(now)
        # Clean old entries
        _failed_auths[client_ip] = [t for t in _failed_auths[client_ip] if now - t < FAILED_AUTH_WINDOW]

        if len(_failed_auths[client_ip]) >= MAX_FAILED_AUTHS:
            logger.warning(f"🚨 Brute force detected from {client_ip}: {len(_failed_auths[client_ip])} failed auths in {FAILED_AUTH_WINDOW}s")
            return JSONResponse(status_code=429, content={"detail": "Too many failed attempts. Please try again later."})

    # Clear on successful auth
    elif response.status_code == 200 and client_ip in _failed_auths:
        _failed_auths.pop(client_ip, None)

    return response


# ══════════════════════════════════════════════════════
# GLOBAL ERROR HANDLER — Prevent info disclosure
# ══════════════════════════════════════════════════════
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."}
    )


# ══════════════════════════════════════════════════════
# INPUT SANITIZATION HELPERS (importable)
# ══════════════════════════════════════════════════════
def sanitize_string(s: str, max_length: int = 10000) -> str:
    """Sanitize user input: escape HTML, limit length, remove null bytes."""
    if not s:
        return s
    s = s.replace("\x00", "")  # Remove null bytes
    s = s[:max_length]  # Limit length
    return s


def sanitize_html(s: str, max_length: int = 10000) -> str:
    """Escape HTML entities to prevent XSS."""
    if not s:
        return s
    s = html.escape(s, quote=True)
    s = s[:max_length]
    return s


def validate_slug(slug: str) -> str:
    """Validate and clean slugs."""
    slug = slug.lower().strip()
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:100]


def validate_url(url: str) -> bool:
    """Validate URL is safe (no javascript: or data: protocols)."""
    if not url:
        return True
    dangerous = ['javascript:', 'data:', 'vbscript:', 'file:']
    return not any(url.lower().startswith(d) for d in dangerous)


# ══════════════════════════════════════════════════════
# ROUTERS
# ══════════════════════════════════════════════════════
app.include_router(tasks.router,   prefix="/tasks",   tags=["tasks"])
app.include_router(agents.router,  prefix="/agents",  tags=["agents"])
app.include_router(hitl.router,    prefix="/hitl",    tags=["hitl"])
app.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
app.include_router(memory.router, prefix="/memory",  tags=["memory"])
app.include_router(admin.router,  prefix="/admin",   tags=["admin"])
app.include_router(profile.router, prefix="/profile", tags=["profile"])
app.include_router(flows.router,  prefix="/flows",   tags=["flows"])
app.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
app.include_router(admin_analytics.router, prefix="/admin", tags=["admin-analytics"])
app.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
app.include_router(outreach.router, tags=["outreach"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])


# ══════════════════════════════════════════════════════
# HEALTH CHECK — Rate limited
# ══════════════════════════════════════════════════════
@app.get("/health")
@limiter.limit("30/minute")
async def health(request: Request):
    return {"status": "ok", "scheduler": "running", "auth": "enabled", "security": "hardened"}
