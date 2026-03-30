"""Agent 3: Scorer - Puntua restaurantes y los convierte en leads."""
from config import settings


def score_restaurant(restaurant: dict) -> dict:
    """Scoring deterministico - NO usa Claude API."""
    score = 0
    breakdown = {}

    # Rating Google
    rating = restaurant.get("google_rating") or 0
    if rating >= 4.5:
        score += 3
        breakdown["rating"] = "+3 (>= 4.5)"
    elif rating >= 4.0:
        score += 2
        breakdown["rating"] = "+2 (>= 4.0)"

    # Volumen resenas
    reviews = restaurant.get("review_count") or 0
    if reviews > 500:
        score += 2
        breakdown["reviews"] = "+2 (> 500)"
    elif reviews >= 200:
        score += 1
        breakdown["reviews"] = "+1 (>= 200)"

    # Sin carta digital = MAXIMO IMPACTO
    has_digital = restaurant.get("has_digital_menu")
    if has_digital is False:
        score += 3
        breakdown["no_digital_menu"] = "+3 (sin carta digital)"
    elif has_digital is None:
        score += 1
        breakdown["no_digital_menu"] = "+1 (no verificado)"

    # Senales turisticas
    languages = restaurant.get("languages_detected") or []
    non_es = [l for l in languages if l != "es"]
    if len(non_es) >= 2:
        score += 2
        breakdown["tourist_langs"] = f"+2 ({len(non_es)} idiomas no-ES)"
    elif len(non_es) == 1:
        score += 1
        breakdown["tourist_langs"] = "+1 (1 idioma no-ES)"

    # Precio alto
    price = restaurant.get("price_level") or 0
    if price >= 3:
        score += 1
        breakdown["price"] = "+1 (price_level >= 3)"

    # Michelin / Repsol
    if restaurant.get("michelin_mentioned"):
        score += 2
        breakdown["michelin"] = "+2 (Michelin mencionado)"
    if restaurant.get("repsol_mentioned"):
        score += 2
        breakdown["repsol"] = "+2 (Repsol mencionado)"

    # Tiene email
    if restaurant.get("email"):
        score += 1
        breakdown["has_email"] = "+1 (email disponible)"

    # Tiene Instagram
    if restaurant.get("instagram_handle"):
        score += 1
        breakdown["has_instagram"] = "+1 (Instagram disponible)"

    # Cap at 10
    score = min(score, 10)

    # Determine segment
    segment = "tourist"
    if restaurant.get("michelin_mentioned") or restaurant.get("repsol_mentioned") or price >= 3:
        segment = "fine_dining"
    if (restaurant.get("tourist_signals") or 0) >= 5 and segment == "fine_dining":
        segment = "both"

    # Determine preferred channel
    preferred_channel = "phone"  # default fallback
    fallback_channels = []

    if restaurant.get("email"):
        preferred_channel = "email"
        if restaurant.get("instagram_handle"):
            fallback_channels.append("instagram_dm")
        if restaurant.get("whatsapp_number"):
            fallback_channels.append("whatsapp")
    elif restaurant.get("whatsapp_number"):
        preferred_channel = "whatsapp"
        if restaurant.get("instagram_handle"):
            fallback_channels.append("instagram_dm")
    elif restaurant.get("instagram_handle"):
        preferred_channel = "instagram_dm"
    elif restaurant.get("website"):
        preferred_channel = "web_form"

    fallback_channels.append("phone")  # always as last resort

    return {
        "priority_score": score,
        "segment": segment,
        "score_breakdown": breakdown,
        "preferred_channel": preferred_channel,
        "fallback_channels": fallback_channels,
    }


async def score_all_pending(workspace_id: str, min_score: int = 3) -> dict:
    """Puntua todos los restaurantes enriquecidos que no tienen lead."""
    from supabase import create_client
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

    # Get enriched restaurants without a lead
    restaurants = sb.table("restaurants").select("*").eq("workspace_id", workspace_id).not_.is_("enriched_at", "null").execute()

    existing_leads = sb.table("leads").select("restaurant_id").eq("workspace_id", workspace_id).execute()
    existing_ids = {l["restaurant_id"] for l in (existing_leads.data or [])}

    scored = 0
    created = 0
    for r in (restaurants.data or []):
        if r["id"] in existing_ids:
            continue

        result = score_restaurant(r)
        scored += 1

        if result["priority_score"] >= min_score:
            lead = {
                "workspace_id": workspace_id,
                "restaurant_id": r["id"],
                **result,
            }
            try:
                sb.table("leads").insert(lead).execute()
                created += 1
            except Exception:
                pass

    return {"scored": scored, "leads_created": created, "min_score": min_score}
