"""AnthropicConverseBackend — realtime direct Anthropic Messages API.

Drop-in replacement for ConverseBackend that uses the direct Anthropic API
instead of Bedrock. Subclasses ConverseBackend and overrides only __init__
to swap the instructor client; _execute_one, run, thread pool, and
on_result streaming are all inherited unchanged.
"""

import anthropic
import instructor
from library_layer.config import SteamPulseConfig
from library_layer.llm.converse import ConverseBackend


class AnthropicConverseBackend(ConverseBackend):
    """Instructor + direct Anthropic API behind the LLMBackend protocol.

    Identical to ConverseBackend except the underlying HTTP client targets
    api.anthropic.com instead of Bedrock. Model IDs use the Anthropic
    format (e.g. ``claude-sonnet-4-6`` without the ``us.anthropic.`` prefix).
    """

    def __init__(
        self,
        config: SteamPulseConfig,
        *,
        max_workers: int,
        max_retries: int,
        api_key: str,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for AnthropicConverseBackend")
        super().__init__(config, max_workers=max_workers, max_retries=max_retries)
        self._client = instructor.from_anthropic(
            anthropic.Anthropic(api_key=api_key)
        )
