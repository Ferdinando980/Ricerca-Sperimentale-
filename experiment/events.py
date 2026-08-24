"""Per-quest event chain for the Experiment Engine -- the real data source behind
the Cognitive City visualization. Every event is grounded in something that
actually happened in the pipeline (no invented state, no chain-of-thought):

  QUEST_CREATED -> NPC_ASSIGNED -> [RETRIEVAL_STARTED -> RETRIEVAL_RESULT]
                 -> PROMPT_BUILT -> MODEL_CALL_STARTED -> MODEL_CALL_FINISHED
                 -> VERIFICATION -> QUEST_COMPLETED

(RETRIEVAL_STARTED/RESULT only fire when the config routes through the
Librarian. There's deliberately no separate ROUTER_DECISION step: in this
codebase which config -- A/B/F -- handles a quest is fixed by the experiment
script before the run even starts, not decided by any runtime router, so a
distinct "router decision" event would carry no real information beyond what
NPC_ASSIGNED already reports. Add it back only once real dynamic routing
exists.)

Each event carries:
  - event_id / parent_event_id: chains events into a tree per quest, so the
    whole "life of the quest" can be reconstructed later (see city/report.py).
  - quest_id: "{task_id}::{config_name}" -- one quest is one (task, NPC) pair;
    deterministic (not a random id) so it's stable across reruns.
  - npc_id: WHICH ROLE performed this step -- "{config_name}:worker",
    "{config_name}:librarian", "{config_name}:checker" -- not a fake per-instance
    id, since there's exactly one of each role per quest today.
  - reason: a short fixed operation-purpose tag (e.g. "solve_task"), never free
    text -- structured "why", not a chain-of-thought leak.
  - architecture_version / generation: static metadata tagging which pipeline
    version produced this event, so future architecture changes (F-v0.1 ->
    F-v0.2 -> ...) can be compared apples-to-apples. generation is always 0 today
    -- there is no teacher/apprentice distillation across generations yet -- the
    field exists so it's ready when that's built, not because it's meaningful now.
"""

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config

ARCHITECTURE_VERSION = "F-v0.1"
GENERATION = 0


@dataclass
class Event:
    event_id: str
    parent_event_id: str | None
    experiment_id: str
    quest_id: str
    task_id: str
    config_name: str
    npc_id: str
    event_type: str
    reason: str | None
    architecture_version: str
    generation: int
    timestamp: str
    data: dict[str, Any]


def events_path(experiment_id: str) -> Path:
    return config.experiment_dir(experiment_id) / "events.jsonl"


def emit(
    experiment_id: str,
    task_id: str,
    config_name: str,
    npc_id: str,
    event_type: str,
    parent_event_id: str | None = None,
    reason: str | None = None,
    **data: Any,
) -> Event:
    event = Event(
        event_id=uuid.uuid4().hex,
        parent_event_id=parent_event_id,
        experiment_id=experiment_id,
        quest_id=f"{task_id}::{config_name}",
        task_id=task_id,
        config_name=config_name,
        npc_id=npc_id,
        event_type=event_type,
        reason=reason,
        architecture_version=ARCHITECTURE_VERSION,
        generation=GENERATION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        data=data,
    )
    with open(events_path(experiment_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(event)) + "\n")
    return event


def read_events(experiment_id: str) -> list[dict]:
    path = events_path(experiment_id)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


_EXPERIMENT_ID_RE = re.compile(r"^experiment\d+$")


def read_events_all_experiments() -> list[dict]:
    """Same as read_events, but merged across every real experiment_id folder
    under logs/ (matching "experimentN" -- excludes ad hoc test dirs like
    cheater_smoketest/ or experiment0_skillfix_test/). The skill library is
    one shared folder across all experiment_ids (see config.LIBRARY_DIR), so a
    pattern's total construction cost (metrics.skill_amortization's build_cost)
    has to look at every experiment that ever ran the Optimizer against it, not
    just the one currently being reported on -- otherwise a skill compressed
    in an earlier experiment and merely reused (not recompressed) in a later
    one reads as free in that later one's report (found 2026-08-18: experiment2's
    knowledge_map showed build_cost=0 for patterns experiment0 had already paid
    to compress)."""
    events = []
    for d in sorted(config.LOG_DIR.iterdir()):
        if d.is_dir() and _EXPERIMENT_ID_RE.match(d.name):
            events.extend(read_events(d.name))
    return events
