import httpx
from config import settings

async def web_search(query: str, count: int = 5) -> str:
    """Busqueda web usando Brave Search API."""
    key = settings.BRAVE_SEARCH_API_KEY
    if not key or key.startswith("BSA...") or len(key) < 10:
        return f"[Web search no disponible - API key no configurada] Busqueda solicitada: '{query}'. Responde con tu conocimiento interno."

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={"X-Subscription-Token": key},
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for r in data.get("web", {}).get("results", [])[:count]:
            results.append(f"- {r['title']}: {r.get('description', '')}\n  URL: {r['url']}")

        return "\n".join(results) if results else "No se encontraron resultados."
    except Exception as e:
        return f"[Error en web search: {str(e)[:100]}] Responde con tu conocimiento interno."

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": "Busca informacion en internet usando Brave Search. Usa esta herramienta cuando necesites datos actualizados, investigar un tema, o verificar informacion.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "La consulta de busqueda"
            },
            "count": {
                "type": "integer",
                "description": "Numero de resultados (default 5)",
                "default": 5
            }
        },
        "required": ["query"]
    }
}
