import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import tasks, agents, hitl, metrics, memory, admin, profile, flows, onboarding, notifications
from config import settings
from scheduler import scheduler_loop

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start scheduler on boot
    task = asyncio.create_task(scheduler_loop())
    logging.info("🚀 HELM API started with scheduler")
    yield
    task.cancel()


app = FastAPI(title="HELM API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "https://helm.i7b.eu", "http://localhost:5173", "http://localhost:5174", "http://localhost:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/health")
def health():
    return {"status": "ok", "scheduler": "running"}
