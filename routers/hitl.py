from fastapi import APIRouter, BackgroundTasks
from models.hitl import HITLDecision
from config import settings
from supabase import create_client
from datetime import datetime, timezone
from orchestrator import resume_after_hitl, reject_after_hitl

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@router.get("/pending")
async def get_pending(workspace_id: str):
    return sb.table("hitl_requests").select(
        "*, tasks!inner(workspace_id)"
    ).eq("tasks.workspace_id", workspace_id).eq("status", "pending").execute().data


@router.post("/{hitl_id}/approve")
async def approve(hitl_id: str, bg: BackgroundTasks, body: HITLDecision | None = None):
    # Update HITL request
    hitl = sb.table("hitl_requests").update({
        "status": "approved",
        "decision_note": body.decision_note if body else None,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", hitl_id).execute().data

    if hitl and len(hitl) > 0:
        task_id = hitl[0]["task_id"]
        # Resume orchestration in background
        bg.add_task(resume_after_hitl, task_id)

    return {"ok": True, "resumed": True}


@router.post("/{hitl_id}/reject")
async def reject(hitl_id: str, body: HITLDecision):
    hitl = sb.table("hitl_requests").update({
        "status": "rejected",
        "decision_note": body.decision_note,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", hitl_id).execute().data

    if hitl and len(hitl) > 0:
        task_id = hitl[0]["task_id"]
        await reject_after_hitl(task_id, body.decision_note or "")

    return {"ok": True, "rejected": True}
