from agents.base_agent import BaseAgent
from tools.web_search import web_search, WEB_SEARCH_TOOL
from tools.file_tool import file_create, FILE_CREATE_TOOL

SYSTEM_PROMPT = """Eres el agente de Social Media de HELM.
Plataformas: Instagram, LinkedIn, TikTok, X/Twitter, YouTube.

Produccion estandar por post:
- Copy principal (adaptado a cada plataforma).
- Variante corta (para stories o reels).
- Hashtags (max 5, relevantes, no genericos).
- Horario optimo de publicacion.

Calendario semanal incluye: tema / formato / plataforma / hook.
Output: tabla Markdown o CSV importable."""

class SocialAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="Social",
            system_prompt=SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL, FILE_CREATE_TOOL],
        )

    async def _execute_tool(self, name: str, inputs: dict):
        if name == "web_search":
            return await web_search(inputs["query"], inputs.get("count", 5))
        if name == "file_create":
            return await file_create(inputs["filename"], inputs["content"])
        raise NotImplementedError(f"Tool {name} no implementada")
