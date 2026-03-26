from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from models.flow import FlowCreate, FlowUpdate
from config import settings
from supabase import create_client
from orchestrator import orchestrate
from datetime import datetime, timezone
from auth import AuthUser, get_current_user

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@router.get("")
async def list_flows(workspace_id: str, user: AuthUser = Depends(get_current_user)):
    from auth import require_workspace_access
    await require_workspace_access(workspace_id, user)
    return sb.table("scheduled_flows").select("*").eq("workspace_id", workspace_id).order("created_at", desc=True).execute().data


@router.post("")
async def create_flow(req: FlowCreate, user: AuthUser = Depends(get_current_user)):
    row = sb.table("scheduled_flows").insert({
        "workspace_id": req.workspace_id,
        "name": req.name,
        "prompt": req.prompt,
        "cron_expression": req.cron_expression,
    }).execute()
    return row.data[0]


@router.patch("/{flow_id}")
async def update_flow(flow_id: str, req: FlowUpdate, user: AuthUser = Depends(get_current_user)):
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No hay campos para actualizar")
    sb.table("scheduled_flows").update(updates).eq("id", flow_id).execute()
    return sb.table("scheduled_flows").select("*").eq("id", flow_id).single().execute().data


@router.delete("/{flow_id}")
async def delete_flow(flow_id: str, user: AuthUser = Depends(get_current_user)):
    sb.table("scheduled_flows").delete().eq("id", flow_id).execute()
    return {"ok": True}


@router.post("/{flow_id}/run-now")
async def run_flow_now(flow_id: str, bg: BackgroundTasks, user: AuthUser = Depends(get_current_user)):
    """Ejecutar un flujo manualmente creando una tarea."""
    flow = sb.table("scheduled_flows").select("*").eq("id", flow_id).single().execute().data
    if not flow:
        raise HTTPException(404, "Flujo no encontrado")

    # Crear tarea con el prompt del flujo
    row = sb.table("tasks").insert({
        "workspace_id": flow["workspace_id"],
        "user_input": f"[Flujo: {flow['name']}] {flow['prompt']}",
        "status": "pending",
    }).execute()
    task = row.data[0]

    # Actualizar last_run_at
    sb.table("scheduled_flows").update({
        "last_run_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", flow_id).execute()

    # Orquestar en background
    bg.add_task(run_flow_orchestration, task["id"], flow["prompt"], flow["workspace_id"])

    return {"ok": True, "task_id": task["id"]}


async def run_flow_orchestration(task_id: str, prompt: str, workspace_id: str):
    try:
        sb.table("tasks").update({"status": "running"}).eq("id", task_id).execute()
        result = await orchestrate(prompt, workspace_id, task_id)
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
