import os

from .. import config
from ..providers import PROVIDERS
from .base import ModelAdapter
from .claude_adapter import ClaudeAdapter
from .gemini_adapter import GeminiAdapter, GeminiVertexAdapter
from .mock_adapter import MockAdapter
from .openai_adapter import OpenAIAdapter

_ADAPTER_CLASSES = {
    "claude": ClaudeAdapter,
    "gemini": GeminiAdapter,
    "gemini_vertex": GeminiVertexAdapter,
    "openai": OpenAIAdapter,
}


def build_adapter(role: str) -> ModelAdapter:
    """role is 'expert' or 'small'. Reads EXPERT_PROVIDER/SMALL_PROVIDER (and the
    matching *_MODEL override) from config -- set via the settings wizard
    (python -m cognitive_rpg.settings_wizard) or by hand in .env."""
    if role not in ("expert", "small"):
        raise ValueError(f"unknown role: {role!r} (expected 'expert' or 'small')")

    provider_key = config.EXPERT_PROVIDER if role == "expert" else config.SMALL_PROVIDER
    if provider_key not in PROVIDERS:
        raise ValueError(f"unknown provider {provider_key!r} for role {role!r}")

    if provider_key == "mock":
        return MockAdapter(model_name=f"mock-{role}")

    provider = PROVIDERS[provider_key]
    # Role-specific override (e.g. EXPERT_GEMINI_MODEL) wins -- needed when both roles
    # share the same provider but should run different models. Falls back to the
    # provider-wide override (e.g. GEMINI_MODEL), then the provider default.
    role_model_env = f"{role.upper()}_{provider.model_env}" if provider.model_env else None
    role_override = os.getenv(role_model_env, "") if role_model_env else ""
    model_override = role_override or getattr(config, f"{provider_key.upper()}_MODEL", "")
    model = model_override or provider.default_model

    adapter_cls = _ADAPTER_CLASSES[provider_key]
    return adapter_cls(model=model)
