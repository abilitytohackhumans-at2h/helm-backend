import anthropic
from typing import Any
from config import settings

class BaseAgent:
    def __init__(self, name: str, system_prompt: str, tools: list | None = None):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def run(self, task: str, context: str = "") -> dict:
        """Bucle agentico: llama al modelo, ejecuta tools, repite hasta end_turn."""
        full_prompt = f"{context}\n\n{task}" if context else task
        messages = [{"role": "user", "content": full_prompt}]
        tokens_used = 0

        while True:
            kwargs: dict[str, Any] = {
                "model": settings.MODEL_NAME,
                "max_tokens": 4096,
                "system": self.system_prompt,
                "messages": messages,
            }
            if self.tools:
                kwargs["tools"] = self.tools

            response = self.client.messages.create(**kwargs)
            tokens_used += response.usage.input_tokens + response.usage.output_tokens

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = await self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result)
                        })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

            else:  # end_turn
                text = next((b.text for b in response.content if hasattr(b, "text")), "")
                return {"output": text, "tokens_used": tokens_used}

    async def _execute_tool(self, name: str, inputs: dict) -> Any:
        """Override en cada agente para sus tools especificas."""
        raise NotImplementedError(f"Tool {name} no implementada en {self.name}")
