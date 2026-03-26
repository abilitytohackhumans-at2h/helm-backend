"""
Admin router — Super Admin operations.
Manage workspaces, agent templates, and deploy custom agents per client.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import settings
from supabase import create_client

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


# ═══════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════

class WorkspaceCreate(BaseModel):
    name: str
    slug: str
    owner_id: str
    plan: str = "free"
    primary_color: str = "#7F77DD"
    max_agents: int = 10

class AgentCreate(BaseModel):
    name: str
    slug: str
    system_prompt: str
    tools_enabled: list[str] = []
    icon: str = "bot"
    color: str = "#7F77DD"
    description: str = ""

class AgentFromTemplate(BaseModel):
    template_id: str
    name_override: str | None = None
    prompt_additions: str | None = None

class TemplateCreate(BaseModel):
    name: str
    slug: str
    category: str = "custom"
    system_prompt: str
    tools_enabled: list[str] = []
    description: str = ""
    icon: str = "bot"
    color: str = "#7F77DD"
    is_public: bool = False


# ═══════════════════════════════════════════════════
# WORKSPACES
# ═══════════════════════════════════════════════════

class OnboardRequest(BaseModel):
    client_name: str
    client_email: str
    client_password: str
    workspace_name: str
    plan: str = "pro"
    agent_template_ids: list[str] = []
    custom_agents: list[AgentCreate] = []


@router.post("/onboard")
async def onboard_client(req: OnboardRequest):
    """Full onboarding: create user + workspace + agents in one go."""
    # 1. Create user in Supabase Auth
    try:
        user_response = sb.auth.admin.create_user({
            "email": req.client_email,
            "password": req.client_password,
            "email_confirm": True,
        })
        user_id = user_response.user.id
    except Exception as e:
        raise HTTPException(400, f"Error creating user: {str(e)}")

    # 2. Create profile
    sb.table("profiles").insert({
        "id": user_id,
        "email": req.client_email,
        "full_name": req.client_name,
        "is_super_admin": False,
    }).execute()

    # 3. Create workspace
    slug = req.workspace_name.lower().replace(" ", "-").replace(".", "")
    ws_row = sb.table("workspaces").insert({
        "name": req.workspace_name,
        "slug": slug,
        "owner_id": user_id,
        "plan": req.plan,
    }).execute()
    ws = ws_row.data[0]

    # 4. Add user as workspace owner
    sb.table("workspace_members").insert({
        "workspace_id": ws["id"],
        "user_id": user_id,
        "role": "owner",
    }).execute()

    # 5. Add super admin to workspace (the one making the request)
    # Find super admins and add them
    super_admins = sb.table("profiles").select("id").eq("is_super_admin", True).execute().data
    for sa in super_admins:
        try:
            sb.table("workspace_members").insert({
                "workspace_id": ws["id"],
                "user_id": sa["id"],
                "role": "super_admin",
            }).execute()
        except Exception:
            pass  # May already exist

    # 6. Deploy agents from templates
    agents_created = []
    for tpl_id in req.agent_template_ids:
        try:
            template = sb.table("agent_templates").select("*").eq("id", tpl_id).single().execute().data
            if template:
                agent = sb.table("agents").insert({
                    "workspace_id": ws["id"],
                    "name": template["name"],
                    "slug": template["slug"],
                    "system_prompt": template["system_prompt"],
                    "tools_enabled": template.get("tools_enabled", []),
                    "is_active": True,
                }).execute()
                agents_created.append(agent.data[0])
        except Exception:
            pass

    # 7. Create custom agents
    for ca in req.custom_agents:
        try:
            agent = sb.table("agents").insert({
                "workspace_id": ws["id"],
                "name": ca.name,
                "slug": ca.slug,
                "system_prompt": ca.system_prompt,
                "tools_enabled": ca.tools_enabled,
                "is_active": True,
            }).execute()
            agents_created.append(agent.data[0])
        except Exception:
            pass

    return {
        "user_id": user_id,
        "workspace": ws,
        "agents_created": len(agents_created),
        "login_url": f"/login",
    }


@router.get("/overview")
async def global_overview():
    """Global metrics across all workspaces for super admin dashboard."""
    workspaces = sb.table("workspaces").select("*").execute().data
    all_tasks = sb.table("tasks").select("id, workspace_id, status, tokens_used, cost_usd, created_at").execute().data
    all_agents = sb.table("agents").select("id, workspace_id, is_active").execute().data

    # Global KPIs
    total_tokens = sum(t.get("tokens_used", 0) or 0 for t in all_tasks)
    total_cost = sum(t.get("cost_usd", 0) or 0 for t in all_tasks)
    total_completed = len([t for t in all_tasks if t["status"] == "completed"])
    total_failed = len([t for t in all_tasks if t["status"] == "failed"])

    # Per-workspace breakdown
    ws_stats = []
    for ws in workspaces:
        ws_tasks = [t for t in all_tasks if t["workspace_id"] == ws["id"]]
        ws_agents = [a for a in all_agents if a["workspace_id"] == ws["id"]]
        ws_tokens = sum(t.get("tokens_used", 0) or 0 for t in ws_tasks)
        ws_cost = sum(t.get("cost_usd", 0) or 0 for t in ws_tasks)
        ws_completed = len([t for t in ws_tasks if t["status"] == "completed"])
        ws_failed = len([t for t in ws_tasks if t["status"] == "failed"])
        ws_running = len([t for t in ws_tasks if t["status"] == "running"])

        # Health: green if active recently, amber if some activity, red if none
        recent_tasks = [t for t in ws_tasks if t.get("created_at", "") > (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            - __import__("datetime").timedelta(days=7)
        ).isoformat()]
        health = "green" if len(recent_tasks) > 2 else "amber" if len(recent_tasks) > 0 else "red"

        ws_stats.append({
            "id": ws["id"],
            "name": ws["name"],
            "slug": ws["slug"],
            "plan": ws.get("plan", "free"),
            "agents_total": len(ws_agents),
            "agents_active": len([a for a in ws_agents if a["is_active"]]),
            "tasks_total": len(ws_tasks),
            "tasks_completed": ws_completed,
            "tasks_failed": ws_failed,
            "tasks_running": ws_running,
            "tokens_used": ws_tokens,
            "cost_usd": round(ws_cost, 4),
            "health": health,
            "created_at": ws.get("created_at", ""),
        })

    return {
        "global": {
            "total_workspaces": len(workspaces),
            "total_agents": len(all_agents),
            "total_tasks": len(all_tasks),
            "total_completed": total_completed,
            "total_failed": total_failed,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
        },
        "workspaces": ws_stats,
    }


@router.get("/workspaces")
async def list_workspaces(owner_id: str | None = None):
    """List all workspaces (optionally filtered by owner)."""
    query = sb.table("workspaces").select("*, workspace_members(role, user_id)")
    if owner_id:
        query = query.eq("owner_id", owner_id)
    data = query.order("created_at", desc=True).execute().data

    # Enrich with agent count and task stats
    for ws in data:
        agents = sb.table("agents").select("id", count="exact").eq("workspace_id", ws["id"]).execute()
        ws["agent_count"] = agents.count or 0
        tasks = sb.table("tasks").select("id", count="exact").eq("workspace_id", ws["id"]).execute()
        ws["task_count"] = tasks.count or 0

    return data


@router.post("/workspaces")
async def create_workspace(req: WorkspaceCreate):
    """Create a new client workspace."""
    row = sb.table("workspaces").insert({
        "name": req.name,
        "slug": req.slug,
        "owner_id": req.owner_id,
        "plan": req.plan,
        "primary_color": req.primary_color,
        "max_agents": req.max_agents,
    }).execute()

    ws = row.data[0]

    # Auto-add owner as member
    sb.table("workspace_members").insert({
        "workspace_id": ws["id"],
        "user_id": req.owner_id,
        "role": "owner",
    }).execute()

    return ws


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, delete_user: bool = False):
    """Delete a workspace and all its data. Optionally delete the owner user too."""
    # Get workspace info first
    ws = sb.table("workspaces").select("owner_id").eq("id", workspace_id).single().execute().data
    if not ws:
        raise HTTPException(404, "Workspace not found")

    # Cascade delete (order matters due to foreign keys)
    # 1. Delete subtasks (via tasks)
    tasks = sb.table("tasks").select("id").eq("workspace_id", workspace_id).execute().data
    for t in tasks:
        sb.table("subtasks").delete().eq("task_id", t["id"]).execute()

    # 2. Delete HITL requests
    for t in tasks:
        sb.table("hitl_requests").delete().eq("task_id", t["id"]).execute()

    # 3. Delete tasks
    sb.table("tasks").delete().eq("workspace_id", workspace_id).execute()

    # 4. Delete agents
    sb.table("agents").delete().eq("workspace_id", workspace_id).execute()

    # 5. Delete workspace members
    sb.table("workspace_members").delete().eq("workspace_id", workspace_id).execute()

    # 6. Delete memory (projects, clients)
    try:
        sb.table("memory_projects").delete().eq("workspace_id", workspace_id).execute()
        sb.table("memory_clients").delete().eq("workspace_id", workspace_id).execute()
    except Exception:
        pass  # Tables may not exist

    # 7. Delete workspace
    sb.table("workspaces").delete().eq("id", workspace_id).execute()

    # 8. Optionally delete the owner user
    if delete_user and ws.get("owner_id"):
        try:
            sb.table("profiles").delete().eq("id", ws["owner_id"]).execute()
            sb.auth.admin.delete_user(ws["owner_id"])
        except Exception:
            pass  # User may have other workspaces

    return {"ok": True, "deleted_tasks": len(tasks)}


@router.patch("/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, updates: dict):
    """Update workspace settings."""
    allowed = {"name", "primary_color", "max_agents", "max_tasks_month", "logo_url", "plan"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        raise HTTPException(400, "No valid fields to update")
    return sb.table("workspaces").update(filtered).eq("id", workspace_id).execute().data


# ═══════════════════════════════════════════════════
# AGENTS PER WORKSPACE
# ═══════════════════════════════════════════════════

@router.get("/workspaces/{workspace_id}/agents")
async def list_workspace_agents(workspace_id: str):
    """List all agents in a workspace."""
    return sb.table("agents").select("*").eq("workspace_id", workspace_id).order("created_at").execute().data


@router.post("/workspaces/{workspace_id}/agents")
async def create_agent(workspace_id: str, req: AgentCreate):
    """Create a custom agent for this workspace."""
    # Check workspace limits
    ws = sb.table("workspaces").select("max_agents").eq("id", workspace_id).single().execute().data
    current = sb.table("agents").select("id", count="exact").eq("workspace_id", workspace_id).execute()
    if current.count >= (ws.get("max_agents") or 10):
        raise HTTPException(400, f"Workspace limit reached ({ws['max_agents']} agents)")

    row = sb.table("agents").insert({
        "workspace_id": workspace_id,
        "name": req.name,
        "slug": req.slug,
        "system_prompt": req.system_prompt,
        "tools_enabled": req.tools_enabled,
        "icon": req.icon,
        "color": req.color,
        "description": req.description,
        "is_active": True,
    }).execute()

    return row.data[0]


@router.post("/workspaces/{workspace_id}/agents/from-template")
async def create_agent_from_template(workspace_id: str, req: AgentFromTemplate):
    """Clone an agent from a template into this workspace."""
    template = sb.table("agent_templates").select("*").eq("id", req.template_id).single().execute().data
    if not template:
        raise HTTPException(404, "Template not found")

    prompt = template["system_prompt"]
    if req.prompt_additions:
        prompt += f"\n\n--- Instrucciones adicionales del cliente ---\n{req.prompt_additions}"

    row = sb.table("agents").insert({
        "workspace_id": workspace_id,
        "name": req.name_override or template["name"],
        "slug": template["slug"],
        "system_prompt": prompt,
        "tools_enabled": template["tools_enabled"],
        "icon": template.get("icon", "bot"),
        "color": template.get("color", "#7F77DD"),
        "description": template.get("description", ""),
        "template_id": template["id"],
        "is_active": True,
    }).execute()

    return row.data[0]


@router.delete("/workspaces/{workspace_id}/agents/{agent_id}")
async def delete_agent(workspace_id: str, agent_id: str):
    """Remove an agent from a workspace."""
    sb.table("agents").delete().eq("id", agent_id).eq("workspace_id", workspace_id).execute()
    return {"ok": True}


# ═══════════════════════════════════════════════════
# TEMPLATES
# ═══════════════════════════════════════════════════

@router.get("/templates")
async def list_templates(owner_id: str | None = None):
    """List available agent templates."""
    query = sb.table("agent_templates").select("*")
    if owner_id:
        # Show user's own + public templates
        query = query.or_(f"owner_id.eq.{owner_id},is_public.eq.true")
    return query.order("category").order("name").execute().data


@router.post("/templates")
async def create_template(req: TemplateCreate):
    """Create a new agent template."""
    row = sb.table("agent_templates").insert({
        "name": req.name,
        "slug": req.slug,
        "category": req.category,
        "system_prompt": req.system_prompt,
        "tools_enabled": req.tools_enabled,
        "description": req.description,
        "icon": req.icon,
        "color": req.color,
        "is_public": req.is_public,
    }).execute()
    return row.data[0]


@router.patch("/templates/{template_id}")
async def update_template(template_id: str, updates: dict):
    """Update an agent template."""
    allowed = {"name", "system_prompt", "tools_enabled", "description", "icon", "color", "is_public", "category"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    return sb.table("agent_templates").update(filtered).eq("id", template_id).execute().data


# ═══════════════════════════════════════════════════
# WORKSPACE MEMBERS
# ═══════════════════════════════════════════════════

class MemberInvite(BaseModel):
    email: str
    role: str = "editor"
    password: str | None = None

class MemberRoleUpdate(BaseModel):
    role: str


@router.get("/workspaces/{workspace_id}/members")
async def list_workspace_members(workspace_id: str):
    """List all members of a workspace with profile info."""
    members = sb.table("workspace_members").select(
        "user_id, role, created_at"
    ).eq("workspace_id", workspace_id).execute().data

    # Enrich with profile info (fallback to auth if profile missing)
    result = []
    for m in members:
        email = ""
        full_name = ""
        avatar_url = None
        try:
            profile = sb.table("profiles").select(
                "email, full_name, avatar_url"
            ).eq("id", m["user_id"]).single().execute().data
            email = profile.get("email", "")
            full_name = profile.get("full_name", "")
            avatar_url = profile.get("avatar_url")
        except Exception:
            # Fallback: get email from Supabase Auth
            try:
                auth_user = sb.auth.admin.get_user_by_id(m["user_id"])
                email = auth_user.user.email or ""
                full_name = email.split("@")[0]
                # Auto-create missing profile
                sb.table("profiles").upsert({
                    "id": m["user_id"],
                    "email": email,
                    "full_name": full_name,
                    "is_super_admin": False,
                }).execute()
            except Exception:
                email = "unknown"

        result.append({
            "user_id": m["user_id"],
            "email": email,
            "full_name": full_name,
            "avatar_url": avatar_url,
            "role": m["role"],
            "created_at": m["created_at"],
        })

    return result


@router.post("/workspaces/{workspace_id}/members")
async def invite_member(workspace_id: str, req: MemberInvite):
    """Invite a member to a workspace. Creates user if email doesn't exist."""
    valid_roles = {"owner", "admin", "editor", "viewer"}
    if req.role not in valid_roles:
        raise HTTPException(400, f"Invalid role. Must be one of: {valid_roles}")

    # Check if user already exists in Supabase Auth
    user_id = None
    try:
        users = sb.auth.admin.list_users()
        for u in users:
            if u.email == req.email:
                user_id = u.id
                break
    except Exception:
        pass

    if not user_id:
        # Create new user
        password = req.password or req.email.split("@")[0] + "2026!"
        try:
            user_response = sb.auth.admin.create_user({
                "email": req.email,
                "password": password,
                "email_confirm": True,
            })
            user_id = user_response.user.id
        except Exception as e:
            raise HTTPException(400, f"Error creating user: {str(e)}")

        # Create profile
        sb.table("profiles").upsert({
            "id": user_id,
            "email": req.email,
            "full_name": req.email.split("@")[0],
            "is_super_admin": False,
        }).execute()

    # Check not already a member
    existing = sb.table("workspace_members").select("id").eq(
        "workspace_id", workspace_id
    ).eq("user_id", user_id).execute().data
    if existing:
        raise HTTPException(409, "User is already a member of this workspace")

    # Add as member
    sb.table("workspace_members").insert({
        "workspace_id": workspace_id,
        "user_id": user_id,
        "role": req.role,
    }).execute()

    return {"user_id": user_id, "email": req.email, "role": req.role, "created": not bool(user_id)}


@router.patch("/workspaces/{workspace_id}/members/{user_id}")
async def update_member_role(workspace_id: str, user_id: str, req: MemberRoleUpdate):
    """Change a member's role. Cannot change the workspace owner."""
    valid_roles = {"owner", "admin", "editor", "viewer"}
    if req.role not in valid_roles:
        raise HTTPException(400, f"Invalid role. Must be one of: {valid_roles}")

    # Check if user is owner — protect owner role
    ws = sb.table("workspaces").select("owner_id").eq("id", workspace_id).single().execute().data
    if ws and ws["owner_id"] == user_id:
        raise HTTPException(403, "Cannot change the workspace owner's role")

    sb.table("workspace_members").update(
        {"role": req.role}
    ).eq("workspace_id", workspace_id).eq("user_id", user_id).execute()

    return {"ok": True, "role": req.role}


@router.delete("/workspaces/{workspace_id}/members/{user_id}")
async def remove_member(workspace_id: str, user_id: str):
    """Remove a member from a workspace. Cannot remove the owner."""
    # Protect owner
    ws = sb.table("workspaces").select("owner_id").eq("id", workspace_id).single().execute().data
    if ws and ws["owner_id"] == user_id:
        raise HTTPException(403, "Cannot remove the workspace owner")

    sb.table("workspace_members").delete().eq(
        "workspace_id", workspace_id
    ).eq("user_id", user_id).execute()

    return {"ok": True}
