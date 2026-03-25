from fastapi import APIRouter, BackgroundTasks
from models.task import TaskRequest, TaskResponse
from config import settings
from supabase import create_client
from orchestrator import orchestrate
from datetime import datetime, timezone

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

@router.post("", response_model=TaskResponse)
async def create_task(req: TaskRequest, bg: BackgroundTasks):
    # Crear tarea en DB
    row = sb.table("tasks").insert({
        "workspace_id": req.workspace_id,
        "user_input": req.user_input,
        "status": "pending",
    }).execute()
    task = row.data[0]

    # Orquestar en background
    bg.add_task(run_orchestration, task["id"], req.user_input, req.workspace_id)

    return TaskResponse(
        id=task["id"],
        workspace_id=task["workspace_id"],
        user_input=task["user_input"],
        status=task["status"],
        created_at=task["created_at"],
    )

async def run_orchestration(task_id: str, user_input: str, workspace_id: str):
    try:
        sb.table("tasks").update({"status": "running"}).eq("id", task_id).execute()
        result = await orchestrate(user_input, workspace_id, task_id)
        sb.table("tasks").update({
            "status": result.get("status", "completed"),
            "plan_json": result.get("plan"),
            "result_json": result.get("results"),
            "assigned_agents": list(result.get("results", {}).keys()) if result.get("results") else [],
            "tokens_used": sum(r.get("tokens_used", 0) for r in result.get("results", {}).values()) if result.get("results") else 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", task_id).execute()
    except Exception as e:
        sb.table("tasks").update({"status": "failed", "result_json": {"error": str(e)}}).eq("id", task_id).execute()

@router.get("")
async def list_tasks(workspace_id: str, status: str | None = None, limit: int = 50):
    query = sb.table("tasks").select("*").eq("workspace_id", workspace_id).order("created_at", desc=True).limit(limit)
    if status:
        query = query.eq("status", status)
    return query.execute().data

@router.get("/{task_id}")
async def get_task(task_id: str):
    task = sb.table("tasks").select("*").eq("id", task_id).single().execute().data
    subtasks = sb.table("subtasks").select("*").eq("task_id", task_id).order("priority").execute().data
    return {"task": task, "subtasks": subtasks}


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    """Delete a task and its subtasks + HITL requests."""
    sb.table("subtasks").delete().eq("task_id", task_id).execute()
    try:
        sb.table("hitl_requests").delete().eq("task_id", task_id).execute()
    except Exception:
        pass
    sb.table("tasks").delete().eq("id", task_id).execute()
    return {"ok": True}
