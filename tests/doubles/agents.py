from shared.db import AgentName
from worker.agents.base import AgentResult, PRContext
from worker.findings import AgentOutput, Finding


class FakeAgentRunner:
    """Returns fixed findings per agent, so pipeline tests are deterministic and free."""

    def __init__(
        self,
        findings: dict[AgentName, list[Finding]] | None = None,
        fail: set[AgentName] | None = None,
    ):
        self.findings = findings or {}
        self.fail = fail or set()
        self.calls: list[tuple[AgentName, PRContext]] = []

    async def run(self, agent: AgentName, pr: PRContext) -> AgentResult:
        self.calls.append((agent, pr))
        if agent in self.fail:
            raise RuntimeError(f"{agent} agent exploded")
        return AgentResult(
            agent=agent,
            model="claude-haiku-4-5",
            output=AgentOutput(summary=f"{agent} summary", findings=self.findings.get(agent, [])),
            input_tokens=1000,
            output_tokens=200,
        )
