"""Agent 1: Scraper - Descubre restaurantes via Google Places API."""
import httpx
import json
from agents.base_agent import BaseAgent
from config import settings

SYSTEM_PROMPT = """Eres el agente Scraper del pipeline WeNeedToEat.
Tu mision: descubrir restaurantes en una zona geografica usando Google Places API.
Filtras por rating >= 4.0 y reviews >= 50.
Devuelves los datos crudos para insertar en la tabla restaurants de Supabase."""

TOOLS = [
    {
        "name": "google_places_search",
        "description": "Busca restaurantes en Google Places por zona y categoria. Devuelve nombre, direccion, rating, reviews, price_level, place_id, maps_url.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Busqueda ej: 'restaurantes centro Madrid turisticos'"},
                "location": {"type": "string", "description": "Lat,Lng del centro de busqueda ej: '40.4168,-3.7038'"},
                "radius": {"type": "integer", "description": "Radio en metros", "default": 2000},
            },
            "required": ["query"]
        }
    }
]


class ScraperAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Scraper", system_prompt=SYSTEM_PROMPT, tools=TOOLS)
        self.api_key = settings.GOOGLE_PLACES_API_KEY

    async def _execute_tool(self, name: str, inputs: dict):
        if name == "google_places_search":
            return await self._search_places(inputs)
        return f"Tool {name} no disponible"

    async def _search_places(self, inputs: dict) -> str:
        query = inputs["query"]
        location = inputs.get("location", "40.4168,-3.7038")  # Madrid centro
        radius = inputs.get("radius", 2000)

        if not self.api_key:
            return json.dumps({"error": "GOOGLE_PLACES_API_KEY no configurada"})

        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": query,
            "location": location,
            "radius": radius,
            "type": "restaurant",
            "language": "es",
            "key": self.api_key,
        }

        results = []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            data = resp.json()

            for place in data.get("results", []):
                rating = place.get("rating", 0)
                reviews = place.get("user_ratings_total", 0)
                if rating >= 4.0 and reviews >= 50:
                    results.append({
                        "google_place_id": place["place_id"],
                        "name": place["name"],
                        "address": place.get("formatted_address", ""),
                        "google_rating": rating,
                        "review_count": reviews,
                        "price_level": place.get("price_level"),
                        "maps_url": f"https://www.google.com/maps/place/?q=place_id:{place['place_id']}",
                    })

            # Get next page if available
            next_token = data.get("next_page_token")
            if next_token and len(results) < 60:
                import asyncio
                await asyncio.sleep(2)  # Google requires delay for next_page_token
                params["pagetoken"] = next_token
                del params["query"]
                resp2 = await client.get(url, params=params)
                data2 = resp2.json()
                for place in data2.get("results", []):
                    rating = place.get("rating", 0)
                    reviews = place.get("user_ratings_total", 0)
                    if rating >= 4.0 and reviews >= 50:
                        results.append({
                            "google_place_id": place["place_id"],
                            "name": place["name"],
                            "address": place.get("formatted_address", ""),
                            "google_rating": rating,
                            "review_count": reviews,
                            "price_level": place.get("price_level"),
                            "maps_url": f"https://www.google.com/maps/place/?q=place_id:{place['place_id']}",
                        })

        return json.dumps({"restaurants": results, "total": len(results)}, ensure_ascii=False)


async def scrape_zone(workspace_id: str, zone: str, category: str = "restaurantes", limit: int = 20) -> dict:
    """Funcion directa sin agente - mas eficiente para scraping masivo."""
    from supabase import create_client
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

    queries = [
        f"{category} {zone} turisticos",
        f"{category} {zone} fine dining",
        f"mejores {category} {zone}",
    ]

    all_restaurants = []
    seen_ids = set()

    async with httpx.AsyncClient(timeout=30) as client:
        for query in queries:
            if len(all_restaurants) >= limit:
                break

            url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
            params = {
                "query": query,
                "type": "restaurant",
                "language": "es",
                "key": settings.GOOGLE_PLACES_API_KEY,
            }
            resp = await client.get(url, params=params)
            data = resp.json()

            for place in data.get("results", []):
                pid = place["place_id"]
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)

                rating = place.get("rating", 0)
                reviews = place.get("user_ratings_total", 0)
                if rating < 4.0 or reviews < 50:
                    continue

                restaurant = {
                    "workspace_id": workspace_id,
                    "google_place_id": pid,
                    "name": place["name"],
                    "address": place.get("formatted_address", ""),
                    "zone": zone,
                    "category": category,
                    "google_rating": float(rating),
                    "review_count": reviews,
                    "price_level": place.get("price_level"),
                    "maps_url": f"https://www.google.com/maps/place/?q=place_id:{pid}",
                }
                all_restaurants.append(restaurant)

                if len(all_restaurants) >= limit:
                    break

    # Upsert into Supabase
    inserted = 0
    for r in all_restaurants:
        try:
            sb.table("restaurants").upsert(r, on_conflict="google_place_id").execute()
            inserted += 1
        except Exception:
            pass

    return {"scraped": len(all_restaurants), "inserted": inserted, "zone": zone}
