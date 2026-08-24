import time

from google import genai
from google.genai import errors as genai_errors

from .. import config
from .base import ModelAdapter, CompletionResult, QuotaExhaustedError

_DEFAULT_RETRY_SECONDS = 60.0
_MAX_RETRY_SECONDS = 300.0
# A 429 with RetryInfo longer than this reads as a real quota wall (daily/hourly
# limit) rather than a short per-minute one -- worth stopping for instead of
# silently blocking for a long stretch.
_HARD_WALL_SECONDS = 120.0

_RETRYABLE_CODES = {429, 500, 503, 504}


def _retry_delay_seconds(error: genai_errors.APIError) -> float:
    """Reads the RetryInfo.retryDelay Google sends with 429 quota errors (e.g.
    '57s'); falls back to a flat default if the shape isn't there (this is the
    normal case for 5xx overload errors, which carry no RetryInfo)."""
    try:
        for detail in error.details["error"]["details"]:
            if detail.get("@type", "").endswith("RetryInfo"):
                return float(detail["retryDelay"].rstrip("s"))
    except (KeyError, TypeError, ValueError):
        pass
    return _DEFAULT_RETRY_SECONDS


class GeminiAdapter(ModelAdapter):
    """Uses the `google-genai` SDK (`genai.Client(...)`,
    `client.models.generate_content(...)`) -- this is NOT covered by any skill loaded
    in this session, so verify the SDK surface and the model id against Google's
    current docs before relying on this, and fill in GEMINI_*_PER_MTOK in .env
    yourself (see .env.example) -- there is no built-in pricing table here."""

    PROVIDER = "gemini"

    def __init__(self, model: str):
        self.model = model
        self._keys = config.GEMINI_API_KEYS or [None]
        self._clients = [genai.Client(api_key=k) for k in self._keys]
        # Round-robin cursor, shared across every complete()/count_input_tokens()
        # call on this adapter instance -- so with N keys configured, each key
        # only sees roughly 1/N of the calls, spreading load to stay under a
        # single key's per-minute limit instead of hammering key #0 until it
        # throttles (changed 2026-08-18, at the user's request: "1 call, 1 call
        # su ogni api, cosi' possiamo usarne 1 al minuto per key").
        self._next_index = 0
        self._exhausted: set[int] = set()  # indices that hit a real (hard-wall) quota exhaustion

    def _pick_client_index(self) -> int | None:
        """Next non-exhausted key in round-robin order. None if every
        configured key has hit a hard quota wall."""
        n = len(self._clients)
        for _ in range(n):
            idx = self._next_index
            self._next_index = (self._next_index + 1) % n
            if idx not in self._exhausted:
                return idx
        return None

    def count_input_tokens(self, prompt: str, system: str | None = None) -> int:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        idx = self._pick_client_index()
        client = self._clients[idx] if idx is not None else self._clients[0]
        result = client.models.count_tokens(model=self.model, contents=full_prompt)
        return result.total_tokens

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> CompletionResult:
        start = time.monotonic()
        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        attempt = 0
        paused_seconds = 0.0
        idx = self._pick_client_index()
        if idx is None:
            raise QuotaExhaustedError(
                retry_after_seconds=_DEFAULT_RETRY_SECONDS,
                message=f"quota Gemini esaurita per {self.model} su tutte le {len(self._clients)} key configurate",
            )
        # Keys already tried in the CURRENT round (since the last real wait).
        # Bounded: once every available key has failed once this round, fall
        # through to a real sleep instead of cycling keys forever -- with
        # round-robin, _pick_client_index() almost always returns "some other"
        # index when there's more than one key, so without this bound a
        # simultaneous 429 on all keys spun in a tight loop with no backoff
        # at all (found in practice 2026-08-18: experiment2 stalled at 18/78
        # while all 3 keys were hitting 429 on gemini-3.7-flash together).
        tried_this_round = {idx}
        while True:
            try:
                response = self._clients[idx].models.generate_content(
                    model=self.model,
                    contents=full_prompt,
                    config={"max_output_tokens": max_tokens},
                )
                break
            except genai_errors.APIError as e:
                # Transient (quota/overload) errors don't give up -- this is an
                # offline batch experiment, so pausing and retrying beats crashing
                # the whole run. Anything else (auth, bad request, ...) is a real
                # error and raises immediately.
                if e.code not in _RETRYABLE_CODES:
                    raise
                delay_hint = _retry_delay_seconds(e)
                if e.code == 429 and delay_hint > _HARD_WALL_SECONDS:
                    # A real quota wall on this key (daily/hourly), not a short
                    # per-minute one -- this key is done for the rest of the
                    # process, don't route any more calls to it.
                    self._exhausted.add(idx)

                # Try a DIFFERENT key not yet tried THIS round before sleeping
                # -- another key very likely has spare per-minute budget right
                # now, sleeping would waste it. Only once every available key
                # has already failed once this round do we fall through to a
                # real wait (below), not "try yet another key" again.
                other_idx = self._pick_client_index()
                if other_idx is not None and other_idx not in tried_this_round:
                    print(
                        f"  [gemini] errore {e.code} su key #{idx + 1}/{len(self._clients)} per "
                        f"{self.model}, provo key #{other_idx + 1}/{len(self._clients)} senza aspettare"
                    )
                    idx = other_idx
                    tried_this_round.add(idx)
                    continue
                if other_idx is None:
                    raise QuotaExhaustedError(
                        retry_after_seconds=delay_hint,
                        message=(
                            f"quota Gemini esaurita per {self.model} su tutte le "
                            f"{len(self._clients)} key configurate, riprova tra {delay_hint:.0f}s"
                        ),
                    ) from e

                attempt += 1
                delay = min(delay_hint * attempt, _MAX_RETRY_SECONDS)
                reason = "quota esaurita" if e.code == 429 else f"errore {e.code} (server)"
                print(
                    f"  [gemini] {reason} per {self.model} (tentate tutte le {len(tried_this_round)} key disponibili), "
                    f"pausa {delay:.0f}s poi riprovo (tentativo {attempt})"
                )
                time.sleep(delay)
                paused_seconds += delay
                tried_this_round = {idx}

        # Retry pauses are dead time waiting out an overloaded/quota-limited server,
        # not the model actually "being slow" -- exclude them from latency and
        # surface them separately (paused_seconds/retries below) instead.
        latency_ms = (time.monotonic() - start - paused_seconds) * 1000

        text = response.text or ""
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        cached_input_tokens = getattr(usage, "cached_content_token_count", 0) or 0
        reasoning_output_tokens = getattr(usage, "thoughts_token_count", None)

        if config.GEMINI_INPUT_PER_MTOK is None or config.GEMINI_OUTPUT_PER_MTOK is None:
            cost_usd = 0.0
        else:
            cost_usd = (
                input_tokens * config.GEMINI_INPUT_PER_MTOK
                + output_tokens * config.GEMINI_OUTPUT_PER_MTOK
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
            retries=attempt,
            paused_seconds=paused_seconds,
        )


class GeminiVertexAdapter(GeminiAdapter):
    """Same retry/round-robin logic as GeminiAdapter, but authenticates through a
    GCP project + service account (Vertex AI / "Agent Platform") instead of a
    plain AI Studio API key -- so usage draws on Cloud billing credits, which AI
    Studio API keys are excluded from as of March 2026 (see config.GOOGLE_CLOUD_*).
    Auth itself is handled entirely by google-auth reading GOOGLE_APPLICATION_
    CREDENTIALS from the environment; no key material is ever read by this code.
    Only one client: Vertex quota is per-project, not per-key, so the multi-key
    rotation the base class does for free-tier AI Studio keys doesn't apply here."""

    PROVIDER = "gemini_vertex"

    def __init__(self, model: str):
        self.model = model
        self._keys = [None]
        self._clients = [
            genai.Client(
                vertexai=True,
                project=config.GOOGLE_CLOUD_PROJECT,
                location=config.GOOGLE_CLOUD_LOCATION,
            )
        ]
        self._next_index = 0
        self._exhausted: set[int] = set()
