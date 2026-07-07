from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: float = Field(ge=0)


class AgentResponse(BaseModel):
    answer: str
    stats: ToolResult
    rag: ToolResult
    suggestion: ToolResult
    degraded: list[str] = Field(default_factory=list)
    total_latency_ms: float = Field(ge=0)
