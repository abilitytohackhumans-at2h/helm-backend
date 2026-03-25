import json
import re
import anthropic
from datetime import datetime, timezone
from agents.dynamic_agent import DynamicAgent
from config import settings
from supabase import create_client

sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def get_orchestrator_prompt(available_agents: list[dict]) -> str:
    """Build orchestrator prompt dynamically based on workspace agents."""
    agent_list = ", ".join([f'"{a["slug"]}"' for a in available_agents])
    agent_descriptions = "\n".join([
        f'  - {a["slug"]}: {a.get("description") or a["name"]}'
        for a in available_agents
    ])

    return f"""Eres el orquestador de HELM, la oficina virtual con agentes IA.
Tu unico rol es clasificar y planificar. NUNCA ejecutas tareas.

Agentes disponibles en este workspace:
{agent_descriptions}

Devuelve SIEMPRE un JSON valido con esta estructura exacta:
{{
  "subtasks": [
    {{
      "agent": {agent_list},
      "task": "descripcion clara de la subtarea",
      "priority": 1,
      "depends_on": []
    }}
  ],
  "hitl_required": false,
  "hitl_reason": ""
}}

Reglas:
- SOLO usa agentes de la lista disponible. No inventes agentes.
- priority: numero entero, 1 = se ejecuta primero
- depends_on: lista de indices (0-based) de subtareas que deben completarse antes
- Si varias subtareas tienen la misma prioridad y no dependen entre si, se ejecutan en orden
- hitl_required debe ser true cuando la tarea implique: enviar emails,
  publicar en RRSS, modificar datos de clientes, o cualquier accion irreversible.
- Asigna subtareas solo a los agentes mas relevantes. No uses todos si no hace falta.
"""


def get_agent_map(workspace_id: str) -> dict[str, DynamicAgent]:
    """Load agents dynamically from DB for this workspace."""
    agents = sb.table("agents").select("*").eq(
        "workspace_id", workspace_id
    ).eq("is_active", True).execute().data

    agent_map = {}
    for a in agents:
        agent_map[a["slug"]] = DynamicAgent(
            slug=a["slug"],
            name=a["name"],
            system_prompt=a["system_prompt"],
            tools_enabled=a.get("tools_enabled") or [],
        )
    return agent_map


def extract_json(text: str) -> dict:
    """Extract JSON from text that may contain markdown code blocks."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"No valid JSON found in response: {text[:200]}")


async def create_hitl_request(task_id: str, plan: dict):
    sb.table("hitl_requests").insert({
        "task_id": task_id,
        "agent_slug": plan["subtasks"][0]["agent"] if plan["subtasks"] else "admin",
        "title": "Aprobacion requerida",
        "description": plan.get("hitl_reason", "Esta tarea requiere aprobacion antes de continuar."),
        "payload": plan,
    }).execute()


async def execute_subtasks(plan: dict, task_id: str, agent_map: dict[str, DynamicAgent]) -> dict:
    """Execute subtasks with individual tracking and context chaining."""
    results = {}
    context_chain = ""  # Accumulated context from previous agents

    # Get subtask DB rows to update them
    db_subtasks = sb.table("subtasks").select("*").eq("task_id", task_id).order("priority").execute().data

    # Build a map: agent_slug -> db subtask id
    subtask_id_map = {}
    for row in db_subtasks:
        subtask_id_map[row["agent_slug"]] = row["id"]

    sorted_subtasks = sorted(plan["subtasks"], key=lambda x: x.get("priority", 1))

    for subtask in sorted_subtasks:
        agent_slug = subtask["agent"]
        agent = agent_map.get(agent_slug)
        if not agent:
            continue

        db_id = subtask_id_map.get(agent_slug)

        # 1. Mark subtask as running
        if db_id:
            sb.table("subtasks").update({
                "status": "running",
            }).eq("id", db_id).execute()

        try:
            # 2. Execute agent with context from previous agents
            result = await agent.run(subtask["task"], context=context_chain)

            # 3. Mark subtask as completed with output
            if db_id:
                sb.table("subtasks").update({
                    "status": "completed",
                    "output": result.get("output", ""),
                    "tokens_used": result.get("tokens_used", 0),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", db_id).execute()

            results[agent_slug] = result

            # 4. Add output to context chain for next agent
            context_chain += f"\n\n--- Output del agente {agent_slug.upper()} ---\n{result.get('output', '')}\n"

        except Exception as e:
            # Mark subtask as failed
            if db_id:
                sb.table("subtasks").update({
                    "status": "failed",
                    "output": f"Error: {str(e)}",
                }).eq("id", db_id).execute()
            results[agent_slug] = {"output": f"Error: {str(e)}", "tokens_used": 0}

    return results


async def orchestrate(user_input: str, workspace_id: str, task_id: str) -> dict:
    """Full orchestration: plan → HITL gate → execute agents."""
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # 0. Load workspace agents dynamically
    agent_map = get_agent_map(workspace_id)
    available_agents = sb.table("agents").select("slug, name, description").eq(
        "workspace_id", workspace_id
    ).eq("is_active", True).execute().data

    orchestrator_prompt = get_orchestrator_prompt(available_agents)

    # 0b. Get workspace memory context
    try:
        from memory.state_manager import get_workspace_context
        memory_context = await get_workspace_context(workspace_id)
    except Exception:
        memory_context = ""

    enriched_input = user_input
    if memory_context:
        enriched_input = f"[Contexto del workspace]\n{memory_context}\n\n[Tarea del usuario]\n{user_input}"

    # 1. Plan
    plan_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=orchestrator_prompt,
        messages=[{"role": "user", "content": enriched_input}]
    )
    raw_text = plan_response.content[0].text
    plan = extract_json(raw_text)

    # Save plan to DB
    sb.table("tasks").update({"plan_json": plan}).eq("id", task_id).execute()

    # 2. HITL gate
    if plan.get("hitl_required"):
        await create_hitl_request(task_id, plan)
        return {"status": "hitl", "plan": plan}

    # 3. Create subtasks in DB
    for st in plan["subtasks"]:
        sb.table("subtasks").insert({
            "task_id": task_id,
            "agent_slug": st["agent"],
            "description": st["task"],
            "priority": st.get("priority", 1),
            "status": "pending",
        }).execute()

    # 4. Execute all subtasks with tracking
    results = await execute_subtasks(plan, task_id, agent_map)

    return {"status": "completed", "plan": plan, "results": results}


async def resume_after_hitl(task_id: str):
    """Resume orchestration after HITL approval."""
    task = sb.table("tasks").select("*").eq("id", task_id).single().execute().data

    if not task or not task.get("plan_json"):
        sb.table("tasks").update({
            "status": "failed",
            "result_json": {"error": "No plan found to resume"},
        }).eq("id", task_id).execute()
        return

    plan = task["plan_json"]

    # Update task status to running
    sb.table("tasks").update({"status": "running"}).eq("id", task_id).execute()

    # Create subtasks in DB (if not already created)
    existing = sb.table("subtasks").select("id").eq("task_id", task_id).execute().data
    if not existing:
        for st in plan["subtasks"]:
            sb.table("subtasks").insert({
                "task_id": task_id,
                "agent_slug": st["agent"],
                "description": st["task"],
                "priority": st.get("priority", 1),
                "status": "pending",
            }).execute()

    try:
        agent_map = get_agent_map(task["workspace_id"])
        results = await execute_subtasks(plan, task_id, agent_map)
        total_tokens = sum(r.get("tokens_used", 0) for r in results.values())

        sb.table("tasks").update({
            "status": "completed",
            "result_json": results,
            "assigned_agents": list(results.keys()),
            "tokens_used": total_tokens,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", task_id).execute()

    except Exception as e:
        sb.table("tasks").update({
            "status": "failed",
            "result_json": {"error": str(e)},
        }).eq("id", task_id).execute()


async def reject_after_hitl(task_id: str, note: str = ""):
    """Mark task as failed after HITL rejection."""
    sb.table("tasks").update({
        "status": "failed",
        "result_json": {"rejected": True, "note": note or "Tarea rechazada por el usuario"},
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", task_id).execute()
