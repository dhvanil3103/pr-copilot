"""The real LangChain agent runner, over HTTP, against the mock Anthropic API."""

import pytest

from shared.config import Settings
from shared.db import AgentName
from tests.doubles.github import FakeGitHubClient
from tests.e2e.mocks.anthropic.app import app as mock_anthropic
from tests.servers import serve
from worker.agents.base import PRContext
from worker.agents.langchain_runner import LangChainAgentRunner
from worker.diff import select_files

FILES = [
    {"filename": "app.py", "status": "modified", "additions": 1,
     "patch": "@@ -3,2 +3,3 @@\n a = 1\n+b = eval(x)\n c = 3"},
    {"filename": "lib/util.js", "status": "added", "additions": 2,
     "patch": "@@ -0,0 +1,2 @@\n+const x = 1;\n+export default x;"},
]  # fmt: skip


@pytest.fixture(scope="module")
def anthropic_url():
    with serve(mock_anthropic) as url:
        yield url


def make_pr() -> PRContext:
    return PRContext(
        repo="o/r",
        pr_number=1,
        head_sha="abc",
        installation_id=1,
        files=select_files(FILES, 10_000).files,
        github=FakeGitHubClient(),
    )


@pytest.mark.parametrize("agent", list(AgentName))
async def test_runner_uses_tools_and_returns_structured_findings(anthropic_url, agent):
    settings = Settings(
        anthropic_api_key="test-key", anthropic_base_url=anthropic_url, test_agent_model="m-test"
    )
    result = await LangChainAgentRunner(settings).run(agent, make_pr())

    assert result.error is None
    assert result.model == settings.model_for(agent)
    assert result.tool_calls == ["list_changed_files", "get_pr_diff", "get_pr_diff"]
    findings = {(f.file_path, f.line) for f in result.output.findings}
    # The mock cites the first added line it sees, i.e. the line numbers our tool produced.
    assert findings == {("app.py", 4), ("lib/util.js", 1)}
    assert result.input_tokens > 0 and result.output_tokens > 0


async def test_model_call_limit_stops_the_agent(anthropic_url):
    # Two model calls are not enough for the mock's three-turn plan.
    settings = Settings(
        anthropic_api_key="k", anthropic_base_url=anthropic_url, agent_max_model_calls=2
    )
    result = await LangChainAgentRunner(settings).run(AgentName.review, make_pr())
    assert result.output is None
    assert "stopped before" in result.error
