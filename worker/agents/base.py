from dataclasses import dataclass, field
from typing import Protocol

from shared.db import AgentName
from worker.diff import ChangedFile
from worker.findings import AgentOutput
from worker.github import GitHubClient


@dataclass
class PRContext:
    repo: str
    pr_number: int
    head_sha: str
    installation_id: int
    files: list[ChangedFile]
    github: GitHubClient


@dataclass
class AgentResult:
    agent: AgentName
    model: str
    output: AgentOutput | None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    tool_calls: list[str] = field(default_factory=list)


class AgentRunner(Protocol):
    """Runs one agent over a PR.

    The worker depends on this interface, not on LangChain, so integration tests
    can inject a deterministic runner and evals can call the real one directly.
    """

    async def run(self, agent: AgentName, pr: PRContext) -> AgentResult: ...
