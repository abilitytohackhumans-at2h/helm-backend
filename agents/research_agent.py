from agents.base_agent import BaseAgent
from tools.web_search import web_search, WEB_SEARCH_TOOL

SYSTEM_PROMPT = """Eres el agente de Research e Inteligencia de HELM.

Metodologia obligatoria:
- Minimo 5 fuentes antes de concluir.
- Distingue dato verificado / estimacion / opinion.
- Incluye seccion "Limitaciones del analisis".
- Resumen ejecutivo primero, detalle despues.
- Cita todas las fuentes con fecha de consulta.

Formato: informe .md con frontmatter de metadatos."""

class ResearchAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="Research",
            system_prompt=SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL],
        )

    async def _execute_tool(self, name: str, inputs: dict):
        if name == "web_search":
            return await web_search(inputs["query"], inputs.get("count", 5))
        raise NotImplementedError(f"Tool {name} no implementada")
