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

import os
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from .. import config
from ..adapters import build_adapter
from ..adapters.base import QuotaExhaustedError
from ..city.report import generate as generate_city_report
from ..domain.task_generator import generate_tasks
from .experiment_log import archive, copy_config_records, read_all
from .quest_runner import run_quest


def _report_quota_stop(e: QuotaExhaustedError, done: int, total_calls: int) -> bool:
    retry_at = datetime.now(timezone.utc).astimezone() + timedelta(seconds=e.retry_after_seconds)
    print(
        f"\n[experiment_0] {e} -- fermato dopo {done}/{total_calls} quest "
        f"(tutto il reale fatto finora e' salvato). Riprova non prima delle "
        f"{retry_at:%H:%M %Z}. Rilancia lo stesso comando per riprendere da qui.",
        file=sys.stderr,
    )
    return True


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

    # REUSE_CONFIGS_FROM/REUSE_CONFIGS (opt-in, both unset by default = no
    # reuse, unchanged behavior) -- 2026-09-18, user-requested: when a new
    # experiment only changes ONE config (e.g. adding "FD" to test the
    # Detective annotation), the configs that DON'T depend on what changed
    # (typically A, and B/C too if only the Librarian-side annotation
    # varies) don't need to be re-run for real quota -- their result on an
    # unchanged task catalog is the same fact, not a new measurement.
    # Explicit and per-config on purpose: this never guesses which configs
    # are safe to reuse, the caller states it, because that's a judgment
    # about what actually changed that only the caller can make correctly
    # ("se ci sono cambiamenti che richiedono di rifarle e' un altro conto").
    reuse_from = os.getenv("REUSE_CONFIGS_FROM", "").strip()
    reuse_configs = [c.strip() for c in os.getenv("REUSE_CONFIGS", "").split(",") if c.strip()]
    if reuse_from and reuse_configs:
        for cfg_name in reuse_configs:
            copied = copy_config_records(reuse_from, experiment_id, cfg_name)
            print(f"[experiment_0] config {cfg_name}: {copied} risultati riusati da {reuse_from!r} (nessuna chiamata reale)")

    tasks = generate_tasks(seed=42)
    already_done = {(r["task_id"], r["config_name"]) for r in read_all(experiment_id)}
    print(
        f"[experiment_0] {len(tasks)} tasks, expert={config.EXPERT_PROVIDER}, "
        f"small={config.SMALL_PROVIDER}, experiment_id={experiment_id}"
        + (f", resuming ({len(already_done)} quests already logged)" if already_done else "")
    )

    # EXTRA_CONFIGS (opt-in, unset by default = exactly A/B/F/C, unchanged)
    # -- 2026-09-18, user-requested: a way to try new annotations (Detective,
    # in the future maybe skill_conflict) as ADDITIONAL configs without ever
    # touching what A/B/F/C themselves mean, so their historical numbers
    # stay comparable. Currently only "FD" (F + Detective hint) is wired;
    # naming a config here that this dict doesn't know about is a plain
    # KeyError, not a silent no-op.
    _EXTRA_CONFIG_SPECS = {
        "FD": (small_adapter, True, False, True),  # Small + Librarian + Detective hint
    }
    base_configs = [
        ("A", expert_adapter, False, False, False),
        ("B", small_adapter, False, False, False),
        ("F", small_adapter, True, False, False),
        ("C", small_adapter, False, True, False),  # Cheater: Small + Solution Bank
    ]
    extra_names = [c.strip() for c in os.getenv("EXTRA_CONFIGS", "").split(",") if c.strip()]
    all_configs = base_configs + [(name, *_EXTRA_CONFIG_SPECS[name]) for name in extra_names]

    total_calls = len(tasks) * len(all_configs)
    done = len(already_done)

    quest_specs = [
        (task, config_name, adapter, use_librarian, use_cheater, use_detective)
        for task in tasks
        for config_name, adapter, use_librarian, use_cheater, use_detective in all_configs
        if (task.task_id, config_name) not in already_done
    ]

    # PARALLEL_QUESTS (opt-in, default 1 = comportamento sequenziale
    # originale, invariato) -- ogni quest resta indipendente (task/config
    # diversi non condividono stato, run_quest scrive il proprio record da
    # solo), quindi lanciarne piu' d'una insieme e' sicuro. Aggiunto
    # 2026-09-17 dopo che i tempi reali di un run hanno mostrato Gemma
    # (locale) come il collo di bottiglia dominante, non le chiamate di rete
    # a Gemini -- va abbinato a un llama-server lanciato con --parallel > 1,
    # altrimenti le richieste si accodano comunque lato server.
    try:
        parallel = max(1, int(os.getenv("PARALLEL_QUESTS", "1")))
    except ValueError:
        parallel = 1

    stopped_early = False
    if parallel <= 1:
        for task, config_name, adapter, use_librarian, use_cheater, use_detective in quest_specs:
            if stopped_early:
                break
            try:
                run_quest(task, experiment_id, config_name, adapter, use_librarian=use_librarian, use_cheater=use_cheater, use_detective=use_detective)
            except QuotaExhaustedError as e:
                stopped_early = _report_quota_stop(e, done, total_calls)
                break
            done += 1
            print(f"[experiment_0] {done}/{total_calls} quests run ({task.task_id})", file=sys.stderr)
    else:
        print(f"[experiment_0] modalita' parallela: {parallel} quest concorrenti", file=sys.stderr)
        done_lock = threading.Lock()
        quota_error: list[QuotaExhaustedError] = []
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {
                pool.submit(run_quest, task, experiment_id, config_name, adapter, use_librarian=use_librarian, use_cheater=use_cheater, use_detective=use_detective): (task, config_name)
                for task, config_name, adapter, use_librarian, use_cheater, use_detective in quest_specs
            }
            for future in as_completed(futures):
                task, config_name = futures[future]
                try:
                    future.result()
                except QuotaExhaustedError as e:
                    quota_error.append(e)
                    continue
                with done_lock:
                    done += 1
                    local_done = done
                print(f"[experiment_0] {local_done}/{total_calls} quests run ({task.task_id}::{config_name})", file=sys.stderr)
        if quota_error:
            stopped_early = _report_quota_stop(quota_error[0], done, total_calls)

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

    # Iterato sui config REALMENTE presenti nel log, non una tupla fissa --
    # cosi' una nuova config opt-in (es. "FD") compare qui automaticamente
    # senza un'altra modifica hardcoded ogni volta che se ne aggiunge una.
    for cfg in sorted({r["config_name"] for r in records}):
        cfg_records = [r for r in records if r["config_name"] == cfg]
        if not cfg_records:
            continue
        n = len(cfg_records)
        acc = sum(int(r["passed"]) for r in cfg_records) / n
        cost = sum(r["cost_usd"] for r in cfg_records)
        print(f"\n{cfg} overall: accuracy={acc:.2%} total_cost=${cost:.4f} n={n}")


if __name__ == "__main__":
    main()
