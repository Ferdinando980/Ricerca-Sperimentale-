import time

from openai import OpenAI

from .. import config
from .base import ModelAdapter, CompletionResult


class OpenAIAdapter(ModelAdapter):
    """Uses the `openai` Python SDK's Chat Completions endpoint
    (`client.chat.completions.create(...)`) -- this is NOT covered by any skill
    loaded in this session, so verify the model id and current pricing yourself
    before relying on this. Fill in OPENAI_*_PER_MTOK in .env (see .env.example) --
    there is no built-in pricing table here, cost is tracked as $0 until you do."""

    PROVIDER = "openai"

    def __init__(self, model: str):
        self.model = model
        self.client = OpenAI(api_key=config.OPENAI_API_KEY or None)

    def count_input_tokens(self, prompt: str, system: str | None = None) -> int:
        # The OpenAI API has no token-counting endpoint (unlike Claude/Gemini) --
        # this is a ~4-chars-per-token heuristic, not exact. Fine for an
        # order-of-magnitude preflight number, not for a hard budget gate.
        text = f"{system}\n\n{prompt}" if system else prompt
        return max(1, len(text) // 4)

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> CompletionResult:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        start = time.monotonic()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
        )
        latency_ms = (time.monotonic() - start) * 1000

        text = response.choices[0].message.content or ""
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        cached_input_tokens = 0
        reasoning_output_tokens = None
        if response.usage:
            if response.usage.prompt_tokens_details:
                cached_input_tokens = response.usage.prompt_tokens_details.cached_tokens or 0
            if response.usage.completion_tokens_details:
                reasoning_output_tokens = response.usage.completion_tokens_details.reasoning_tokens

        if config.OPENAI_INPUT_PER_MTOK is None or config.OPENAI_OUTPUT_PER_MTOK is None:
            cost_usd = 0.0
        else:
            cost_usd = (
                input_tokens * config.OPENAI_INPUT_PER_MTOK
                + output_tokens * config.OPENAI_OUTPUT_PER_MTOK
            ) / 1_000_000

        return CompletionResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            model=self.model,
            provider=self.PROVIDER,
            cached_input_tokens=cached_input_tokens,
            reasoning_output_tokens=reasoning_output_tokens,
        )
