"""Preflight estimator: for a given experiment_id, reports exactly how many quests
are still to run (respecting the resume checkpoint) and how many input tokens that
would cost, WITHOUT spending anything -- token counts come from each provider's
free, non-billed count-tokens endpoint (exact for Claude/Gemini; a documented
approximation for OpenAI, which has no such endpoint). Output token cost is
estimated from this experiment's own historical average for the same
provider/model, when there is any; otherwise it's left unestimated rather than
guessed.

This can't tell you your remaining quota/balance -- no provider exposes that
through a plain API key, only through their account dashboard (for Gemini:
https://aistudio.google.com/rate-limit). What it gives you instead: a real count
of what the remaining run will actually cost, computed before you spend anything.

Run: python -m cognitive_rpg.experiment.preflight [experiment_id]
"""

import sys
from collections import defaultdict

from .. import config
from ..adapters import build_adapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt
from ..cheater import solution_bank
from ..domain.task_generator import generate_tasks
from ..librarian import librarian
from .experiment_log import read_all


def _avg_output_tokens(records: list[dict], provider: str, model: str) -> float | None:
    matches = [
        r["output_tokens"] for r in records
        if r.get("provider") == provider and r.get("model") == model
    ]
    return (sum(matches) / len(matches)) if matches else None


def estimate(experiment_id: str | None = None) -> dict:
    if experiment_id is None:
        experiment_id = config.get_current_experiment_id()
    tasks = generate_tasks(seed=42)
    records = read_all(experiment_id)
    already_done = {(r["task_id"], r["config_name"]) for r in records}

    expert_adapter = build_adapter("expert")
    small_adapter = build_adapter("small")
    plan = (
        ("A", expert_adapter, False),
        ("B", small_adapter, False),
        ("F", small_adapter, True),
    )

    # Keyed by (provider, model), not just provider -- Expert and Small can share
    # a provider (e.g. both "gemini") while running different models via a
    # role-specific override, and a provider-only key was silently merging their
    # calls/tokens into one bucket, displaying only whichever model's adapter
    # happened to run last for each task (see recap.md / conversation for how
    # this surfaced: expert=gemini-3-flash-preview, small=gemini-3.1-flash-lite
    # both real but only the small one was ever shown).
    per_provider = defaultdict(lambda: {
        "calls": 0, "input_tokens": 0, "output_tokens_est": 0.0,
        "output_tokens_is_estimate_missing": False, "model": None,
        "input_is_exact": True,
    })

    for task in tasks:
        for config_name, adapter, use_librarian in plan:
            if (task.task_id, config_name) in already_done:
                continue
            skill_package = librarian.route(task) if use_librarian else None
            prompt = build_prompt(task, skill_package)
            input_tokens = adapter.count_input_tokens(prompt, system=SYSTEM_PROMPT)

            model = getattr(adapter, "model", None) or getattr(adapter, "model_name", "?")
            bucket = per_provider[(adapter.PROVIDER, model)]
            bucket["calls"] += 1
            bucket["input_tokens"] += input_tokens
            bucket["model"] = model
            bucket["input_is_exact"] = adapter.PROVIDER in ("claude", "gemini", "mock")

            avg_out = _avg_output_tokens(records, adapter.PROVIDER, model)
            if avg_out is None:
                bucket["output_tokens_is_estimate_missing"] = True
            else:
                bucket["output_tokens_est"] += avg_out

    return {
        "experiment_id": experiment_id,
        "total_tasks": len(tasks),
        "already_done": len(already_done),
        "remaining_calls": sum(b["calls"] for b in per_provider.values()),
        "per_provider": dict(per_provider),
    }


def _print_report(report: dict) -> None:
    print(f"[preflight] experiment_id={report['experiment_id']}")
    print(f"[preflight] {report['already_done']} quest gia' fatte, {report['remaining_calls']} rimanenti\n")
    if not report["per_provider"]:
        print("[preflight] niente da fare -- tutte le quest sono gia' state completate.")
        return
    for (provider, _model), b in sorted(report["per_provider"].items()):
        exact = "esatto" if b["input_is_exact"] else "stima approssimata (~4 char/token, nessun endpoint di conteggio)"
        print(f"-- {provider} ({b['model']}) --")
        print(f"   chiamate rimanenti: {b['calls']}")
        print(f"   token di input ({exact}): {b['input_tokens']}")
        if b["output_tokens_is_estimate_missing"]:
            print("   token di output: nessun dato storico per questo provider/modello -- non stimato")
        else:
            print(f"   token di output (stima da media storica reale): ~{b['output_tokens_est']:.0f}")
            total = b["input_tokens"] + b["output_tokens_est"]
            print(f"   totale stimato: ~{total:.0f} token")
    print(
        "\n[preflight] questo NON e' il tuo saldo/quota residua -- quello si vede solo nella "
        "dashboard del provider (per Gemini: https://aistudio.google.com/rate-limit). "
        "Le quote giornaliere (RPD) di Gemini si resettano a mezzanotte Pacific Time."
    )


if __name__ == "__main__":
    exp_id = sys.argv[1] if len(sys.argv) > 1 else config.get_current_experiment_id()
    _print_report(estimate(exp_id))
