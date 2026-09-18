import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..adapters.base import CompletionResult

# 2026-09-18: same real race condition fixed in events.py's emit() -- a
# multi-threaded PARALLEL_QUESTS run appends to the same log.jsonl file
# from several threads at once, and an unguarded open/write/close is not
# guaranteed atomic. One process-wide lock serializes the actual write.
_write_lock = threading.Lock()


@dataclass
class LogRecord:
    experiment_id: str
    task_id: str
    split: str
    config_name: str  # A | B | F
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_output_tokens: int | None
    cost_usd: float
    latency_ms: float
    retries: int
    paused_seconds: float
    passed: bool
    coverage: str
    timestamp: str


def log_path(experiment_id: str) -> Path:
    return config.experiment_dir(experiment_id) / "log.jsonl"


def archive(experiment_id: str) -> None:
    """Renames (never deletes) the whole logs/{experiment_id}/ folder, tagged with
    the current time, so a fresh run can reuse the plain id without losing prior
    data."""
    folder = config.LOG_DIR / experiment_id
    if folder.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        folder.rename(config.LOG_DIR / f"{experiment_id}_archived_{stamp}")


def append(record: LogRecord) -> None:
    line = json.dumps(asdict(record)) + "\n"
    with _write_lock:
        with open(log_path(record.experiment_id), "a", encoding="utf-8") as f:
            f.write(line)


def copy_config_records(source_experiment_id: str, target_experiment_id: str, config_name: str) -> int:
    """Copies one config's LogRecords from a previous experiment into this
    one, re-pointed at target_experiment_id -- 2026-09-18, user-requested:
    Config A (Expert alone) doesn't depend on the Librarian/skills, so on an
    UNCHANGED task catalog its accuracy carries over exactly, and re-running
    it for every new experiment that only varies B/F-side configs wastes
    real Expert quota for no new information. Generic across any config
    name, not hardcoded to "A" -- whatever is genuinely unaffected by what a
    new experiment varies can be reused the same way.

    Never overwrites: only adds records for (task_id, config_name) pairs
    the target doesn't already have, so the existing resume/skip logic in
    experiment_0.py picks these up naturally as "already done" -- no new
    skip logic needed, this only pre-seeds the log the resume check reads.
    Returns the number of records actually copied."""
    source_records = [r for r in read_all(source_experiment_id) if r["config_name"] == config_name]
    already = {(r["task_id"], r["config_name"]) for r in read_all(target_experiment_id)}
    copied = 0
    for r in source_records:
        if (r["task_id"], config_name) in already:
            continue
        record = LogRecord(**{**r, "experiment_id": target_experiment_id})
        append(record)
        copied += 1
    return copied


def new_record(
    experiment_id: str,
    task_id: str,
    split: str,
    config_name: str,
    completion: CompletionResult,
    passed: bool,
    coverage: str = "N/A",
) -> LogRecord:
    return LogRecord(
        experiment_id=experiment_id,
        task_id=task_id,
        split=split,
        config_name=config_name,
        model=completion.model,
        provider=completion.provider,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        cached_input_tokens=completion.cached_input_tokens,
        reasoning_output_tokens=completion.reasoning_output_tokens,
        cost_usd=completion.cost_usd,
        latency_ms=completion.latency_ms,
        retries=completion.retries,
        paused_seconds=completion.paused_seconds,
        passed=passed,
        coverage=coverage,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def read_all(experiment_id: str) -> list[dict]:
    path = log_path(experiment_id)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
