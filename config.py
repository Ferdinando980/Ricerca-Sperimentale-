import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH)

# Which provider each role is assigned to. Defaults to "mock" for both roles so the
# project runs with zero API keys configured -- run the settings wizard
# (python -m cognitive_rpg.settings_wizard) to assign real providers instead of
# editing this file or .env by hand.
EXPERT_PROVIDER = os.getenv("EXPERT_PROVIDER", "mock")
SMALL_PROVIDER = os.getenv("SMALL_PROVIDER", "mock")

def _keys(plural_env: str, singular_env: str) -> list[str]:
    """Reads {PROVIDER}_API_KEYS (comma-separated) if set -- lets a provider rotate
    across multiple keys (e.g. two free-tier accounts) instead of stopping at one
    key's quota wall. Falls back to the older single-key {PROVIDER}_API_KEY."""
    raw = os.getenv(plural_env, "")
    if raw.strip():
        return [k.strip() for k in raw.split(",") if k.strip()]
    single = os.getenv(singular_env, "")
    return [single] if single else []


ANTHROPIC_API_KEYS = _keys("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY")
GEMINI_API_KEYS = _keys("GEMINI_API_KEYS", "GEMINI_API_KEY")
OPENAI_API_KEYS = _keys("OPENAI_API_KEYS", "OPENAI_API_KEY")

# Back-compat single-key accessors -- some call sites only ever need "a" key.
ANTHROPIC_API_KEY = ANTHROPIC_API_KEYS[0] if ANTHROPIC_API_KEYS else ""
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
OPENAI_API_KEY = OPENAI_API_KEYS[0] if OPENAI_API_KEYS else ""

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")
GEMINI_VERTEX_MODEL = os.getenv("GEMINI_VERTEX_MODEL", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")

# gemini_vertex auth: project + region, both required; the service account key
# itself is never read here -- GOOGLE_APPLICATION_CREDENTIALS (set in .env like
# any other var here) is picked up straight from the process environment by
# google-auth's default credential lookup, so it never needs to pass through
# this codebase or through a chat with an assistant.
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")

# LIBRARY_DIR is one shared folder, never scoped to an experiment_id -- every
# experiment reads/writes the same live library. LIBRARY_DIR_OVERRIDE lets a
# run point at a frozen snapshot instead (see library/snapshot.py), so a
# "library before vs after the optimizer" comparison isn't confused by the
# live library having kept evolving in between.
_library_dir_override = os.getenv("LIBRARY_DIR_OVERRIDE", "").strip()
LIBRARY_DIR = (
    Path(_library_dir_override) if _library_dir_override
    else Path(__file__).resolve().parent / "library" / "books"
)
# Sibling of LIBRARY_DIR, not a subfolder of it -- load_books() globs LIBRARY_DIR
# non-recursively, but keeping this out of "books/" entirely means a rejected
# compression can never accidentally get picked up as a routable Book.
COMPRESSION_FAILURES_DIR = Path(__file__).resolve().parent / "library" / "compression_failures"
# Sibling of LIBRARY_DIR too. Confirmed-duplicate Book files get moved here
# instead of deleted (2026-08-18): historical events.jsonl entries reference
# these ids for cost attribution (metrics.skill_amortization), so physically
# deleting one silently drops its build_cost from every future report --
# discovered when book_floating_point_equality_v2's removal dropped that
# pattern's build_cost from 18572 to 12477 tokens with no visible warning.
# load_books() never reads this directory -- routing/_latest_per_pattern is
# unaffected, only historical id->pattern_id lookups consult it.
ARCHIVED_BOOKS_DIR = Path(__file__).resolve().parent / "library" / "archived_books"
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

_CURRENT_EXPERIMENT_FILE = LOG_DIR / ".current_experiment"


def get_current_experiment_id(default: str = "experiment0") -> str:
    """Whatever experiment_id a tool last ran with, so double-clicking a .bat in
    tools\\ (which passes no CLI argument) continues the experiment actually in
    progress instead of always landing back on the literal string "experiment0"
    (found 2026-08-18: real progress had piled up in experiment2 while every
    double-click kept starting/resuming experiment0 instead)."""
    if _CURRENT_EXPERIMENT_FILE.exists():
        stored = _CURRENT_EXPERIMENT_FILE.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    return default


def set_current_experiment_id(experiment_id: str) -> None:
    _CURRENT_EXPERIMENT_FILE.write_text(experiment_id, encoding="utf-8")


def experiment_dir(experiment_id: str) -> Path:
    """Each experiment gets its own folder under logs/ (log.jsonl, events.jsonl,
    city.html) instead of flat files sharing the logs/ directory."""
    path = LOG_DIR / experiment_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _price(env_name: str) -> float | None:
    raw = os.getenv(env_name, "")
    return float(raw) if raw else None


# Pricing per model, USD per 1,000,000 tokens -- from the claude-api skill (cached
# 2026-06-24). Re-check before trusting this for anything beyond rough cost tracking.
CLAUDE_PRICING_PER_MTOK = {
    "claude-opus-5": (
        _price("CLAUDE_OPUS_5_INPUT_PER_MTOK") or 5.00,
        _price("CLAUDE_OPUS_5_OUTPUT_PER_MTOK") or 25.00,
    ),
    "claude-sonnet-5": (
        _price("CLAUDE_SONNET_5_INPUT_PER_MTOK") or 3.00,
        _price("CLAUDE_SONNET_5_OUTPUT_PER_MTOK") or 15.00,
    ),
    "claude-haiku-4-5": (
        _price("CLAUDE_HAIKU_4_5_INPUT_PER_MTOK") or 1.00,
        _price("CLAUDE_HAIKU_4_5_OUTPUT_PER_MTOK") or 5.00,
    ),
}

# No verified default for Gemini/OpenAI pricing -- neither is covered by a skill in
# this project, so these stay unset (cost tracked as $0) until filled in via the
# settings wizard or .env directly.
GEMINI_INPUT_PER_MTOK = _price("GEMINI_INPUT_PER_MTOK")
GEMINI_OUTPUT_PER_MTOK = _price("GEMINI_OUTPUT_PER_MTOK")
OPENAI_INPUT_PER_MTOK = _price("OPENAI_INPUT_PER_MTOK")
OPENAI_OUTPUT_PER_MTOK = _price("OPENAI_OUTPUT_PER_MTOK")
