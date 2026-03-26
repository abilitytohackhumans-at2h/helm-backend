from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from config import settings
from supabase import create_client
from auth import AuthUser, get_current_user, require_workspace_access

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


# --- Models ---

class ProjectCreate(BaseModel):
    workspace_id: str
    name: str
    type: str = "campaign"
    status: str = "active"
    summary: str = ""

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None

class ClientCreate(BaseModel):
    workspace_id: str
    name: str
    tier: str = "standard"
    notes: str = ""

class ClientUpdate(BaseModel):
    name: Optional[str] = None
    tier: Optional[str] = None
    notes: Optional[str] = None


# --- Projects ---

@router.get("/projects")
async def list_projects(workspace_id: str, user: AuthUser = Depends(get_current_user)):
    await require_workspace_access(workspace_id, user)
    return sb.table("memory_projects").select("*").eq(
        "workspace_id", workspace_id
    ).order("created_at", desc=True).execute().data


@router.post("/projects")
async def create_project(body: ProjectCreate, user: AuthUser = Depends(get_current_user)):
    await require_workspace_access(body.workspace_id, user)
    row = sb.table("memory_projects").insert({
        "workspace_id": body.workspace_id,
        "name": body.name,
        "type": body.type,
        "status": body.status,
        "summary": body.summary,
    }).execute()
    return row.data[0] if row.data else {"ok": True}


@router.put("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate, user: AuthUser = Depends(get_current_user)):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if data:
        sb.table("memory_projects").update(data).eq("id", project_id).execute()
    return {"ok": True}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: AuthUser = Depends(get_current_user)):
    sb.table("memory_projects").delete().eq("id", project_id).execute()
    return {"ok": True}


# --- Clients ---

@router.get("/clients")
async def list_clients(workspace_id: str, user: AuthUser = Depends(get_current_user)):
    await require_workspace_access(workspace_id, user)
    return sb.table("memory_clients").select("*").eq(
        "workspace_id", workspace_id
    ).order("created_at", desc=True).execute().data


@router.post("/clients")
async def create_client_entry(body: ClientCreate, user: AuthUser = Depends(get_current_user)):
    await require_workspace_access(body.workspace_id, user)
    row = sb.table("memory_clients").insert({
        "workspace_id": body.workspace_id,
        "name": body.name,
        "tier": body.tier,
        "notes": body.notes,
    }).execute()
    return row.data[0] if row.data else {"ok": True}


@router.put("/clients/{client_id}")
async def update_client_entry(client_id: str, body: ClientUpdate, user: AuthUser = Depends(get_current_user)):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if data:
        sb.table("memory_clients").update(data).eq("id", client_id).execute()
    return {"ok": True}


@router.delete("/clients/{client_id}")
async def delete_client_entry(client_id: str, user: AuthUser = Depends(get_current_user)):
    sb.table("memory_clients").delete().eq("id", client_id).execute()
    return {"ok": True}
