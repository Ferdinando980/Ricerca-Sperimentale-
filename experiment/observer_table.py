"""Flattens events.jsonl into one row per pipeline step, in the schema the user
asked for: npc_id, parent_id, quest_id, step_id, role, prompt_tokens,
context_tokens, retrieved_tokens, tool_tokens, reasoning_tokens, output_tokens.

Not a new data source -- every value here is read straight out of the real
events already emitted by quest_runner.py (see events.py's docstring for the
event chain). This module only reshapes/renames, it invents nothing:

  role            <- npc_id's suffix after ":" (worker/librarian/checker/npc) --
                     confirmed with the user: "pipeline role", not
                     expert/small (that's config_name, kept as its own column).
  step_id         <- 1-based position of this event within its quest_id,
                     ordered by timestamp (events.py has no positional field).
  prompt_tokens   <- data["input_tokens"] if the event carries an actual completion
                     input count, else data["input_tokens_estimate"] (PROMPT_BUILT
                     has no real call yet, only the tokenizer estimate).
  context_tokens  <- data["base_prompt_tokens"] (the task's own prompt, before
                     any retrieved skill is added).
  retrieved_tokens<- data["skill_context_tokens"] (what the Librarian's retrieval
                     added on top of the base prompt). Only RETRIEVAL_RESULT and
                     PROMPT_BUILT carry this; null elsewhere.
  tool_tokens     <- always null. Confirmed with the user: no event in this
                     pipeline corresponds to a tool call distinct from the
                     Worker's own completion (the Librarian's retrieval makes no
                     model call and is already costed via retrieved_tokens), so
                     there is no real number to put here yet. Column kept for
                     schema stability once/if a real tool-call step exists.
  reasoning_tokens<- data["reasoning_output_tokens"] (nullable upstream too --
                     only present when the provider exposes it).
  output_tokens   <- data["output_tokens"].
  latency_ms      <- data["latency_ms"] (only MODEL_CALL_FINISHED carries this --
                     the Librarian's retrieval and pytest verification are not
                     timed today, so null on every other step).
  cost_usd        <- data["cost_usd"] (same event, real $ from the adapter;
                     $0 wherever the provider has no configured price, see
                     config.py's *_PRICING).
  passed          <- data["passed"] (only VERIFICATION and QUEST_COMPLETED carry
                     this -- null on every earlier step, there's no partial
                     result before the checker runs).

A second table, one row per quest_id (not per step), mirrors the "QUEST SCORE"
block: correctness/latency/cost/npc_calls/verification. This is NOT a new
measurement -- it's the corresponding LogRecord from log.jsonl (already one row
per quest) relabeled to match, plus npc_calls counted from real
MODEL_CALL_FINISHED events. Two real ambiguities were resolved by asking the
user first (see conversation): "cost" in the mockup used token-scale numbers,
not dollars, so input_cost/reasoning_cost below are token counts
(prompt/reasoning tokens) -- the real $ figure is also included as cost_usd so
neither reading is lost.

Run: python -m cognitive_rpg.experiment.observer_table <experiment_id>
Writes logs/{experiment_id}/observer_table.csv (per step) and
logs/{experiment_id}/quest_scores.csv (per quest) next to log.jsonl/events.jsonl.
"""

import csv
import sys
from pathlib import Path

from .. import config
from .events import read_events
from .experiment_log import read_all

COLUMNS = [
    "npc_id", "parent_id", "quest_id", "step_id", "role", "event_type",
    "config_name", "prompt_tokens", "context_tokens", "retrieved_tokens",
    "tool_tokens", "reasoning_tokens", "output_tokens", "latency_ms",
    "cost_usd", "passed", "timestamp",
]

QUEST_SCORE_COLUMNS = [
    "quest_id", "task_id", "config_name", "split", "npc_calls",
    "correctness", "verification", "latency_s", "input_cost",
    "reasoning_cost", "output_cost", "cost_usd", "retries", "timestamp",
]


def build_table(experiment_id: str) -> list[dict]:
    events = read_events(experiment_id)
    events.sort(key=lambda e: e["timestamp"])

    step_counters: dict[str, int] = {}
    rows = []
    for e in events:
        quest_id = e["quest_id"]
        step_counters[quest_id] = step_counters.get(quest_id, 0) + 1
        data = e["data"]
        npc_id = e["npc_id"]
        role = npc_id.split(":", 1)[1] if ":" in npc_id else npc_id

        prompt_tokens = data.get("input_tokens")
        if prompt_tokens is None:
            prompt_tokens = data.get("input_tokens_estimate")

        rows.append({
            "npc_id": npc_id,
            "parent_id": e["parent_event_id"],
            "quest_id": quest_id,
            "step_id": step_counters[quest_id],
            "role": role,
            "event_type": e["event_type"],
            "config_name": e["config_name"],
            "prompt_tokens": prompt_tokens,
            "context_tokens": data.get("base_prompt_tokens"),
            "retrieved_tokens": data.get("skill_context_tokens"),
            "tool_tokens": None,
            "reasoning_tokens": data.get("reasoning_output_tokens"),
            "output_tokens": data.get("output_tokens"),
            "latency_ms": data.get("latency_ms"),
            "cost_usd": data.get("cost_usd"),
            "passed": data.get("passed"),
            "timestamp": e["timestamp"],
        })
    return rows


def build_quest_scores(experiment_id: str) -> list[dict]:
    """One row per quest_id, matching the QUEST SCORE mockup. Base fields come
    straight from log.jsonl (already one row per quest); npc_calls is the only
    value not already sitting on the LogRecord, so it's counted for real from
    MODEL_CALL_FINISHED events instead of assumed to be 1."""
    records = read_all(experiment_id)
    events = read_events(experiment_id)

    npc_calls: dict[str, int] = {}
    for e in events:
        if e["event_type"] == "MODEL_CALL_FINISHED":
            qid = e["quest_id"]
            npc_calls[qid] = npc_calls.get(qid, 0) + 1

    rows = []
    for r in records:
        quest_id = f"{r['task_id']}::{r['config_name']}"
        rows.append({
            "quest_id": quest_id,
            "task_id": r["task_id"],
            "config_name": r["config_name"],
            "split": r["split"],
            "npc_calls": npc_calls.get(quest_id, 0),
            "correctness": 1.0 if r["passed"] else 0.0,
            "verification": "PASS" if r["passed"] else "FAIL",
            "latency_s": round(r["latency_ms"] / 1000, 3),
            "input_cost": r["input_tokens"],
            "reasoning_cost": r["reasoning_output_tokens"] or 0,
            "output_cost": r["output_tokens"],
            "cost_usd": r["cost_usd"],
            "retries": r["retries"],
            "timestamp": r["timestamp"],
        })
    return rows


def write_csv(experiment_id: str) -> Path:
    rows = build_table(experiment_id)
    out_path = config.experiment_dir(experiment_id) / "observer_table.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def write_quest_scores_csv(experiment_id: str) -> Path:
    rows = build_quest_scores(experiment_id)
    out_path = config.experiment_dir(experiment_id) / "quest_scores.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=QUEST_SCORE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


if __name__ == "__main__":
    experiment_id = sys.argv[1] if len(sys.argv) > 1 else config.get_current_experiment_id()
    step_path = write_csv(experiment_id)
    score_path = write_quest_scores_csv(experiment_id)
    print(f"[observer_table] scritto {step_path}")
    print(f"[observer_table] scritto {score_path}")
