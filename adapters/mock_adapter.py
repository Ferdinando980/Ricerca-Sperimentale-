import time

from .base import ModelAdapter, CompletionResult


class MockAdapter(ModelAdapter):
    """No network calls, zero cost. Used to validate the pipeline/schema (task
    generation -> librarian -> worker -> verifier -> log) before spending on real
    calls, and as the default so the project runs with no API keys configured."""

    PROVIDER = "mock"

    def __init__(self, model_name: str = "mock-model", canned_response: str | None = None):
        self.model_name = model_name
        self.canned_response = canned_response

    def count_input_tokens(self, prompt: str, system: str | None = None) -> int:
        return len(prompt.split())

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        thinking_budget: int | None = None,
    ) -> CompletionResult:
        # thinking_budget: no real call happens here, nothing to configure.
        # Accepted and ignored for interface compatibility (see adapters/
        # base.py's docstring).
        start = time.monotonic()
        text = self.canned_response if self.canned_response is not None else "# mock: no fix applied\n"
        latency_ms = (time.monotonic() - start) * 1000
        return CompletionResult(
            text=text,
            input_tokens=len(prompt.split()),
            output_tokens=len(text.split()),
            cost_usd=0.0,
            latency_ms=latency_ms,
            model=self.model_name,
            provider=self.PROVIDER,
        )
