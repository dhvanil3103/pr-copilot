from functools import cached_property

from anthropic import AnthropicBedrockMantle, AsyncAnthropicBedrockMantle
from langchain_anthropic import ChatAnthropic


class ChatAnthropicBedrock(ChatAnthropic):
    """ChatAnthropic that calls Claude in Amazon Bedrock (the Messages API on bedrock-mantle).

    Only the transport changes, so tools and native structured output behave as on the
    Claude API. Credentials come from the AWS chain (env keys, profile, EKS Pod Identity)
    or AWS_BEARER_TOKEN_BEDROCK; none are stored here.
    """

    aws_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    # Overridable so tests can point at the mock Anthropic server.
    bedrock_base_url: str | None = None

    @property
    def _llm_type(self) -> str:
        # Anything but "anthropic-chat" makes LangChain send block-level cache_control,
        # the only form Bedrock accepts.
        return "anthropic-bedrock"

    def _bedrock_params(self) -> dict:
        params: dict = {
            "aws_region": self.aws_region,
            "aws_access_key": self.aws_access_key_id,
            "aws_secret_key": self.aws_secret_access_key,
            "aws_session_token": self.aws_session_token,
            "base_url": self.bedrock_base_url,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
        }
        if self.default_request_timeout is None or self.default_request_timeout > 0:
            params["timeout"] = self.default_request_timeout
        return params

    @cached_property
    def _client(self) -> AnthropicBedrockMantle:  # type: ignore[override]
        return AnthropicBedrockMantle(**self._bedrock_params())

    @cached_property
    def _async_client(self) -> AsyncAnthropicBedrockMantle:  # type: ignore[override]
        return AsyncAnthropicBedrockMantle(**self._bedrock_params())
