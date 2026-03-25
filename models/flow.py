from pydantic import BaseModel
from typing import Optional


class FlowCreate(BaseModel):
    workspace_id: str
    name: str
    prompt: str
    cron_expression: Optional[str] = None


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    cron_expression: Optional[str] = None
    is_active: Optional[bool] = None
