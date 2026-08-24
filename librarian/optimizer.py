"""Skill compression + re-verification pipeline (batch, run AFTER an Experiment
Engine run -- it reads that run's real event log, it does not run live inside a
quest). Implements the loop the user described:

  NPC Worker observes its own cost -> notices a skill is expensive
  -> writes a compressed version -> tests it on the tasks that used the
  original -> keeps it only if it holds up -> saves it as a new Book.

Design decisions made explicitly here (none of this is in the user's original
description, so they're spelled out rather than silently guessed):
  - WHO compresses: the Small-role adapter itself (the same model that actually
    uses the skill), not a separate "editor" role.
  - TRIGGER: a skill whose average skill_context_tokens (real, from
    RETRIEVAL_RESULT events) exceeds `min_avg_tokens` AND was used at least
    `min_uses` times in the run.
  - VERIFICATION: re-run pytest (real, same verifier as the main pipeline) on
    every task that historically retrieved this skill, with ONLY the compressed
    book injected (isolates this skill's effect).
  - SELECTION (changed 2026-08-18, "evolutionary" pass): a single compression
    sample turned out to be noisy -- book_floating_point_equality looked like
    a clean reject (1/2 vs 2/2) on one sample, but 6 repeated samples showed
    it was really 83% vs 100%, a real but partial effect (see
    library/compression_failures/repeated_verification_floating_point_equality_20260818.md).
    So instead of one compress+verify per skill, this generates N_CANDIDATES
    independent compressions, verifies each, and keeps the SHORTEST candidate
    whose pass rate is >= MIN_ACCEPT_RATIO of the original's -- not the first
    one tried, and not required to match the original exactly (some
    reproducible loss is tolerated in exchange for a real token reduction).
  - PERSISTENCE: the winning compression is saved as a NEW Book file
    (id "{original_id}_v{version+1}"), never overwriting the original -- so
    both stay available for comparison. If NO candidate clears the bar, all
    N attempts are written to library/compression_failures/ as one record --
    original text, every compressed candidate tried, and a per-task
    original-vs-compressed pass/fail breakdown -- specifically so a "which bug
    patterns compress cleanly and which don't" study is possible later
    without having thrown the data away. This directory is a sibling of
    library/books/, never inside it, so load_books() can never accidentally
    route on a rejected skill.
  - NOT handled here: making the Librarian's retrieval prefer a newer/cheaper
    version when both exist for the same pattern -- that's routing-selection
    logic, a separate concern from creating and verifying the skill.

Run: python -m cognitive_rpg.librarian.optimizer <experiment_id> [min_avg_tokens] [min_uses]
"""

import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .. import config
from ..adapters import build_adapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..domain.task_generator import generate_tasks
from ..domain.verifier import run_tests
from ..experiment.events import emit, read_events
from ..experiment.experiment_log import read_all
from ..library.loader import load_books
from ..models import Book, SkillPackage

_OPTIMIZER_CONFIG = "OPTIMIZER"
_N_CANDIDATES = 6
_MIN_ACCEPT_RATIO = 0.8

_COMPRESSION_SYSTEM_PROMPT = (
    "You compress debugging procedures for a shared knowledge library. You will "
    "be given a procedure. Rewrite it to be as short as possible while keeping "
    "every actionable step and the diagnostic symptom -- an engineer must still "
    "be able to follow it with no loss of usefulness. Return ONLY the rewritten "
    "procedure text, no preamble, no code fences."
)


def _skill_usage(experiment_id: str) -> dict[str, dict]:
    """Real per-skill stats from this run's own event log: how many times a
    skill was retrieved, its average real token cost, and which (task_id,
    config_name) quests used it -- plus whether each of those quests passed,
    read from the same run's log.jsonl."""
    events = read_events(experiment_id)
    records = {(r["task_id"], r["config_name"]): r["passed"] for r in read_all(experiment_id)}

    usage: dict[str, dict] = defaultdict(lambda: {"uses": [], "quests": []})
    for e in events:
        if e["event_type"] != "RETRIEVAL_RESULT":
            continue
        for skill_id in e["data"].get("skill_ids", []):
            key = (e["task_id"], e["config_name"])
            usage[skill_id]["uses"].append(e["data"].get("skill_context_tokens", 0))
            usage[skill_id]["quests"].append(key)

    result = {}
    for skill_id, u in usage.items():
        n = len(u["uses"])
        passed = sum(1 for q in u["quests"] if records.get(q) is True)
        result[skill_id] = {
            "n_uses": n,
            "avg_skill_context_tokens": sum(u["uses"]) / n if n else 0,
            "quests": u["quests"],
            "original_passed": passed,
        }
    return result


def find_candidates(experiment_id: str, min_avg_tokens: float = 100.0, min_uses: int = 2) -> list[dict]:
    usage = _skill_usage(experiment_id)
    books_by_id = {b.id: b for b in load_books()}
    candidates = []
    for skill_id, stats in usage.items():
        if skill_id not in books_by_id:
            continue
        if stats["n_uses"] < min_uses or stats["avg_skill_context_tokens"] < min_avg_tokens:
            continue
        candidates.append({"book": books_by_id[skill_id], **stats})
    return candidates


def compress_skill(experiment_id: str, book: Book, adapter, candidate_index: int | None = None) -> str:
    prompt = (
        f"Procedure to compress (currently {len(book.procedure_text.split())} words):\n\n"
        f"{book.procedure_text}"
    )
    emit(
        experiment_id, f"skill:{book.id}", _OPTIMIZER_CONFIG, "optimizer:worker",
        "SKILL_COMPRESSION_STARTED", reason="compress_skill", skill_id=book.id,
        candidate_index=candidate_index,
        provider=adapter.PROVIDER, model=getattr(adapter, "model", "?"),
    )
    result = adapter.complete(prompt=prompt, system=_COMPRESSION_SYSTEM_PROMPT, max_tokens=1024)
    compressed = result.text.strip()
    emit(
        experiment_id, f"skill:{book.id}", _OPTIMIZER_CONFIG, "optimizer:worker",
        "SKILL_COMPRESSION_FINISHED", reason="compress_skill", skill_id=book.id,
        candidate_index=candidate_index,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        cost_usd=result.cost_usd, latency_ms=result.latency_ms,
    )
    return compressed


def verify_compressed(
    experiment_id: str, book: Book, compressed_text: str, quest_keys: list[tuple[str, str]], adapter,
    candidate_index: int | None = None,
) -> list[tuple[str, bool]]:
    """Re-runs real pytest verification for every (task_id, config_name) that
    historically used `book`, with ONLY the compressed text injected. Returns
    the per-task_id pass/fail (not just a count) -- needed to build a useful
    compression-failure record when the compressed version is rejected: which
    specific task(s) it broke, not just how many."""
    tasks_by_id = {t.task_id: t for t in generate_tasks(seed=42)}
    compressed_package = SkillPackage(books=[Book(**{**asdict(book), "procedure_text": compressed_text})])

    results: list[tuple[str, bool]] = []
    seen_tasks = {tid for tid, _ in quest_keys}
    for task_id in seen_tasks:
        task = tasks_by_id.get(task_id)
        if task is None:
            continue
        prompt = build_prompt(task, compressed_package)
        result = adapter.complete(prompt=prompt, system=SYSTEM_PROMPT, max_tokens=4096)
        candidate_source = extract_code(result.text)
        verification = run_tests(candidate_source, task.test_source)
        emit(
            experiment_id, f"skill:{book.id}", _OPTIMIZER_CONFIG, "optimizer:checker",
            "SKILL_REVERIFICATION", reason="verify_compressed_skill", skill_id=book.id,
            candidate_index=candidate_index,
            reverified_task_id=task_id, passed=verification.passed,
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        )
        results.append((task_id, verification.passed))
    return results


def save_compressed_book(book: Book, compressed_text: str, output_dir: Path | None = None) -> Path:
    new_id = f"{book.id}_v{book.version + 1}"
    data = {
        "id": new_id,
        "version": book.version + 1,
        "title": f"{book.title} (compressed)",
        "domain": book.domain,
        "problem_tags": book.problem_tags,
        "capability_tags": book.capability_tags,
        "resource_tags": book.resource_tags,
        "pattern_id": book.pattern_id,
        "canonical_problem_id": book.canonical_problem_id,
        "status": "VERIFIED",
        "confidence": book.confidence,
        "verification_count": book.verification_count + 1,
        "verification_types": book.verification_types + ["self_compression_reverify"],
        "procedure_text": compressed_text,
        "derived_from": book.id,  # Phase 4 genealogy (2026-08-18)
        "generation_method": "compression",
    }
    out_path = (output_dir or config.LIBRARY_DIR) / f"{new_id}.yaml"
    out_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out_path


def save_compression_failure(
    experiment_id: str, book: Book, attempts: list[dict],
    original_by_task: dict[str, bool | None], min_accept_ratio: float,
    failures_dir: Path | None = None,
) -> Path:
    """Rejected compressions used to just vanish -- the attempt was decided on
    and thrown away, leaving only a pass/fail count in the event log with no
    way to later study WHY a given skill resists compression (see conversation
    2026-08-18: this is meant to build into a dataset of compression failures,
    e.g. to find out empirically which bug patterns compress cleanly and which
    don't). Written next to library/books/, never inside it, so it can never
    be picked up by load_books() as a routable skill.

    `attempts` holds EVERY candidate tried (not just the best), each a dict
    with index/text/words/by_task/passed_n -- a single rejected sample looked
    like a hard wall for book_floating_point_equality but 6 repeated samples
    showed an 83%-vs-100% partial effect instead (see
    library/compression_failures/repeated_verification_floating_point_equality_20260818.md),
    so keeping only the "best" failed attempt would silently throw that shape
    away again."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    data = {
        "skill_id": book.id,
        "pattern_id": book.pattern_id,
        "experiment_id": experiment_id,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "status": "REJECTED",
        "original_version": book.version,
        "original_procedure_text": book.procedure_text,
        "original_words": len(book.procedure_text.split()),
        "min_accept_ratio": min_accept_ratio,
        "n_candidates": len(attempts),
        "candidates": [
            {
                "index": a["index"],
                "procedure_text": a["text"],
                "words": a["words"],
                "passed_n": a["passed_n"],
                "per_task": {
                    task_id: {
                        "original_passed": original_by_task.get(task_id),
                        "compressed_passed": a["by_task"].get(task_id),
                    }
                    for task_id in sorted(set(original_by_task) | set(a["by_task"]))
                },
            }
            for a in attempts
        ],
    }
    out_dir = failures_dir or config.COMPRESSION_FAILURES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{book.id}_{stamp}.yaml"
    out_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out_path


def optimize(
    experiment_id: str, min_avg_tokens: float = 100.0, min_uses: int = 2, output_dir: Path | None = None,
    n_candidates: int = _N_CANDIDATES, min_accept_ratio: float = _MIN_ACCEPT_RATIO,
) -> list[dict]:
    adapter = build_adapter("small")
    candidates = find_candidates(experiment_id, min_avg_tokens, min_uses)
    records_by_key = {(r["task_id"], r["config_name"]): r["passed"] for r in read_all(experiment_id)}
    results = []
    for c in candidates:
        book = c["book"]
        n_tasks = len(set(c["quests"]))
        original_words = len(book.procedure_text.split())
        min_passed_needed = min_accept_ratio * c["original_passed"]
        print(
            f"[optimizer] {book.id}: {c['n_uses']} usi, {c['avg_skill_context_tokens']:.0f} token medi -- "
            f"genero {n_candidates} candidati (soglia: >= {min_accept_ratio:.0%} di {c['original_passed']}/{n_tasks} originale)"
        )

        attempts = []
        for i in range(1, n_candidates + 1):
            compressed = compress_skill(experiment_id, book, adapter, candidate_index=i)
            comp_results = verify_compressed(experiment_id, book, compressed, c["quests"], adapter, candidate_index=i)
            by_task = dict(comp_results)
            passed_n = sum(1 for _, p in comp_results if p)
            words = len(compressed.split())
            attempts.append({"index": i, "text": compressed, "words": words, "by_task": by_task, "passed_n": passed_n})
            print(f"[optimizer]   candidato {i}/{n_candidates}: {passed_n}/{n_tasks} passate, {words} parole")

        # 2026-08-19 fix (prompted by external review, found via a real check
        # against logged history, not a hypothetical): this used to require
        # only passed_n >= min_passed_needed -- NEVER checking a candidate
        # against original_words at all. "ACCEPTED" therefore meant "didn't
        # break accuracy", not "actually compressed" -- 4 of the 10
        # SKILL_ACCEPTED events on disk as of this date had, when checked
        # against their true parent book, a HIGHER word count than the
        # original (book_floating_point_equality_v4_v5: 103->299 words,
        # +196 -- the biggest offender). "words < original_words" closes
        # that gap: a candidate that grows the procedure can still pass
        # verification, but can no longer be accepted AS a compression.
        qualifying = [a for a in attempts if a["passed_n"] >= min_passed_needed and a["words"] < original_words]
        best = min(qualifying, key=lambda a: a["words"]) if qualifying else None
        accepted = best is not None

        emit(
            experiment_id, f"skill:{book.id}", _OPTIMIZER_CONFIG, "optimizer:npc",
            "SKILL_ACCEPTED" if accepted else "SKILL_REJECTED", reason="optimize_skill",
            skill_id=book.id, original_passed=c["original_passed"], n_tasks=n_tasks,
            n_candidates=n_candidates, min_accept_ratio=min_accept_ratio,
            best_candidate_index=best["index"] if best else None,
            best_candidate_passed=best["passed_n"] if best else None,
            best_candidate_words=best["words"] if best else None,
            compressed_text=best["text"] if best else None,
        )
        saved_path = None
        if accepted:
            saved_path = save_compressed_book(book, best["text"], output_dir)
            print(
                f"[optimizer]   ACCETTATA: candidato {best['index']} ({best['passed_n']}/{n_tasks}, {best['words']}p, "
                f"il piu' corto tra {len(qualifying)}/{n_candidates} validi) -> {saved_path}"
            )
        else:
            original_by_task = {
                task_id: records_by_key.get((task_id, config_name))
                for task_id, config_name in c["quests"]
            }
            saved_path = save_compression_failure(experiment_id, book, attempts, original_by_task, min_accept_ratio)
            grew_but_passed = [a for a in attempts if a["passed_n"] >= min_passed_needed and a["words"] >= original_words]
            reason = (
                f"{len(grew_but_passed)}/{n_candidates} passavano la verifica ma non erano piu' corti dell'originale ({original_words}p)"
                if grew_but_passed
                else f"nessuno dei {n_candidates} candidati raggiunge {min_accept_ratio:.0%} di {c['original_passed']}/{n_tasks}"
            )
            print(f"[optimizer]   RESPINTA: {reason} -- libreria invariata, autopsia -> {saved_path}")

        results.append({
            "skill_id": book.id, "accepted": accepted,
            "original_passed": c["original_passed"], "n_tasks": n_tasks,
            "best_candidate_passed": best["passed_n"] if best else None,
            "original_words": original_words, "best_candidate_words": best["words"] if best else None,
            "n_candidates": n_candidates, "n_qualifying": len(qualifying),
            "saved_path": str(saved_path) if saved_path else None,
        })
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "usage: python -m cognitive_rpg.librarian.optimizer <experiment_id> "
            "[min_avg_tokens] [min_uses] [output_dir] [n_candidates] [min_accept_ratio]",
            file=sys.stderr,
        )
        sys.exit(1)
    exp_id = sys.argv[1]
    min_tok = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
    min_n = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    out_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    n_cand = int(sys.argv[5]) if len(sys.argv) > 5 else _N_CANDIDATES
    accept_ratio = float(sys.argv[6]) if len(sys.argv) > 6 else _MIN_ACCEPT_RATIO
    out = optimize(exp_id, min_tok, min_n, out_dir, n_cand, accept_ratio)
    if not out:
        print("[optimizer] nessuna skill sopra soglia in questo run.")
