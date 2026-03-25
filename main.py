from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import tasks, agents, hitl, metrics, memory, admin, profile
from config import settings

app = FastAPI(title="HELM API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:5173", "http://localhost:5174", "http://localhost:5175"],
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


@app.get("/health")
def health():
    return {"status": "ok"}
