"""
Admin Analytics & Activity Log — advanced metrics for super admin dashboard.
"""
from fastapi import APIRouter, Depends
from config import settings
from supabase import create_client
from auth import AuthUser, require_super_admin
from datetime import datetime, timezone, timedelta

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@router.get("/analytics/usage")
async def global_usage(admin: AuthUser = Depends(require_super_admin), days: int = 30):
    """Global usage analytics: tasks per day, tokens per day, registrations."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # All tasks in period
    tasks = sb.table("tasks").select(
        "id, workspace_id, status, tokens_used, cost_usd, created_at"
    ).gte("created_at", since).order("created_at").execute().data

    # Group by date
    daily = {}
    for t in tasks:
        day = t["created_at"][:10]
        if day not in daily:
            daily[day] = {"date": day, "tasks": 0, "completed": 0, "failed": 0, "tokens": 0, "cost": 0}
        daily[day]["tasks"] += 1
        if t["status"] == "completed":
            daily[day]["completed"] += 1
        elif t["status"] == "failed":
            daily[day]["failed"] += 1
        daily[day]["tokens"] += t.get("tokens_used", 0) or 0
        daily[day]["cost"] += t.get("cost_usd", 0) or 0

    # Workspaces created in period (new registrations)
    workspaces = sb.table("workspaces").select("id, created_at").gte("created_at", since).execute().data
    registrations = {}
    for w in workspaces:
        day = w["created_at"][:10]
        registrations[day] = registrations.get(day, 0) + 1

    return {
        "daily": sorted(daily.values(), key=lambda x: x["date"]),
        "registrations": registrations,
        "totals": {
            "tasks": len(tasks),
            "tokens": sum(t.get("tokens_used", 0) or 0 for t in tasks),
            "cost": round(sum(t.get("cost_usd", 0) or 0 for t in tasks), 4),
            "new_clients": len(workspaces),
        }
    }


@router.get("/analytics/top-clients")
async def top_clients(admin: AuthUser = Depends(require_super_admin), limit: int = 10):
    """Top clients by token usage."""
    workspaces = sb.table("workspaces").select("id, name, plan, created_at").execute().data
    all_tasks = sb.table("tasks").select("workspace_id, tokens_used, cost_usd, status").execute().data

    clients = []
    for ws in workspaces:
        ws_tasks = [t for t in all_tasks if t["workspace_id"] == ws["id"]]
        tokens = sum(t.get("tokens_used", 0) or 0 for t in ws_tasks)
        cost = sum(t.get("cost_usd", 0) or 0 for t in ws_tasks)
        completed = len([t for t in ws_tasks if t["status"] == "completed"])
        clients.append({
            "id": ws["id"],
            "name": ws["name"],
            "plan": ws.get("plan", "free"),
            "tasks_total": len(ws_tasks),
            "tasks_completed": completed,
            "tokens_used": tokens,
            "cost_usd": round(cost, 4),
            "created_at": ws["created_at"],
        })

    clients.sort(key=lambda x: x["tokens_used"], reverse=True)
    return clients[:limit]


@router.get("/activity-log")
async def activity_log(admin: AuthUser = Depends(require_super_admin), limit: int = 50):
    """Recent activity across all workspaces."""
    events = []

    # Recent tasks
    tasks = sb.table("tasks").select(
        "id, workspace_id, user_input, status, tokens_used, created_at, completed_at"
    ).order("created_at", desc=True).limit(30).execute().data

    for t in tasks:
        # Get workspace name
        ws_name = ""
        try:
            ws = sb.table("workspaces").select("name").eq("id", t["workspace_id"]).single().execute().data
            ws_name = ws["name"] if ws else ""
        except Exception:
            pass

        events.append({
            "type": "task",
            "action": f"Tarea {t['status']}",
            "detail": t["user_input"][:100],
            "workspace": ws_name,
            "tokens": t.get("tokens_used", 0),
            "created_at": t["created_at"],
        })

    # Recent registrations
    workspaces = sb.table("workspaces").select(
        "id, name, plan, created_at"
    ).order("created_at", desc=True).limit(10).execute().data

    for ws in workspaces:
        events.append({
            "type": "registration",
            "action": "Nuevo cliente registrado",
            "detail": f"{ws['name']} (plan: {ws.get('plan', 'free')})",
            "workspace": ws["name"],
            "tokens": 0,
            "created_at": ws["created_at"],
        })

    # Sort all events by date
    events.sort(key=lambda x: x["created_at"], reverse=True)
    return events[:limit]


@router.get("/system/stats")
async def system_stats(admin: AuthUser = Depends(require_super_admin)):
    """System-wide statistics."""
    workspaces = sb.table("workspaces").select("id, plan").execute().data
    agents = sb.table("agents").select("id, is_active").execute().data
    tasks = sb.table("tasks").select("id, status").execute().data
    profiles = sb.table("profiles").select("id, is_super_admin").execute().data

    plan_dist = {}
    for ws in workspaces:
        p = ws.get("plan", "free")
        plan_dist[p] = plan_dist.get(p, 0) + 1

    return {
        "total_workspaces": len(workspaces),
        "total_agents": len(agents),
        "active_agents": len([a for a in agents if a["is_active"]]),
        "total_tasks": len(tasks),
        "tasks_by_status": {
            "completed": len([t for t in tasks if t["status"] == "completed"]),
            "running": len([t for t in tasks if t["status"] == "running"]),
            "failed": len([t for t in tasks if t["status"] == "failed"]),
            "pending": len([t for t in tasks if t["status"] == "pending"]),
        },
        "total_users": len(profiles),
        "super_admins": len([p for p in profiles if p.get("is_super_admin")]),
        "plan_distribution": plan_dist,
    }
