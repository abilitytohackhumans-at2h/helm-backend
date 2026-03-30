"""Agent 2: Enricher - Enriquece restaurantes con datos de contacto."""
import httpx
import json
import re
from config import settings


async def enrich_restaurant(restaurant: dict) -> dict:
    """Enriquece un restaurante con datos de contacto via Google Place Details + web scraping."""
    updates = {}
    place_id = restaurant.get("google_place_id")

    if not place_id or not settings.GOOGLE_PLACES_API_KEY:
        return updates

    # 1. Google Place Details - phone, website
    async with httpx.AsyncClient(timeout=20) as client:
        url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {
            "place_id": place_id,
            "fields": "formatted_phone_number,website,opening_hours,reviews",
            "language": "es",
            "key": settings.GOOGLE_PLACES_API_KEY,
        }
        resp = await client.get(url, params=params)
        details = resp.json().get("result", {})

        if details.get("formatted_phone_number"):
            updates["phone"] = details["formatted_phone_number"]

        if details.get("website"):
            updates["website"] = details["website"]

        # Detect languages from reviews
        reviews = details.get("reviews", [])
        languages = set()
        for review in reviews:
            lang = review.get("language", "es")
            languages.add(lang)
        if languages:
            updates["languages_detected"] = list(languages)
            # Tourist signal: multiple non-Spanish languages
            non_es = [l for l in languages if l != "es"]
            updates["tourist_signals"] = min(len(non_es) * 3, 10)

        # 2. Try to extract email from website
        website = updates.get("website") or restaurant.get("website")
        if website:
            try:
                resp_web = await client.get(website, follow_redirects=True, timeout=10)
                html = resp_web.text[:50000]  # limit

                # Extract emails
                emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html)
                valid_emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.gif'))]
                if valid_emails:
                    updates["email"] = valid_emails[0]

                # Extract Instagram handle
                ig_matches = re.findall(r'(?:instagram\.com|instagr\.am)/([a-zA-Z0-9_.]+)', html)
                if ig_matches:
                    handle = ig_matches[0].strip('/')
                    if handle not in ('p', 'reel', 'stories', 'explore'):
                        updates["instagram_handle"] = handle

                # Detect digital menu
                menu_signals = ['qr', 'carta digital', 'menu digital', 'digital menu',
                                'qamarero', 'covermanager', 'thefork']
                has_digital = any(signal in html.lower() for signal in menu_signals)
                updates["has_digital_menu"] = has_digital

                # Detect Michelin / Repsol
                text_lower = html.lower()
                updates["michelin_mentioned"] = 'michelin' in text_lower
                updates["repsol_mentioned"] = 'repsol' in text_lower or 'sol repsol' in text_lower

            except Exception:
                updates["has_digital_menu"] = None

    return updates


async def enrich_all_pending(workspace_id: str) -> dict:
    """Enriquece todos los restaurantes pendientes de un workspace."""
    from supabase import create_client
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

    # Get restaurants without enrichment
    result = sb.table("restaurants").select("*").eq("workspace_id", workspace_id).is_("enriched_at", "null").limit(50).execute()
    restaurants = result.data or []

    enriched_count = 0
    for restaurant in restaurants:
        try:
            updates = await enrich_restaurant(restaurant)
            if updates:
                from datetime import datetime, timezone
                updates["enriched_at"] = datetime.now(timezone.utc).isoformat()
                sb.table("restaurants").update(updates).eq("id", restaurant["id"]).execute()
                enriched_count += 1
        except Exception:
            pass

    return {"total": len(restaurants), "enriched": enriched_count}
