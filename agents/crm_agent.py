from agents.base_agent import BaseAgent
from tools.file_tool import file_create, FILE_CREATE_TOOL

SYSTEM_PROMPT = """Eres el agente de CRM de HELM.
Especialidades: gestion de leads, pipeline, seguimiento de clientes.

Reglas de operacion:
- Nunca borres datos sin confirmacion explicita (HITL).
- Toda actualizacion incluye timestamp y resumen del cambio.
- Si un cliente lleva mas de 30 dias sin contacto, genera alerta.
- El pipeline tiene etapas: prospecto / contactado / propuesta / negociacion / cerrado."""

class CRMAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="CRM",
            system_prompt=SYSTEM_PROMPT,
            tools=[FILE_CREATE_TOOL],
        )

    async def _execute_tool(self, name: str, inputs: dict):
        if name == "file_create":
            return await file_create(inputs["filename"], inputs["content"])
        raise NotImplementedError(f"Tool {name} no implementada")
