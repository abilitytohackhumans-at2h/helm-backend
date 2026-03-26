"""
Self-service onboarding router.
Allows new users (already signed up via Supabase Auth) to create their
workspace, profile, and initial agents without admin intervention.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from config import settings
from supabase import create_client
from auth import AuthUser, get_current_user
from routers.notifications import notify_super_admins

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


# ═══════════════════════════════════════════════════
# PRESET AGENTS (mirrors frontend Onboarding.tsx)
# ═══════════════════════════════════════════════════

PRESET_AGENTS = {
    "research": {
        "name": "Research",
        "slug": "research",
        "system_prompt": "Eres el agente de Research. Investiga temas a fondo con minimo 5 fuentes. Distingue dato verificado de estimacion. Incluye limitaciones del analisis.",
        "tools_enabled": ["web_search"],
        "icon": "🔍",
        "color": "#3B82F6",
        "description": "Investigación y análisis de mercado",
    },
    "content": {
        "name": "Content",
        "slug": "content",
        "system_prompt": "Eres el agente de Contenido. Especialidades: articulos, guiones, newsletters, posts. Estructura: gancho potente, desarrollo, call to action. SEO natural.",
        "tools_enabled": ["web_search", "file_create"],
        "icon": "✍️",
        "color": "#F59E0B",
        "description": "Creación de contenido y copywriting",
    },
    "social": {
        "name": "Social Media",
        "slug": "social",
        "system_prompt": "Eres el agente de Social Media. Plataformas: Instagram, LinkedIn, TikTok, X/Twitter. Copy principal + variante corta + hashtags (max 5) + horario optimo.",
        "tools_enabled": ["web_search", "file_create"],
        "icon": "📱",
        "color": "#EC4899",
        "description": "Gestión de redes sociales",
    },
    "marketing": {
        "name": "Marketing",
        "slug": "marketing",
        "system_prompt": "Eres el agente de Marketing. Especialidades: copies publicitarios, naming, taglines, briefings creativos, estrategia de campana. Entrega siempre 3 variantes.",
        "tools_enabled": ["web_search", "file_create"],
        "icon": "📣",
        "color": "#EF4444",
        "description": "Estrategia y campañas de marketing",
    },
    "crm": {
        "name": "CRM",
        "slug": "crm",
        "system_prompt": "Eres el agente de CRM. Gestion de leads, pipeline, seguimiento de clientes. Pipeline: prospecto / contactado / propuesta / negociacion / cerrado.",
        "tools_enabled": ["file_create"],
        "icon": "🤝",
        "color": "#10B981",
        "description": "Gestión de relaciones con clientes",
    },
    "admin": {
        "name": "Admin",
        "slug": "admin",
        "system_prompt": "Eres el agente de Administracion. Especialidades: emails, agenda, gestion documental. Toda accion irreversible es HITL obligatorio.",
        "tools_enabled": ["file_create"],
        "icon": "⚙️",
        "color": "#8B5CF6",
        "description": "Administración y gestión documental",
    },
}


# ═══════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════

class SelfOnboardRequest(BaseModel):
    company_name: str
    industry: str = ""
    team_size: str = ""
    logo_url: str | None = None
    plan: str = "free"
    selected_agent_slugs: list[str] = ["research", "content", "social"]


# ═══════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════

@router.post("/self-service")
async def self_service_onboard(req: SelfOnboardRequest, user: AuthUser = Depends(get_current_user)):
    """
    Self-service onboarding for new users.
    The user already exists in Supabase Auth (signed up via frontend).
    This creates: profile + workspace + workspace_member + agents.
    """
    user_id = user.user_id

    # 1. Check user doesn't already have a workspace
    existing = sb.table("workspaces").select("id").eq("owner_id", user_id).execute().data
    if existing:
        raise HTTPException(409, "User already has a workspace")

    # 2. Get user email from Supabase Auth
    try:
        auth_user = sb.auth.admin.get_user_by_id(user_id)
        user_email = auth_user.user.email
    except Exception as e:
        raise HTTPException(400, f"Could not find user: {str(e)}")

    # 3. Create profile (upsert to handle race conditions)
    try:
        sb.table("profiles").upsert({
            "id": user_id,
            "email": user_email,
            "full_name": req.company_name,
            "is_super_admin": False,
            "avatar_url": req.logo_url,
        }).execute()
    except Exception as e:
        raise HTTPException(500, f"Error creating profile: {str(e)}")

    # 4. Create workspace
    slug = req.company_name.lower().replace(" ", "-").replace(".", "").replace(",", "")
    try:
        ws_row = sb.table("workspaces").insert({
            "name": req.company_name,
            "slug": slug,
            "owner_id": user_id,
            "plan": req.plan,
        }).execute()
        ws = ws_row.data[0]
    except Exception as e:
        raise HTTPException(500, f"Error creating workspace: {str(e)}")

    # 5. Add user as workspace owner
    sb.table("workspace_members").insert({
        "workspace_id": ws["id"],
        "user_id": user_id,
        "role": "owner",
    }).execute()

    # 6. Add super admins to workspace
    super_admins = sb.table("profiles").select("id").eq("is_super_admin", True).execute().data
    for sa in super_admins:
        try:
            sb.table("workspace_members").insert({
                "workspace_id": ws["id"],
                "user_id": sa["id"],
                "role": "super_admin",
            }).execute()
        except Exception:
            pass

    # 7. Deploy selected preset agents
    agents_created = []
    for slug_key in req.selected_agent_slugs:
        preset = PRESET_AGENTS.get(slug_key)
        if not preset:
            continue
        try:
            agent = sb.table("agents").insert({
                "workspace_id": ws["id"],
                "name": preset["name"],
                "slug": preset["slug"],
                "system_prompt": preset["system_prompt"],
                "tools_enabled": preset["tools_enabled"],
                "icon": preset["icon"],
                "color": preset["color"],
                "description": preset["description"],
                "is_active": True,
            }).execute()
            agents_created.append(agent.data[0])
        except Exception:
            pass

    # 8. Store extra metadata in workspace (industry, team_size)
    try:
        sb.table("workspaces").update({
            "logo_url": req.logo_url,
        }).eq("id", ws["id"]).execute()
    except Exception:
        pass

    # 9. Notify super admins about new registration
    notify_super_admins(
        title="🆕 Nuevo cliente registrado",
        message=f"{req.company_name} se ha registrado con plan {req.plan} y {len(agents_created)} agentes.",
        type="success",
        link="/admin",
    )

    return {
        "workspace": ws,
        "agents_created": len(agents_created),
        "profile_created": True,
    }
