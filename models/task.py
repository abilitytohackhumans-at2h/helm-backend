from pydantic import BaseModel
from typing import Optional

class TaskRequest(BaseModel):
    user_input: str
    workspace_id: str

class TaskResponse(BaseModel):
    id: str
    workspace_id: str
    user_input: str
    status: str
    plan_json: Optional[dict] = None
    result_json: Optional[dict] = None
    assigned_agents: list[str] = []
    tokens_used: int = 0
    cost_usd: float = 0.0
    created_at: str
    completed_at: Optional[str] = None
