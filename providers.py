"""Registry of AI providers a role (Expert or Small) can be assigned to. Adding a
new provider means: write an adapter in adapters/, add one entry here, done --
settings_wizard.py and adapters/factory.py both read from this list instead of
hardcoding provider names."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    api_key_env: str | None  # None for providers that need no key (mock)
    default_model: str
    model_env: str | None  # env var the wizard/factory use for a model override
    pricing_input_env: str | None
    pricing_output_env: str | None
    # Only set for providers authenticated via GCP project + service account
    # instead of a plain API key (e.g. gemini_vertex) -- None for everyone else.
    project_env: str | None = None
    location_env: str | None = None
    credentials_env: str | None = None


PROVIDERS: dict[str, Provider] = {
    "claude": Provider(
        key="claude",
        label="Claude (Anthropic)",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-opus-5",
        model_env="CLAUDE_MODEL",
        pricing_input_env=None,  # priced via config.CLAUDE_PRICING_PER_MTOK, keyed by model
        pricing_output_env=None,
    ),
    "gemini": Provider(
        key="gemini",
        label="Gemini (Google)",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-2.5-flash",
        model_env="GEMINI_MODEL",
        pricing_input_env="GEMINI_INPUT_PER_MTOK",
        pricing_output_env="GEMINI_OUTPUT_PER_MTOK",
    ),
    "gemini_vertex": Provider(
        key="gemini_vertex",
        label="Gemini via Vertex AI / Agent Platform (usa i crediti GCP invece della key AI Studio)",
        api_key_env=None,
        default_model="gemini-2.5-flash",
        model_env="GEMINI_VERTEX_MODEL",
        pricing_input_env="GEMINI_INPUT_PER_MTOK",  # same models/prices as the AI Studio path
        pricing_output_env="GEMINI_OUTPUT_PER_MTOK",
        project_env="GOOGLE_CLOUD_PROJECT",
        location_env="GOOGLE_CLOUD_LOCATION",
        credentials_env="GOOGLE_APPLICATION_CREDENTIALS",
    ),
    "openai": Provider(
        key="openai",
        label="ChatGPT (OpenAI)",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4.1",
        model_env="OPENAI_MODEL",
        pricing_input_env="OPENAI_INPUT_PER_MTOK",
        pricing_output_env="OPENAI_OUTPUT_PER_MTOK",
    ),
    "mock": Provider(
        key="mock",
        label="Mock (nessuna chiamata reale, costo $0, per test)",
        api_key_env=None,
        default_model="mock-model",
        model_env=None,
        pricing_input_env=None,
        pricing_output_env=None,
    ),
}

PROVIDER_ORDER = ["claude", "gemini", "gemini_vertex", "openai", "mock"]
