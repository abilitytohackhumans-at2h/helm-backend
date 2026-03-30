"""Agent 6: Follow-up - Genera y envia mensajes de seguimiento."""
import json
import anthropic
from datetime import datetime, timezone, timedelta
from config import settings

FOLLOWUP_SYSTEM = """Eres el agente de follow-up de WeNeedToEat.

El restaurante ya recibio un primer mensaje hace varios dias y no respondio.
Tu mision: escribir un mensaje de seguimiento que NO repita el primero.

REGLAS:
- Reconoce implicitamente que ya escribiste (sin ser pesado).
- Aporta algo nuevo: un dato, una pregunta diferente, un caso de uso.
- Si es el follow-up numero 3, hazlo de despedida: "Si no es el momento,
  sin problema. Aqui estaremos."
- Mismos limites de longitud que el mensaje original segun canal.
- Email: max 100 palabras. WhatsApp: max 3 frases. Instagram: max 2 frases.

OUTPUT: JSON con los campos apropiados segun canal. Solo JSON, sin markdown."""

# Default intervals
FOLLOWUP_INTERVALS = [3, 5, 7]  # days between follow-ups
MAX_FOLLOWUPS = 3


async def generate_followup(lead: dict, restaurant: dict, last_message: dict, follow_up_number: int) -> dict:
    """Genera mensaje de follow-up."""
    channel = last_message.get("channel", lead.get("preferred_channel", "email"))

    profile = {
        "name": restaurant.get("name"),
        "zone": restaurant.get("zone"),
        "segment": lead.get("segment"),
        "channel": channel,
        "original_message": last_message.get("message_body", ""),
        "follow_up_number": follow_up_number,
    }

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=settings.MODEL_NAME,
        max_tokens=300,
        system=FOLLOWUP_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(profile, ensure_ascii=False)}],
    )

    text = response.content[0].text
    tokens = response.usage.input_tokens + response.usage.output_tokens

    try:
        message_data = json.loads(text)
    except json.JSONDecodeError:
        import re
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            message_data = json.loads(json_match.group())
        else:
            message_data = {"body": text} if channel == "email" else {"message": text}

    return {
        "channel": channel,
        "message": message_data,
        "tokens_used": tokens,
        "follow_up_number": follow_up_number,
    }


async def run_followups(workspace_id: str = None) -> dict:
    """Ejecuta follow-ups para todos los leads pendientes."""
    from supabase import create_client
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    from agents.outreach.sender_agent import send_message

    now = datetime.now(timezone.utc)
    sent = 0
    errors = 0

    # Get all contacted leads that haven't replied
    query = sb.table("leads").select("*, restaurants(*)").eq("status", "contacted")
    if workspace_id:
        query = query.eq("workspace_id", workspace_id)
    result = query.execute()

    for lead in (result.data or []):
        restaurant = lead.get("restaurants", {})
        if not restaurant:
            continue

        # Get last outreach log for this lead
        logs = sb.table("outreach_log").select("*").eq("lead_id", lead["id"]).order("created_at", desc=True).limit(1).execute()
        if not logs.data:
            continue

        last_log = logs.data[0]
        last_contact = datetime.fromisoformat(last_log["sent_at"].replace("Z", "+00:00")) if last_log.get("sent_at") else None
        if not last_contact:
            continue

        follow_up_num = last_log.get("follow_up_number", 1) + 1
        if follow_up_num > MAX_FOLLOWUPS:
            # Max follow-ups reached - mark as closed_lost
            sb.table("leads").update({"status": "closed_lost", "disqualify_reason": "Sin respuesta tras 3 follow-ups"}).eq("id", lead["id"]).execute()
            continue

        # Check interval
        interval_days = FOLLOWUP_INTERVALS[min(follow_up_num - 2, len(FOLLOWUP_INTERVALS) - 1)]
        if now - last_contact < timedelta(days=interval_days):
            continue

        # Generate and send follow-up
        try:
            fu_result = await generate_followup(lead, restaurant, last_log, follow_up_num)
            send_result = await send_message(lead, restaurant, fu_result["message"], fu_result["channel"])

            # Log the outreach
            log_entry = {
                "workspace_id": lead["workspace_id"],
                "lead_id": lead["id"],
                "channel": fu_result["channel"],
                "message_body": json.dumps(fu_result["message"], ensure_ascii=False),
                "follow_up_number": follow_up_num,
                "status": send_result.get("status", "failed"),
                "sent_at": send_result.get("sent_at"),
                "error_message": send_result.get("error"),
                "tokens_used": fu_result.get("tokens_used", 0),
            }
            if fu_result["channel"] == "email":
                log_entry["message_subject"] = fu_result["message"].get("subject", "Follow-up")

            sb.table("outreach_log").insert(log_entry).execute()

            # Update lead
            sb.table("leads").update({
                "last_contact_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }).eq("id", lead["id"]).execute()

            if send_result.get("status") == "sent":
                sent += 1
            else:
                errors += 1
        except Exception:
            errors += 1

    return {"follow_ups_sent": sent, "errors": errors}
