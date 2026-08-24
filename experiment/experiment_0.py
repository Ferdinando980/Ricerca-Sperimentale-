"""Experiment 0 (design review §K): compares
  A = Expert alone (Claude, no Librarian)
  B = Small alone (Gemini, no Librarian)
  F = Small + Librarian (Gemini + hand-written Books)
  C = Small + Cheater (Gemini + a past solution from cheater/solution_bank.py,
      added 2026-08-18 -- base implementation, see the Cheater Agent plan in
      conversation: how much of F's advantage over B is real generalizable
      competence vs. having effectively "seen the answer" before)
over the seed task set, and reports accuracy per split plus cost/latency per config.

Run: python -m cognitive_rpg.experiment.experiment_0
Provider/model per role is controlled by EXPERT_PROVIDER / SMALL_PROVIDER in .env --
run `python -m cognitive_rpg.settings_wizard` to set them interactively.
"""

import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .. import config
from ..adapters import build_adapter
from ..adapters.base import QuotaExhaustedError
from ..city.report import generate as generate_city_report
from ..domain.task_generator import generate_tasks
from .experiment_log import archive, read_all
from .quest_runner import run_quest


def main():
    # --fresh archives any existing log for this id (renamed, not deleted) and
    # starts clean. Without it, the run always resumes -- the checkpoint lives in
    # the log file on disk, so this works even after closing everything and coming
    # back later (e.g. once a quota resets), not just within one process.
    args = [a for a in sys.argv[1:] if a != "--fresh"]
    fresh = len(args) != len(sys.argv) - 1
    experiment_id = args[0] if args else config.get_current_experiment_id()
    config.set_current_experiment_id(experiment_id)

    if fresh:
        archive(experiment_id)

    expert_adapter = build_adapter("expert")
    small_adapter = build_adapter("small")

    tasks = generate_tasks(seed=42)
    already_done = {(r["task_id"], r["config_name"]) for r in read_all(experiment_id)}
    print(
        f"[experiment_0] {len(tasks)} tasks, expert={config.EXPERT_PROVIDER}, "
        f"small={config.SMALL_PROVIDER}, experiment_id={experiment_id}"
        + (f", resuming ({len(already_done)} quests already logged)" if already_done else "")
    )

    total_calls = len(tasks) * 4
    done = len(already_done)
    stopped_early = False
    for task in tasks:
        if stopped_early:
            break
        for config_name, adapter, use_librarian, use_cheater in (
            ("A", expert_adapter, False, False),
            ("B", small_adapter, False, False),
            ("F", small_adapter, True, False),
            ("C", small_adapter, False, True),  # Cheater: Small + Solution Bank
        ):
            if (task.task_id, config_name) in already_done:
                continue
            try:
                run_quest(task, experiment_id, config_name, adapter, use_librarian=use_librarian, use_cheater=use_cheater)
            except QuotaExhaustedError as e:
                retry_at = datetime.now(timezone.utc).astimezone() + timedelta(seconds=e.retry_after_seconds)
                print(
                    f"\n[experiment_0] {e} -- fermato dopo {done}/{total_calls} quest "
                    f"(tutto il reale fatto finora e' salvato). Riprova non prima delle "
                    f"{retry_at:%H:%M %Z}. Rilancia lo stesso comando per riprendere da qui.",
                    file=sys.stderr,
                )
                stopped_early = True
                break
            done += 1
            print(f"[experiment_0] {done}/{total_calls} quests run ({task.task_id})", file=sys.stderr)

    summarize(experiment_id)

    city_path = generate_city_report(experiment_id)
    print(f"[experiment_0] Cognitive City aggiornata: {city_path}")

    if stopped_early:
        sys.exit(2)


def summarize(experiment_id: str):
    records = read_all(experiment_id)
    by_config_split = defaultdict(lambda: {"n": 0, "passed": 0, "cost": 0.0, "latency": 0.0})

    for r in records:
        key = (r["config_name"], r["split"])
        bucket = by_config_split[key]
        bucket["n"] += 1
        bucket["passed"] += int(r["passed"])
        bucket["cost"] += r["cost_usd"]
        bucket["latency"] += r["latency_ms"]

    print("\n=== Experiment 0 summary ===")
    print(f"{'config':<8}{'split':<10}{'n':>4}{'accuracy':>10}{'total_cost':>12}{'avg_latency_ms':>16}")
    for (cfg, split), bucket in sorted(by_config_split.items()):
        acc = bucket["passed"] / bucket["n"] if bucket["n"] else 0.0
        avg_latency = bucket["latency"] / bucket["n"] if bucket["n"] else 0.0
        print(f"{cfg:<8}{split:<10}{bucket['n']:>4}{acc:>10.2%}{bucket['cost']:>12.4f}{avg_latency:>16.1f}")

    for cfg in ("A", "B", "F", "C"):
        cfg_records = [r for r in records if r["config_name"] == cfg]
        if not cfg_records:
            continue
        n = len(cfg_records)
        acc = sum(int(r["passed"]) for r in cfg_records) / n
        cost = sum(r["cost_usd"] for r in cfg_records)
        print(f"\n{cfg} overall: accuracy={acc:.2%} total_cost=${cost:.4f} n={n}")


if __name__ == "__main__":
    main()
