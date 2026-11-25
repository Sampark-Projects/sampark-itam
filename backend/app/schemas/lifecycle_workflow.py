import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class WorkflowStepIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    step_type: Literal["task", "approval"] = "task"
    role_id: Optional[uuid.UUID] = None
    required_fields: List[str] = Field(default_factory=list)
    requires_document: bool = False
    document_category: Optional[str] = Field(None, max_length=30)
    requires_comment: bool = False
    confirm_statement: Optional[str] = Field(None, max_length=255)
    sets_status_id: Optional[uuid.UUID] = None


class WorkflowDefinitionIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    allow_self_approval: bool = False
    steps: List[WorkflowStepIn] = Field(..., min_length=1, max_length=15)


class StartRunIn(BaseModel):
    kind: Literal["onboarding", "retirement"]


class StepActionIn(BaseModel):
    comment: Optional[str] = Field(None, max_length=2000)
    confirmed: bool = False


class CancelRunIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=2000)
