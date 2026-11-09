import logging
import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage

from shared.config import Settings
from shared.db import AgentName
from worker.agents.base import AgentResult, PRContext
from worker.agents.tools import build_tools
from worker.findings import AgentOutput

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
# Bump the file name (review_v2.md) when changing a prompt so evals can compare versions.
PROMPT_FILES = {AgentName.review: "review_v1.md", AgentName.test: "test_v1.md"}


def load_prompt(agent: AgentName) -> str:
    return (PROMPTS_DIR / PROMPT_FILES[agent]).read_text()


class LangChainAgentRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _model(self, agent: AgentName) -> ChatAnthropic:
        s = self._settings
        return ChatAnthropic(
            model=s.model_for(agent),
            api_key=s.anthropic_api_key,
            base_url=s.anthropic_base_url,
            max_tokens=s.agent_max_tokens,
            timeout=s.agent_timeout_seconds,
            max_retries=3,
        )

    async def run(self, agent: AgentName, pr: PRContext) -> AgentResult:
        model_name = self._settings.model_for(agent)
        graph = create_agent(
            model=self._model(agent),
            tools=build_tools(pr, self._settings.max_file_content_chars),
            system_prompt=load_prompt(agent),
            # Native structured output (output_config.format) rather than a forced
            # tool call, because newer Claude models reject forced tool_choice.
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
