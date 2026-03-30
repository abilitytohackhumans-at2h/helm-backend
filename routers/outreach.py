"""WeNeedToEat Outreach Pipeline - FastAPI Router."""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from routers.tasks import get_current_user
from config import settings

router = APIRouter(prefix="/outreach", tags=["outreach"])


# --- Request models ---

class ScrapeRequest(BaseModel):
    zone: str
    category: str = "restaurantes"
    limit: int = 20

class GenerateRequest(BaseModel):
    channel: Optional[str] = None

class RunPipelineRequest(BaseModel):
    zone: str
    category: str = "restaurantes"
    limit: int = 20
    min_score: int = 3


# --- Health ---

@router.get("/health")
async def health():
    return {"status": "ok", "pipeline": "weneedtoeat"}


# --- Scrape ---

@router.post("/scrape")
async def scrape(req: ScrapeRequest, user=Depends(get_current_user)):
    from agents.outreach.scraper_agent import scrape_zone
    result = await scrape_zone(user["workspace_id"], req.zone, req.category, req.limit)
    return result


# --- Enrich ---

@router.post("/enrich")
async def enrich_all(user=Depends(get_current_user)):
    from agents.outreach.enricher_agent import enrich_all_pending
    result = await enrich_all_pending(user["workspace_id"])
    return result

@router.post("/enrich/{restaurant_id}")
async def enrich_one(restaurant_id: str, user=Depends(get_current_user)):
    from supabase import create_client
    from agents.outreach.enricher_agent import enrich_restaurant
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

    r = sb.table("restaurants").select("*").eq("id", restaurant_id).eq("workspace_id", user["workspace_id"]).single().execute()
    if not r.data:
        raise HTTPException(404, "Restaurante no encontrado")

    updates = await enrich_restaurant(r.data)
    if updates:
        updates["enriched_at"] = datetime.now(timezone.utc).isoformat()
        sb.table("restaurants").update(updates).eq("id", restaurant_id).execute()

    return {"restaurant_id": restaurant_id, "updates": updates}


# --- Score ---

@router.post("/score")
async def score(user=Depends(get_current_user)):
    from agents.outreach.scorer_agent import score_all_pending
    result = await score_all_pending(user["workspace_id"])
    return result


# --- Generate message (HITL) ---

@router.post("/generate/{lead_id}")
async def generate(lead_id: str, req: GenerateRequest = None, user=Depends(get_current_user)):
    from supabase import create_client
    from agents.outreach.copywriter_agent import generate_message
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

    lead = sb.table("leads").select("*").eq("id", lead_id).eq("workspace_id", user["workspace_id"]).single().execute()
    if not lead.data:
        raise HTTPException(404, "Lead no encontrado")

    restaurant = sb.table("restaurants").select("*").eq("id", lead.data["restaurant_id"]).single().execute()
    if not restaurant.data:
        raise HTTPException(404, "Restaurante no encontrado")

    channel = (req.channel if req else None) or lead.data.get("preferred_channel", "email")
    result = await generate_message(lead.data, restaurant.data, channel)

    # Store generated message in outreach_log as pending (HITL)
    log_entry = {
        "workspace_id": user["workspace_id"],
        "lead_id": lead_id,
        "channel": result["channel"],
        "message_body": json.dumps(result["message"], ensure_ascii=False),
        "status": "pending",
        "tokens_used": result.get("tokens_used", 0),
    }
    if result["channel"] == "email":
        log_entry["message_subject"] = result["message"].get("subject", "")

    sb.table("outreach_log").insert(log_entry).execute()

    # Update lead status to queued
    sb.table("leads").update({"status": "queued", "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", lead_id).execute()

    return {"lead_id": lead_id, "channel": result["channel"], "message": result["message"], "tokens_used": result.get("tokens_used", 0)}


# --- Send (after HITL approval) ---

@router.post("/send/{lead_id}")
async def send(lead_id: str, user=Depends(get_current_user)):
    from supabase import create_client
    from agents.outreach.sender_agent import send_message
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

    lead = sb.table("leads").select("*").eq("id", lead_id).eq("workspace_id", user["workspace_id"]).single().execute()
    if not lead.data:
        raise HTTPException(404, "Lead no encontrado")

    restaurant = sb.table("restaurants").select("*").eq("id", lead.data["restaurant_id"]).single().execute()
    if not restaurant.data:
        raise HTTPException(404, "Restaurante no encontrado")

    # Get pending outreach log
    log = sb.table("outreach_log").select("*").eq("lead_id", lead_id).eq("status", "pending").order("created_at", desc=True).limit(1).execute()
    if not log.data:
        raise HTTPException(400, "No hay mensaje pendiente. Genera uno primero con /generate.")

    log_entry = log.data[0]
    message_data = json.loads(log_entry["message_body"])
    channel = log_entry["channel"]

    # Send
    result = await send_message(lead.data, restaurant.data, message_data, channel)

    now = datetime.now(timezone.utc).isoformat()

    # Update outreach log
    sb.table("outreach_log").update({
        "status": result.get("status", "failed"),
        "sent_at": result.get("sent_at"),
        "error_message": result.get("error"),
    }).eq("id", log_entry["id"]).execute()

    # Update lead
    update_data = {"updated_at": now, "last_contact_at": now}
    if result.get("status") == "sent":
        update_data["status"] = "contacted"
        if not lead.data.get("first_contact_at"):
            update_data["first_contact_at"] = now
    sb.table("leads").update(update_data).eq("id", lead_id).execute()

    return {"lead_id": lead_id, "send_status": result.get("status"), "error": result.get("error")}


# --- Run full pipeline ---

@router.post("/run-pipeline")
async def run_pipeline(req: RunPipelineRequest, user=Depends(get_current_user)):
    from agents.outreach.scraper_agent import scrape_zone
    from agents.outreach.enricher_agent import enrich_all_pending
    from agents.outreach.scorer_agent import score_all_pending

    workspace_id = user["workspace_id"]
    results = {}

    # Step 1: Scrape
    results["scrape"] = await scrape_zone(workspace_id, req.zone, req.category, req.limit)

    # Step 2: Enrich
    results["enrich"] = await enrich_all_pending(workspace_id)

    # Step 3: Score
    results["score"] = await score_all_pending(workspace_id, req.min_score)

    return results


# --- Leads list ---

@router.get("/leads")
async def list_leads(
    status: Optional[str] = None,
    segment: Optional[str] = None,
    min_score: Optional[int] = None,
    zone: Optional[str] = None,
    user=Depends(get_current_user),
):
    from supabase import create_client
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

    query = sb.table("leads").select("*, restaurants(name, zone, google_rating, review_count, email, instagram_handle, phone, category, has_digital_menu)").eq("workspace_id", user["workspace_id"])

    if status:
        query = query.eq("status", status)
    if segment:
        query = query.eq("segment", segment)
    if min_score:
        query = query.gte("priority_score", min_score)

    result = query.order("priority_score", desc=True).execute()

    leads = result.data or []
    # Filter by zone if needed (join filter)
    if zone:
        leads = [l for l in leads if l.get("restaurants", {}).get("zone") == zone]

    return {"leads": leads, "total": len(leads)}


# --- Stats ---

@router.get("/stats")
async def stats(user=Depends(get_current_user)):
    from supabase import create_client
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    wid = user["workspace_id"]

    restaurants = sb.table("restaurants").select("id", count="exact").eq("workspace_id", wid).execute()
    leads_all = sb.table("leads").select("id, status", count="exact").eq("workspace_id", wid).execute()

    leads = leads_all.data or []
    contacted = len([l for l in leads if l["status"] in ("contacted", "replied", "demo_scheduled", "closed_won")])
    replied = len([l for l in leads if l["status"] in ("replied", "demo_scheduled", "closed_won")])
    demos = len([l for l in leads if l["status"] == "demo_scheduled"])
    won = len([l for l in leads if l["status"] == "closed_won"])

    # Channel breakdown
    logs = sb.table("outreach_log").select("channel, status").eq("workspace_id", wid).execute()
    channel_stats = {}
    for log in (logs.data or []):
        ch = log["channel"]
        if ch not in channel_stats:
            channel_stats[ch] = {"sent": 0, "delivered": 0, "failed": 0}
        status = log.get("status", "pending")
        if status in channel_stats[ch]:
            channel_stats[ch][status] += 1

    return {
        "restaurants_discovered": restaurants.count or 0,
        "total_leads": len(leads),
        "contacted": contacted,
        "replied": replied,
        "demos_scheduled": demos,
        "closed_won": won,
        "conversion_rate": round(replied / contacted * 100, 1) if contacted else 0,
        "channel_breakdown": channel_stats,
    }


# --- Follow-up manual trigger ---

@router.post("/followup/run")
async def run_followup(user=Depends(get_current_user)):
    from agents.outreach.followup_agent import run_followups
    result = await run_followups(user["workspace_id"])
    return result
