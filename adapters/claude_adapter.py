import time

import anthropic

from .. import config
from .base import ModelAdapter, CompletionResult


class ClaudeAdapter(ModelAdapter):
    PROVIDER = "claude"

    def __init__(self, model: str):
        self.model = model
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)

    def count_input_tokens(self, prompt: str, system: str | None = None) -> int:
        result = self.client.messages.count_tokens(
            model=self.model,
            system=system or anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": prompt}],
        )
        return result.input_tokens

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> CompletionResult:
        start = time.monotonic()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system or anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = (time.monotonic() - start) * 1000

        text = "".join(block.text for block in response.content if block.type == "text")
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        # cache_read (served from cache, cheap) vs cache_creation (written this call,
        # billed higher) -- cached_input_tokens tracks reads, since that's the
        # observable "this call benefited from caching" number. Neither is used by
        # cost_usd below: this adapter sends no cache_control, so both are normally 0.
        cached_input_tokens = response.usage.cache_read_input_tokens or 0

        price_in, price_out = config.CLAUDE_PRICING_PER_MTOK.get(self.model, (0.0, 0.0))
        cost_usd = (input_tokens * price_in + output_tokens * price_out) / 1_000_000

        return CompletionResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            model=self.model,
            provider=self.PROVIDER,
            cached_input_tokens=cached_input_tokens,
            reasoning_output_tokens=None,  # Claude doesn't expose this; extended thinking isn't used here
        )
