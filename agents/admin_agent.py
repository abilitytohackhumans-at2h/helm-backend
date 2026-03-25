from agents.base_agent import BaseAgent
from tools.file_tool import file_create, FILE_CREATE_TOOL

SYSTEM_PROMPT = """Eres el agente de Administracion de HELM.
Especialidades: emails, agenda, gestion documental, recordatorios.

REGLAS CRITICAS DE SEGURIDAD:
- NUNCA envies un email sin mostrar el borrador y marcar hitl_required=true.
- NUNCA elimines eventos o archivos sin confirmacion explicita del usuario.
- Toda accion irreversible es HITL obligatorio, sin excepcion.
- Redacta en el tono de la agencia: directo, profesional, cercano."""

class AdminAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="Admin",
            system_prompt=SYSTEM_PROMPT,
            tools=[FILE_CREATE_TOOL],
        )

    async def _execute_tool(self, name: str, inputs: dict):
        if name == "file_create":
            return await file_create(inputs["filename"], inputs["content"])
        raise NotImplementedError(f"Tool {name} no implementada")
