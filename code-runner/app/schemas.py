from pydantic import BaseModel, Field
from typing import Optional, List, Dict

# Incoming message

class ForbiddenRule(BaseModel):
    path: str
    reason: str

class ExecutionConfig(BaseModel):
    blacklist: List[ForbiddenRule] = []

class ExecutionRequest(BaseModel):
    submission_id: str = Field(..., description="Code submission id from Kotlin")
    code: str
    config: ExecutionConfig = Field(default_factory=ExecutionConfig)
    timeout: int = Field(default=5)


# Outgoing message

class VariableInfo(BaseModel):
    type: str
    value_preview: str
    shape: Optional[list] = None

class ExecutionResult(BaseModel):
    submission_id: str
    success: bool
    output: str
    error: Optional[str] = None
    truncated: bool = False
    memory_peak_mb: Optional[float] = None
    execution_time: Optional[float] = None
    variables: Optional[Dict[str, VariableInfo]] = None
    system_error: Optional[str] = None
    hotspots: Optional[list[dict]] = None
