import time

from openai import APIConnectionError, OpenAI

from .. import config
from .base import CompletionResult, ModelAdapter


class GemmaAdapter(ModelAdapter):
    """Local Gemma via llama-server's OpenAI-compatible endpoint (llama.cpp,
    installed via WinGet as ggml.llamacpp -- NOT Ollama, which is not
    installed on this machine). Reuses the exact server invocation already
    proven working for the Archivist benchmark (2026-09-15,
    Ai/start-gemma-benchmark.ps1, results in Ai/archivist-evaluation-gemma.json):
    llama-server bound to 127.0.0.1:8080, --jinja with a Gemma-specific chat
    template, reasoning off, temp 0.2 / top_p 0.9 / top_k 40 / min_p 0.05 /
    repeat_penalty 1.05, stop tokens for Gemma's <end_of_turn>/<eos> turn
    markers (all four stop strings are sent regardless of template, same as
    the proven script -- llama-server ignores the ones the active template
    doesn't use).

    Zero cost, no API key, no network beyond localhost. The caller MUST start
    the server first (Ai/start-gemma-benchmark.ps1 or an equivalent
    llama-server invocation) -- this adapter only calls it, it never launches
    the process itself."""

    PROVIDER = "gemma"

    _STOP_TOKENS = ["<end_of_turn>", "<eos>", "<|im_end|>", "<|endoftext|>"]

    def __init__(self, model: str):
        self.model = model
        # llama-server ignores the key entirely; the OpenAI SDK still
        # requires a non-empty string to construct the client.
        self.client = OpenAI(api_key="local-llama-server-no-key-needed", base_url=config.GEMMA_BASE_URL)

    def count_input_tokens(self, prompt: str, system: str | None = None) -> int:
        # llama-server exposes no token-count endpoint (same limitation as
        # OpenAIAdapter) -- ~4-chars-per-token heuristic, order-of-magnitude
        # only, never a hard budget gate.
        text = f"{system}\n\n{prompt}" if system else prompt
        return max(1, len(text) // 4)

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        thinking_budget: int | None = None,
    ) -> CompletionResult:
        # thinking_budget: no matching llama-server parameter -- the local
        # server is already started with --reasoning off at the process
        # level (config.py), so there is nothing to toggle per-call. Accepted
        # and ignored, same as every other adapter without a real knob (see
        # adapters/base.py's docstring).
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        start = time.monotonic()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,
                top_p=0.9,
                stop=self._STOP_TOKENS,
                extra_body={"top_k": 40, "min_p": 0.05, "repeat_penalty": 1.05},
            )
        except APIConnectionError as e:
            raise RuntimeError(
                f"Impossibile raggiungere il server Gemma locale su {config.GEMMA_BASE_URL} -- "
                "avvialo prima con Ai/start-gemma-benchmark.ps1 (o un llama-server equivalente "
                "sullo stesso host/porta)."
            ) from e
        latency_ms = (time.monotonic() - start) * 1000

        text = response.choices[0].message.content or ""
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        return CompletionResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=0.0,  # hardware locale, nessun costo per token
            latency_ms=latency_ms,
            model=self.model,
            provider=self.PROVIDER,
        )
