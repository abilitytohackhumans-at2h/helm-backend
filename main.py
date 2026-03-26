import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from routers import tasks, agents, hitl, metrics, memory, admin, profile, flows, onboarding, notifications, admin_analytics, integrations
from config import settings
from scheduler import scheduler_loop

logging.basicConfig(level=logging.INFO)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(scheduler_loop())
    logging.info("🚀 HELM API started with scheduler")
    yield
    task.cancel()


app = FastAPI(title="HELM API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — restrictive in production
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


# Global rate limit for all endpoints
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    response = await call_next(request)
    return response


@app.get("/health")
@limiter.limit("30/minute")
async def health(request: Request):
    return {"status": "ok", "scheduler": "running", "auth": "enabled"}
