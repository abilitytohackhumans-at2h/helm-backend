from config import settings
from supabase import create_client

sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

async def get_workspace_context(workspace_id: str) -> str:
    """Obtiene contexto del workspace para enriquecer prompts de agentes."""
    projects = sb.table("memory_projects").select("name, type, status").eq(
        "workspace_id", workspace_id
    ).eq("status", "active").execute().data

    clients = sb.table("memory_clients").select("name, tier, notes").eq(
        "workspace_id", workspace_id
    ).execute().data

    context_parts = []
    if projects:
        context_parts.append("Proyectos activos: " + ", ".join(p["name"] for p in projects))
    if clients:
        context_parts.append("Clientes: " + ", ".join(c["name"] for c in clients))

    return "\n".join(context_parts)
