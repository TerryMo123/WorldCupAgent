from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    team_a: str = Field(..., min_length=1, description="球队 A（中文名或 id，如 巴西 / brazil）")
    team_b: str = Field(..., min_length=1, description="球队 B（中文名或 id，如 法国 / france）")
    query: str | None = Field(
        default=None,
        description="可选具体问题；默认做全面优劣对比",
    )
    user_id: str | None = Field(default=None, description="Optional user identifier")
