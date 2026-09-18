"""Shared holdout-task lookup, used by both skill_repair.py's caller
(library_benchmark.py) and method_repair.py: this pattern's own REAL,
hand-authored canonical task (domain/task_generator.py's KNOWN split), not
an LLM-generated probe.

Extracted 2026-09-17 after finding library_benchmark.py's floating_point_
equality run stalled with HIGH_RISK_UNRESOLVED because probe_generator.py
failed to produce a usable Category-A holdout -- the real catalog task was
available the whole time (task_generator.generate_tasks(), split="KNOWN")
and is a stronger holdout anyway: it's the actual reference example the
skill was written to document, hand-verified since the project's first
session, not a fresh LLM invention that itself needs a self-check."""

from ..domain.task_generator import generate_tasks
from ..models import Task


def get_known_task(pattern_id: str) -> Task | None:
    """None if this pattern has no real KNOWN task in the catalog -- no
    silent fallback here; a caller decides what to try next (e.g.
    library_benchmark.py falls back to an auto-generated Category-A probe)."""
    for task in generate_tasks():
        if task.pattern_id == pattern_id and task.split == "KNOWN":
            return task
    return None
