from fastapi import APIRouter
from config import settings
from supabase import create_client
from datetime import datetime, timedelta, timezone

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}


@router.get("/summary")
async def summary(workspace_id: str, period: str = "7d"):
    tasks = sb.table("tasks").select("*").eq("workspace_id", workspace_id).execute().data

    completed = len([t for t in tasks if t["status"] == "completed"])
    in_progress = len([t for t in tasks if t["status"] == "running"])
    tokens = sum(t.get("tokens_used", 0) for t in tasks)
    cost = tokens * 0.003 / 1000  # Approximate Claude pricing

    return {
        "completed": completed,
        "in_progress": in_progress,
        "tokens_used": tokens,
        "cost_usd": round(cost, 4),
        "total_tasks": len(tasks),
        "failed": len([t for t in tasks if t["status"] == "failed"]),
    }


@router.get("/by-agent")
async def by_agent(workspace_id: str):
    subtasks = sb.table("subtasks").select("agent_slug, tokens_used, status").execute().data

    agents: dict[str, dict] = {}
    for st in subtasks:
        slug = st["agent_slug"]
        if slug not in agents:
            agents[slug] = {"agent": slug, "tasks": 0, "tokens": 0, "completed": 0, "failed": 0}
        agents[slug]["tasks"] += 1
        agents[slug]["tokens"] += st.get("tokens_used", 0) or 0
        if st["status"] == "completed":
            agents[slug]["completed"] += 1
        elif st["status"] == "failed":
            agents[slug]["failed"] += 1

    return list(agents.values())


@router.get("/by-day")
async def by_day(workspace_id: str, period: str = "30d"):
    """Tasks and tokens grouped by day."""
    days = PERIOD_DAYS.get(period, 30)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    tasks = sb.table("tasks").select(
        "created_at, tokens_used, cost_usd, status"
    ).eq("workspace_id", workspace_id).gte(
        "created_at", since.isoformat()
    ).order("created_at").execute().data

    # Group by day
    daily: dict[str, dict] = {}
    for t in tasks:
        day = t["created_at"][:10]  # YYYY-MM-DD
        if day not in daily:
            daily[day] = {"day": day, "tasks": 0, "tokens": 0, "cost": 0, "completed": 0, "failed": 0}
        daily[day]["tasks"] += 1
        daily[day]["tokens"] += t.get("tokens_used", 0) or 0
        daily[day]["cost"] += t.get("cost_usd", 0) or 0
        if t["status"] == "completed":
            daily[day]["completed"] += 1
        elif t["status"] == "failed":
            daily[day]["failed"] += 1

    # Fill missing days
    result = []
    current = since.date()
    end = datetime.now(timezone.utc).date()
    while current <= end:
        day_str = current.isoformat()
        if day_str in daily:
            result.append(daily[day_str])
        else:
            result.append({"day": day_str, "tasks": 0, "tokens": 0, "cost": 0, "completed": 0, "failed": 0})
        current += timedelta(days=1)

    return result


@router.get("/top-tasks")
async def top_tasks(workspace_id: str, limit: int = 5):
    """Most expensive tasks by tokens."""
    tasks = sb.table("tasks").select(
        "id, user_input, tokens_used, status, created_at, assigned_agents"
    ).eq("workspace_id", workspace_id).order(
        "tokens_used", desc=True
    ).limit(limit).execute().data

    return tasks
