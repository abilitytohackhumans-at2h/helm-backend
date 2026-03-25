from agents.base_agent import BaseAgent
from tools.web_search import web_search, WEB_SEARCH_TOOL
from tools.file_tool import file_create, FILE_CREATE_TOOL

SYSTEM_PROMPT = """Eres el agente de Contenido de HELM.
Especialidades: articulos, guiones, newsletters, posts longform, scripts.

Estandar de calidad:
- Estructura: gancho potente / desarrollo / call to action.
- Tono cinematografico y editorial cuando el brief lo permite.
- SEO natural, nunca forzado.
- Revisa coherencia de marca antes de entregar.

Entrega en Markdown con metadatos en frontmatter YAML."""

class ContentAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="Content",
            system_prompt=SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL, FILE_CREATE_TOOL],
        )

    async def _execute_tool(self, name: str, inputs: dict):
        if name == "web_search":
            return await web_search(inputs["query"], inputs.get("count", 5))
        if name == "file_create":
            return await file_create(inputs["filename"], inputs["content"])
        raise NotImplementedError(f"Tool {name} no implementada")
