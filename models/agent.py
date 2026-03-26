from pydantic import BaseModel
from typing import Optional

class AgentStatus(BaseModel):
    id: str
    workspace_id: str
    name: str
    slug: str
    system_prompt: str
    is_active: bool
    tools_enabled: list[str]
    created_at: str
    status: str = "idle"
    tasks_today: int = 0
    tokens_used: int = 0

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    is_active: Optional[bool] = None
    tools_enabled: Optional[list[str]] = None
    metadata: Optional[dict] = None

class AgentCreate(BaseModel):
    workspace_id: str
    name: str
    slug: str
    system_prompt: str
    tools_enabled: list[str] = []
    metadata: dict = {}
