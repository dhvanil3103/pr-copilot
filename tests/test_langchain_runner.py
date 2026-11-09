"""The real LangChain agent runner, over HTTP, against the mock Anthropic API."""

import pytest

from shared.config import Settings
from shared.db import AgentName
from tests.doubles.github import FakeGitHubClient
from tests.e2e.mocks.anthropic.app import app as mock_anthropic
from tests.servers import serve
from worker.agents.base import PRContext
from worker.agents.bedrock import ChatAnthropicBedrock
from worker.agents.langchain_runner import (
    LangChainAgentRunner,
    bedrock_model_id,
    uses_bedrock_messages_api,
)
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


async def test_bedrock_provider_uses_mantle_client_and_prefixed_model(anthropic_url, monkeypatch):
    # A bearer token stands in for SigV4 so the request reaches the mock unsigned.
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-bedrock-token")
    settings = Settings(
        llm_provider="bedrock",
        aws_region="us-east-1",
        bedrock_base_url=anthropic_url,
        default_model="claude-sonnet-5",
    )
    runner = LangChainAgentRunner(settings)
    chat = runner._model(AgentName.review)
    assert isinstance(chat, ChatAnthropicBedrock)
    assert chat.model == "anthropic.claude-sonnet-5"

    result = await runner.run(AgentName.review, make_pr())
    assert result.error is None
    assert result.model == "claude-sonnet-5"  # prices and dashboard keep the plain name
    assert {(f.file_path, f.line) for f in result.output.findings} == {
        ("app.py", 4),
        ("lib/util.js", 1),
    }


def test_bedrock_model_id_is_prefixed_once():
    assert bedrock_model_id("claude-sonnet-5") == "anthropic.claude-sonnet-5"
    assert bedrock_model_id("anthropic.claude-sonnet-5") == "anthropic.claude-sonnet-5"


def test_bedrock_routes_versioned_and_non_claude_ids_to_converse():
    assert uses_bedrock_messages_api("claude-sonnet-5")
    assert uses_bedrock_messages_api("anthropic.claude-opus-5")
    assert not uses_bedrock_messages_api("us.anthropic.claude-opus-4-5-20251101-v1:0")
    assert not uses_bedrock_messages_api("us.moonshotai.kimi-k3.1")


def test_rate_limit_is_shared_by_both_agents():
    runner = LangChainAgentRunner(Settings(llm_requests_per_minute=5))
    review, test = runner._model(AgentName.review), runner._model(AgentName.test)
    assert review.rate_limiter is test.rate_limiter is not None
    assert review.rate_limiter.requests_per_second == 5 / 60


def test_no_rate_limit_by_default():
    assert LangChainAgentRunner(Settings())._model(AgentName.review).rate_limiter is None
