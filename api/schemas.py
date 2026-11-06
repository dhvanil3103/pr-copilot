from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from shared.db import AgentName, ReviewStatus, Severity


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent: AgentName
    file_path: str
    line: int
    severity: Severity
    category: str
    body: str
    posted: bool
    created_at: datetime


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_full_name: str
    pr_number: int
    head_sha: str
    status: ReviewStatus
    error_message: str | None
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    comment_count: int = 0

    @computed_field
    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    @computed_field
    @property
    def pr_url(self) -> str:
        return f"https://github.com/{self.repo_full_name}/pull/{self.pr_number}"


class ReviewDetail(ReviewOut):
    summary: str | None
    comments: list[CommentOut]


class ReviewPage(BaseModel):
    items: list[ReviewOut]
    total: int
    page: int
    page_size: int


class Stats(BaseModel):
    total_reviews: int
    counts_by_status: dict[ReviewStatus, int]
    avg_duration_seconds: float | None
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
