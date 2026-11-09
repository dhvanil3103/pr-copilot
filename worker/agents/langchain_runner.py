import logging
import sys
from pathlib import Path

from botocore.config import Config as BotoConfig
from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy
from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrockConverse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.rate_limiters import InMemoryRateLimiter

from shared.config import Settings
from shared.db import AgentName
from worker.agents.base import AgentResult, PRContext
from worker.agents.bedrock import ChatAnthropicBedrock
from worker.agents.tools import build_tools
from worker.findings import AgentOutput

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
# Bump the file name (review_v2.md) when changing a prompt so evals can compare versions.
PROMPT_FILES = {AgentName.review: "review_v1.md", AgentName.test: "test_v1.md"}


def load_prompt(agent: AgentName) -> str:
    return (PROMPTS_DIR / PROMPT_FILES[agent]).read_text()


def uses_bedrock_messages_api(model: str) -> bool:
    # Bedrock's Messages API serves Claude 4.7+ under unversioned IDs (anthropic.claude-opus-5).
    # Versioned IDs (us.anthropic.claude-opus-4-5-20251101-v1:0) and other vendors' models
    # only work through Converse.
    return "claude" in model and ":" not in model


def bedrock_model_id(model: str) -> str:
    # Config keeps the Claude API name so prices and the dashboard use one key per model.
    return model if model.startswith("anthropic.") else f"anthropic.{model}"


class LangChainAgentRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # One limiter for every model this runner builds, so both agents share the budget.
        rpm = settings.llm_requests_per_minute
        self._rate_limiter = (
            InMemoryRateLimiter(requests_per_second=rpm / 60, max_bucket_size=1) if rpm else None
        )

    def _model(self, agent: AgentName) -> BaseChatModel:
        s = self._settings
        model = s.model_for(agent)
        common = {"max_tokens": s.agent_max_tokens, "timeout": s.agent_timeout_seconds}
        limiter = {"rate_limiter": self._rate_limiter} if self._rate_limiter else {}
        aws_creds = {
            "aws_access_key_id": s.aws_access_key_id,
            "aws_secret_access_key": s.aws_secret_access_key,
            "aws_session_token": s.aws_session_token,
        }
        if s.llm_provider == "bedrock" and not uses_bedrock_messages_api(model):
            return ChatBedrockConverse(
                model_id=model,
                region_name=s.aws_region,
                max_tokens=s.agent_max_tokens,
                # boto's 60s read timeout is too short for a reasoning model's long turns.
                config=BotoConfig(
                    read_timeout=s.agent_timeout_seconds,
                    # Adaptive mode backs off and slows down on ThrottlingException.
                    retries={"max_attempts": 8, "mode": "adaptive"},
                ),
                **{k: v for k, v in aws_creds.items() if v},
                **limiter,
            )
        if s.llm_provider == "bedrock":
            return ChatAnthropicBedrock(
                model=bedrock_model_id(model),
                aws_region=s.aws_region,
                bedrock_base_url=s.bedrock_base_url,
                max_retries=3,
                **aws_creds,
                **common,
                **limiter,
            )
        return ChatAnthropic(
            model=model,
            api_key=s.anthropic_api_key,
            base_url=s.anthropic_base_url,
            max_retries=3,
            **common,
            **limiter,
        )

    async def run(self, agent: AgentName, pr: PRContext) -> AgentResult:
        model_name = self._settings.model_for(agent)
        graph = create_agent(
            model=self._model(agent),
            tools=build_tools(pr, self._settings.max_file_content_chars),
            system_prompt=load_prompt(agent),
            # Native structured output (output_config.format, or Converse outputConfig) rather
            # than a forced tool call: newer Claude models and models like Kimi reject one.
            response_format=ProviderStrategy(AgentOutput),
            name=f"{agent}_agent",
        )
        task = (
            f"Review pull request #{pr.pr_number} in {pr.repo} at commit {pr.head_sha}. "
            f"{len(pr.files)} files are in scope. Use the tools to read the changes."
        )
        state = await graph.ainvoke(
            {"messages": [{"role": "user", "content": task}]},
            # LangGraph's default (25 steps, about 12 model calls) is too few for a large PR.
            config={"recursion_limit": sys.maxsize},
        )

        ai_messages = [m for m in state["messages"] if isinstance(m, AIMessage)]
        usage = [m.usage_metadata for m in ai_messages if m.usage_metadata]
        tool_calls = [c["name"] for m in ai_messages for c in m.tool_calls]
        output = state.get("structured_response")
        error = None
        if output is None:
            error = "agent finished without a structured result"
        return AgentResult(
            agent=agent,
            model=model_name,
            output=output,
            input_tokens=sum(u["input_tokens"] for u in usage),
            output_tokens=sum(u["output_tokens"] for u in usage),
            error=error,
            tool_calls=tool_calls,
        )
