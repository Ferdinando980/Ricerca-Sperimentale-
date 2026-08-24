from abc import ABC, abstractmethod
from dataclasses import dataclass


class QuotaExhaustedError(RuntimeError):
    """Raised instead of retrying when a provider's rate-limit error signals a real
    wall (e.g. a daily quota, reset hours away) rather than a short per-minute
    limit -- so a caller can stop cleanly and report when to come back instead of
    blocking indefinitely."""

    def __init__(self, retry_after_seconds: float, message: str):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass
class CompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float  # actual request time only -- excludes any retry/backoff pause below
    model: str
    provider: str
    cached_input_tokens: int = 0
    reasoning_output_tokens: int | None = None  # None where the provider doesn't expose it
    retries: int = 0
    paused_seconds: float = 0.0  # time spent sleeping between retries, tracked separately from latency


class ModelAdapter(ABC):
    """Every component that calls a model goes through this interface -- Librarian,
    Worker, Checker, Global Verifier alike -- so cost/latency accounting never misses
    a call and any component can be re-pointed at a different provider."""

    PROVIDER: str

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> CompletionResult:
        raise NotImplementedError

    @abstractmethod
    def count_input_tokens(self, prompt: str, system: str | None = None) -> int:
        """Token count for a would-be request -- no completion call, no cost. Used
        by the preflight estimator so it can report real numbers before spending
        anything. Exact where the provider exposes a token-counting endpoint
        (Claude, Gemini); approximate otherwise (OpenAI has none)."""
        raise NotImplementedError
