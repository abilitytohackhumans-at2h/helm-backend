from agents.base_agent import BaseAgent
from tools.web_search import web_search, WEB_SEARCH_TOOL
from tools.file_tool import file_create, FILE_CREATE_TOOL

SYSTEM_PROMPT = """Eres el agente de Marketing de HELM / ATH2 Agency.
Estetica y nivel de referencia: Jordi Urbea / Ogilvy Barcelona.

Especialidades: copies publicitarios, naming, taglines, briefings creativos,
estrategia de campana, propuestas de valor.

Reglas de produccion:
- Entrega siempre 3 variantes de cualquier copy.
- Documenta el insight estrategico antes del copy.
- El tono se adapta al brief: nunca sacrifiques calidad por velocidad.
- Formato de entrega: Markdown estructurado."""

class MarketingAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="Marketing",
            system_prompt=SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL, FILE_CREATE_TOOL],
        )

    async def _execute_tool(self, name: str, inputs: dict):
        if name == "web_search":
            return await web_search(inputs["query"], inputs.get("count", 5))
        if name == "file_create":
            return await file_create(inputs["filename"], inputs["content"])
        raise NotImplementedError(f"Tool {name} no implementada")
