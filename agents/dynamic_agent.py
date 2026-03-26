"""
DynamicAgent: agente creado dinamicamente desde la DB.
Reemplaza los agentes hardcodeados — cualquier workspace puede tener
agentes con slugs y prompts custom.
"""
from agents.base_agent import BaseAgent
from tools.web_search import web_search, WEB_SEARCH_TOOL
from tools.file_tool import file_create, FILE_CREATE_TOOL
from tools.instagram_tool import (
    instagram_publish, INSTAGRAM_PUBLISH_TOOL,
    instagram_get_insights, INSTAGRAM_GET_INSIGHTS_TOOL,
    instagram_read_comments, INSTAGRAM_READ_COMMENTS_TOOL,
    instagram_reply_comment, INSTAGRAM_REPLY_COMMENT_TOOL,
)
from tools.image_tool import (
    freepik_generate, FREEPIK_GENERATE_TOOL,
    dalle_generate, DALLE_GENERATE_TOOL,
)

# Registry of available tools
# Handlers accept (name, inputs, **kwargs) — workspace_id passed via kwargs
TOOL_REGISTRY = {
    "web_search": {
        "definition": WEB_SEARCH_TOOL,
        "handler": lambda name, inputs, **kw: web_search(inputs["query"], inputs.get("count", 5)),
    },
    "file_create": {
        "definition": FILE_CREATE_TOOL,
        "handler": lambda name, inputs, **kw: file_create(inputs["filename"], inputs["content"]),
    },
    "instagram_publish": {
        "definition": INSTAGRAM_PUBLISH_TOOL,
        "handler": lambda name, inputs, **kw: instagram_publish(kw.get("workspace_id", ""), inputs),
    },
    "instagram_get_insights": {
        "definition": INSTAGRAM_GET_INSIGHTS_TOOL,
        "handler": lambda name, inputs, **kw: instagram_get_insights(kw.get("workspace_id", ""), inputs),
    },
    "instagram_read_comments": {
        "definition": INSTAGRAM_READ_COMMENTS_TOOL,
        "handler": lambda name, inputs, **kw: instagram_read_comments(kw.get("workspace_id", ""), inputs),
    },
    "instagram_reply_comment": {
        "definition": INSTAGRAM_REPLY_COMMENT_TOOL,
        "handler": lambda name, inputs, **kw: instagram_reply_comment(kw.get("workspace_id", ""), inputs),
    },
    "freepik_generate": {
        "definition": FREEPIK_GENERATE_TOOL,
        "handler": lambda name, inputs, **kw: freepik_generate(kw.get("workspace_id", ""), inputs),
    },
    "dalle_generate": {
        "definition": DALLE_GENERATE_TOOL,
        "handler": lambda name, inputs, **kw: dalle_generate(kw.get("workspace_id", ""), inputs),
    },
}


class DynamicAgent(BaseAgent):
    """Agent whose prompt and tools are loaded from the database."""

    def __init__(self, slug: str, name: str, system_prompt: str, tools_enabled: list[str], workspace_id: str = ""):
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
        self.workspace_id = workspace_id

    async def _execute_tool(self, name: str, inputs: dict):
        handler = self._handlers.get(name)
        if handler:
            return await handler(name, inputs, workspace_id=self.workspace_id)
        raise NotImplementedError(f"Tool {name} no disponible para agente {self.name}")
