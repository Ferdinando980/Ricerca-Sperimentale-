import random

from ..library.loader import library_pattern_ids
from ..models import Task
from .bug_catalog import BASE_PROBLEMS, BUG_PATTERNS, TASK_TEMPLATES


def generate_tasks(seed: int | None = None, splits: set[str] | None = None) -> list[Task]:
    """Split is derived from the library, not hardcoded on the template: a pattern
    counts as KNOWN only for the exact problem its Book uses as a worked example,
    VARIANT for the same pattern on a different problem, and NOVEL whenever no
    Book documents the pattern at all (see design review §J)."""
    covered_patterns = library_pattern_ids()
    tasks = []

    for pattern_id, problem_id, role, buggy_source in TASK_TEMPLATES:
        if pattern_id in covered_patterns:
            split = "KNOWN" if role == "known_example" else "VARIANT"
        else:
            split = "NOVEL"

        if splits is not None and split not in splits:
            continue

        problem = BASE_PROBLEMS[problem_id]
        pattern = BUG_PATTERNS[pattern_id]
        tasks.append(
            Task(
                task_id=f"{pattern_id}__{problem_id}__{role}",
                pattern_id=pattern_id,
                problem_id=problem_id,
                fn_name=problem["fn_name"],
                buggy_source=buggy_source,
                test_source=problem["test_source"],
                split=split,
                problem_tags=["wrong-output", "runtime-bug"],
                capability_tags=pattern["capability_tags"],
            )
        )

    if seed is not None:
        random.Random(seed).shuffle(tasks)
    return tasks
