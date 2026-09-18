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
        thinking_budget: int | None = None,
    ) -> CompletionResult:
        """thinking_budget: None (default) leaves a reasoning-capable model's
        extended thinking dynamic/unbounded, as before -- unchanged behavior
        for every existing caller. A caller that ONLY needs a fixed-shape
        classification (a JSON verdict, not open-ended problem solving) can
        pass a small value (e.g. 0) to make the answer-token budget
        deterministic instead of variable-per-topic.

        Real bug this fixes (2026-09-18): identify_slot_decomposed's classify
        step asked gemini-3.6-flash to classify the literal 'None' -- and the
        model spent enough invisible reasoning tokens on that one specific
        candidate (not on '[]', not on other literals) to blow through
        max_tokens=1024 before writing the JSON verdict, 5/5 repeated runs.
        The early-return-on-first-match loop in identify_slot_decomposed then
        silently fell through to the NEXT candidate, so the bug looked like
        "the model disagrees on which slot is real" when it was actually a
        token-budget truncation on ONE specific candidate, invisible without
        isolating extract vs. classify (see verification/slot_identifier.py's
        own comment on _CLASSIFY_LITERAL_SYSTEM_PROMPT call sites). Providers
        without an equivalent knob (Claude's extended thinking is a different
        API shape not used here; OpenAI/Gemma have no matching parameter;
        Gemma's local server already runs with --reasoning off at the process
        level) accept and ignore this argument rather than erroring, so every
        call site can pass it uniformly regardless of which adapter is
        configured for a role."""
        raise NotImplementedError

    @abstractmethod
    def count_input_tokens(self, prompt: str, system: str | None = None) -> int:
        """Token count for a would-be request -- no completion call, no cost. Used
        by the preflight estimator so it can report real numbers before spending
        anything. Exact where the provider exposes a token-counting endpoint
        (Claude, Gemini); approximate otherwise (OpenAI has none)."""
        raise NotImplementedError
