"""
DynamicAgent: agente creado dinamicamente desde la DB.
Reemplaza los agentes hardcodeados — cualquier workspace puede tener
agentes con slugs y prompts custom.
"""
from agents.base_agent import BaseAgent
from tools.web_search import web_search, WEB_SEARCH_TOOL
from tools.file_tool import file_create, FILE_CREATE_TOOL

# Registry of available tools
TOOL_REGISTRY = {
    "web_search": {
        "definition": WEB_SEARCH_TOOL,
        "handler": lambda name, inputs: web_search(inputs["query"], inputs.get("count", 5)),
    },
    "file_create": {
        "definition": FILE_CREATE_TOOL,
        "handler": lambda name, inputs: file_create(inputs["filename"], inputs["content"]),
    },
}


class DynamicAgent(BaseAgent):
    """Agent whose prompt and tools are loaded from the database."""

    def __init__(self, slug: str, name: str, system_prompt: str, tools_enabled: list[str]):
        # Build tool definitions from registry
        tool_defs = []
        self._handlers: dict = {}
        for tool_slug in tools_enabled:
            if tool_slug in TOOL_REGISTRY:
                tool_defs.append(TOOL_REGISTRY[tool_slug]["definition"])
                self._handlers[tool_slug] = TOOL_REGISTRY[tool_slug]["handler"]

        super().__init__(
            name=name,
            system_prompt=system_prompt,
            tools=tool_defs if tool_defs else None,
        )
        self.slug = slug

    async def _execute_tool(self, name: str, inputs: dict):
        handler = self._handlers.get(name)
        if handler:
            return await handler(name, inputs)
        raise NotImplementedError(f"Tool {name} no disponible para agente {self.name}")
