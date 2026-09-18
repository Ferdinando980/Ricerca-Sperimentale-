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
