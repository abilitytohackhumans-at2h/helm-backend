from config import settings
from supabase import create_client

sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

async def log_task(task_id: str, plan: dict, results: dict):
    """Guarda el resultado de una tarea en el historial."""
    total_tokens = sum(r.get("tokens_used", 0) for r in results.values())
    # Coste aproximado: $3/MTok input + $15/MTok output para Sonnet
    cost_usd = total_tokens * 0.003 / 1000

    sb.table("tasks").update({
        "result_json": {agent: r.get("output", "") for agent, r in results.items()},
        "tokens_used": total_tokens,
        "cost_usd": cost_usd,
    }).eq("id", task_id).execute()
