from pydantic import BaseModel
from typing import Optional

class HITLRequest(BaseModel):
    id: str
    task_id: str
    subtask_id: Optional[str] = None
    agent_slug: str
    title: str
    description: str
    payload: Optional[dict] = None
    status: str = "pending"
    decision_note: Optional[str] = None
    created_at: str
    decided_at: Optional[str] = None

class HITLDecision(BaseModel):
    decision_note: Optional[str] = None
