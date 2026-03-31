from fastapi import APIRouter, BackgroundTasks, Depends, Request
from models.task import TaskRequest, TaskResponse
from config import settings
from supabase import create_client
from orchestrator import orchestrate
from datetime import datetime, timezone
from auth import AuthUser, get_current_user
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
limiter = Limiter(key_func=get_remote_address)

@router.post("", response_model=TaskResponse)
@limiter.limit("20/minute")
async def create_task(request: Request, req: TaskRequest, bg: BackgroundTasks, user: AuthUser = Depends(get_current_user)):
    # Verify workspace access
    from auth import require_workspace_access
    await require_workspace_access(req.workspace_id, user)

    row = sb.table("tasks").insert({
        "workspace_id": req.workspace_id,
        "user_input": req.user_input,
        "status": "pending",
    }).execute()
    task = row.data[0]
    bg.add_task(run_orchestration, task["id"], req.user_input, req.workspace_id)
    return TaskResponse(
        id=task["id"],
        workspace_id=task["workspace_id"],
        user_input=task["user_input"],
        status=task["status"],
        created_at=task["created_at"],
    )

async def fire_webhook(workspace_id: str, event: str, payload: dict):
    """Send webhook to configured URL if exists."""
    try:
        import httpx
        ws = sb.table("workspaces").select("webhook_url, webhook_secret").eq("id", workspace_id).single().execute()
        url = (ws.data or {}).get("webhook_url")
        if not url:
            return
        secret = (ws.data or {}).get("webhook_secret", "")
        import hashlib, hmac, json as j
        body = j.dumps({"event": event, "data": payload}, default=str)
        sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest() if secret else ""
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, content=body, headers={
                "Content-Type": "application/json",
                "X-HELM-Signature": sig,
                "X-HELM-Event": event,
            })
    except Exception:
        pass  # Don't fail task if webhook fails

async def run_orchestration(task_id: str, user_input: str, workspace_id: str):
    try:
        sb.table("tasks").update({"status": "running"}).eq("id", task_id).execute()
        result = await orchestrate(user_input, workspace_id, task_id)
        total_tokens = sum(r.get("tokens_used", 0) for r in result.get("results", {}).values()) if result.get("results") else 0
        cost_usd = round(total_tokens * 0.003 / 1000, 6)  # Approximate Claude Sonnet pricing
        final_status = result.get("status", "completed")
        sb.table("tasks").update({
            "status": final_status,
            "plan_json": result.get("plan"),
            "result_json": result.get("results"),
            "assigned_agents": list(result.get("results", {}).keys()) if result.get("results") else [],
            "tokens_used": total_tokens,
            "cost_usd": cost_usd,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", task_id).execute()

        # Fire webhook
        await fire_webhook(workspace_id, f"task.{final_status}", {
            "task_id": task_id,
            "status": final_status,
            "user_input": user_input,
            "tokens_used": total_tokens,
            "cost_usd": cost_usd,
        })
    except Exception as e:
        sb.table("tasks").update({"status": "failed", "result_json": {"error": str(e)}}).eq("id", task_id).execute()
        await fire_webhook(workspace_id, "task.failed", {"task_id": task_id, "error": str(e)})

@router.get("")
async def list_tasks(workspace_id: str, user: AuthUser = Depends(get_current_user), status: str | None = None, limit: int = 50):
    from auth import require_workspace_access
    await require_workspace_access(workspace_id, user)

    query = sb.table("tasks").select("*").eq("workspace_id", workspace_id).order("created_at", desc=True).limit(limit)
    if status:
        query = query.eq("status", status)
    return query.execute().data

@router.get("/{task_id}")
async def get_task(task_id: str, user: AuthUser = Depends(get_current_user)):
    task = sb.table("tasks").select("*").eq("id", task_id).single().execute().data
    if task:
        from auth import require_workspace_access
        await require_workspace_access(task["workspace_id"], user)
    subtasks = sb.table("subtasks").select("*").eq("task_id", task_id).order("priority").execute().data
    return {"task": task, "subtasks": subtasks}

@router.delete("/{task_id}")
async def delete_task(task_id: str, user: AuthUser = Depends(get_current_user)):
    task = sb.table("tasks").select("workspace_id").eq("id", task_id).single().execute().data
    if task:
        from auth import require_workspace_access
        await require_workspace_access(task["workspace_id"], user)
    sb.table("subtasks").delete().eq("task_id", task_id).execute()
    try:
        sb.table("hitl_requests").delete().eq("task_id", task_id).execute()
    except Exception:
        pass
    sb.table("tasks").delete().eq("id", task_id).execute()
    return {"ok": True}
