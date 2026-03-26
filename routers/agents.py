from fastapi import APIRouter, HTTPException, Depends
from models.agent import AgentUpdate, AgentCreate
from config import settings
from supabase import create_client
from auth import AuthUser, get_current_user

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@router.get("")
async def list_agents(workspace_id: str, user: AuthUser = Depends(get_current_user)):
    from auth import require_workspace_access
    await require_workspace_access(workspace_id, user)

    agents = sb.table("agents").select("*").eq("workspace_id", workspace_id).execute().data
    for agent in agents:
        today_tasks = sb.table("subtasks").select("id", count="exact").eq(
            "agent_slug", agent["slug"]
        ).execute()
        agent["tasks_today"] = today_tasks.count or 0
        agent["tokens_used"] = 0
        agent["status"] = "active" if agent["is_active"] else "idle"
    return agents


@router.post("")
async def create_agent(agent: AgentCreate, user: AuthUser = Depends(get_current_user)):
    from auth import require_workspace_access
    await require_workspace_access(agent.workspace_id, user)

    existing = sb.table("agents").select("id").eq(
        "workspace_id", agent.workspace_id
    ).eq("slug", agent.slug).execute().data
    if existing:
        raise HTTPException(status_code=409, detail=f"Agent slug '{agent.slug}' already exists")

    row = sb.table("agents").insert({
        "workspace_id": agent.workspace_id,
        "name": agent.name,
        "slug": agent.slug,
        "system_prompt": agent.system_prompt,
        "tools_enabled": agent.tools_enabled,
        "is_active": True,
    }).execute()
    return row.data[0]


@router.patch("/{slug}")
async def update_agent(slug: str, update: AgentUpdate, user: AuthUser = Depends(get_current_user), workspace_id: str = ""):
    data = {}
    if update.name is not None: data["name"] = update.name
    if update.system_prompt is not None: data["system_prompt"] = update.system_prompt
    if update.is_active is not None: data["is_active"] = update.is_active
    if update.tools_enabled is not None: data["tools_enabled"] = update.tools_enabled

    if data:
        query = sb.table("agents").update(data).eq("slug", slug)
        if workspace_id:
            from auth import require_workspace_access
            await require_workspace_access(workspace_id, user)
            query = query.eq("workspace_id", workspace_id)
        query.execute()
    return {"ok": True}


@router.delete("/{slug}")
async def delete_agent(slug: str, workspace_id: str, user: AuthUser = Depends(get_current_user)):
    from auth import require_workspace_access
    await require_workspace_access(workspace_id, user)

    sb.table("agents").delete().eq("slug", slug).eq("workspace_id", workspace_id).execute()
    return {"ok": True}
