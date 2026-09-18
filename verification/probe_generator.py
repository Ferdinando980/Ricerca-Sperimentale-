"""Automates writing A/B/C probe tasks (task-sonda) for an arbitrary skill
(Book) -- the step canary.py did entirely by hand for floating_point_equality
(see its module docstring, 2026-08-18/19: reading the skill, inventing a
plausible no-hint / domain-hint / explicit-hint problem, writing buggy_source
plus a pytest suite that actually distinguishes buggy from fixed, all by a
human).

Generated via the Expert adapter (generation infrastructure, not the model
under test -- same role split as skill_repair.py's rewriter). Every generated
probe is self-checked the same way a human author would have to satisfy by
construction: buggy_source must actually FAIL its own test_source (a "bug"
that already passes its own tests measures nothing) -- verified by actually
running it (domain/verifier.run_tests), retried up to a fixed number of
attempts, never accepted on the model's own claim alone.

MANDATORY before trusting this on any untested skill (see the plan,
Workstream A point 2): rerun it on floating_point_equality, whose true
qualitative shape is already known from canary.py, and check the freshly
generated probes reproduce the same kind of tier-c tracking / tier-b
selectivity when fed through substitution_ablation.py -- see
validate_probe_generator_milestone.py. Skipping this and trusting generated
probes on a brand-new skill first would repeat exactly the mistake
substitution_ablation.py's own validation milestone was built to avoid.
"""

import json
import re

from ..adapters.base import ModelAdapter
from ..domain.verifier import run_tests
from ..models import Book, Task

# Mirrors canary.py's own category definitions (module docstring) exactly --
# this is the automation of that existing, hand-validated taxonomy, not a new
# one.
CATEGORY_DESCRIPTIONS = {
    "A": (
        "CATEGORY_A (explicit hint): a problem where the missing parameter/rule "
        "the skill supplies (a tolerance, a default, an operator choice, ...) IS "
        "stated explicitly in the problem's own wording (a percentage, a named "
        "margin, a concrete rule). Measures whether the model APPLIES the "
        "procedure when given what it needs, not whether it invents anything."
    ),
    "B": (
        "CATEGORY_B (domain-recognizable, no number): a problem where the "
        "parameter is NOT stated as a number or explicit rule, but the domain is "
        "recognizable from naming (a physical unit in a variable name, a "
        "domain-specific term). Some signal, just not a number."
    ),
    "C": (
        "CATEGORY_C (no signal at all): no number, no percentage, no unit, no "
        "domain-revealing naming anywhere in the problem. Only a genuine probe "
        "if there really IS a derivable correct answer from general reasoning "
        "alone (a real convention, e.g. currency -> cent precision) -- if you "
        "cannot think of a real, defensible reason the correct value follows "
        "from general knowledge without ANY hint, still write the most "
        "hint-free version you can; do not invent a fake convention to make it "
        "look valid. Whether it is actually usable is decided later, by "
        "checking whether an unaided model converges on it independently -- "
        "not assumed here."
    ),
}

_PROBE_SYSTEM_PROMPT = (
    "You write probe tasks used to test whether a language model applies a "
    "debugging procedure ('skill') by genuine reasoning or by copying a "
    "literal example from the procedure's own text verbatim. Given a skill's "
    "procedure text and a target category, invent ONE new, small, "
    "self-contained Python function with a realistic bug matching the "
    "skill's pattern, plus a pytest test suite (plain `def test_...(): "
    "assert ...` functions only -- no imports, no fixtures, no pytest.mark) "
    "that actually FAILS against the buggy version and would PASS a correct "
    "fix. Return ONLY a single JSON object, no prose, no markdown code "
    'fences, with exactly these keys: {"problem_id": "...", "fn_name": '
    '"...", "buggy_source": "...", "test_source": "..."}. buggy_source and '
    "test_source are raw Python source code as JSON strings (use \\n for "
    "newlines). Do not reuse any example, function name, or scenario that "
    "already appears in the procedure text verbatim -- a probe that recites "
    "the skill's own example measures nothing."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_SPLIT_BY_CATEGORY = {"A": "CATEGORY_A", "B": "CATEGORY_B", "C": "CATEGORY_C"}


def _build_probe_prompt(book: Book, category: str, avoid_problem_ids: list[str]) -> str:
    avoid = f" Avoid these problem_ids, already used for this skill: {avoid_problem_ids}." if avoid_problem_ids else ""
    return (
        f"Skill procedure text (pattern: {book.pattern_id!r}):\n\n{book.procedure_text}\n\n"
        f"Target category:\n{CATEGORY_DESCRIPTIONS[category]}\n\n"
        f"Write ONE new probe task for this category, matching pattern {book.pattern_id!r}.{avoid}"
    )


def _parse_generated_task(text: str, book: Book, category: str) -> Task | None:
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    required = {"problem_id", "fn_name", "buggy_source", "test_source"}
    if not required.issubset(data) or not isinstance(data["problem_id"], str):
        return None
    if not data["buggy_source"].strip() or not data["test_source"].strip():
        return None
    return Task(
        task_id=f"{book.pattern_id}__{data['problem_id']}__generated_{category.lower()}",
        pattern_id=book.pattern_id,
        problem_id=data["problem_id"],
        fn_name=data["fn_name"],
        buggy_source=data["buggy_source"],
        test_source=data["test_source"],
        split=_SPLIT_BY_CATEGORY[category],
        problem_tags=list(book.problem_tags),
        capability_tags=list(book.capability_tags),
    )


def generate_probe(
    book: Book,
    category: str,
    adapter: ModelAdapter,
    avoid_problem_ids: list[str] | None = None,
    max_attempts: int = 3,
) -> Task | None:
    """One self-checked probe in the given category, or None if max_attempts
    is exhausted without producing a usable one. 'Usable' means: parses into a
    Task, AND buggy_source genuinely fails test_source (verified by actually
    running it, not assumed from the model's own claim) -- the same bar a
    human author meets by construction when hand-writing a canary task."""
    avoid = list(avoid_problem_ids or [])
    for _ in range(max_attempts):
        prompt = _build_probe_prompt(book, category, avoid)
        # 4096, not 1024: a smaller cap silently truncated reasoning-model
        # output mid-JSON (the same failure agents/worker.py already
        # documents for this provider class -- gemini-3.7-flash spends
        # hundreds of tokens on internal reasoning before writing anything).
        # Every category A/B attempt failed to parse under 1024, not because
        # the model couldn't write a valid probe.
        completion = adapter.complete(prompt=prompt, system=_PROBE_SYSTEM_PROMPT, max_tokens=4096)
        task = _parse_generated_task(completion.text, book, category)
        if task is None:
            continue
        result = run_tests(task.buggy_source, task.test_source)
        if result.passed:
            # The "buggy" source passes its own tests -- the tests don't
            # actually exercise the claimed bug, so this probe would measure
            # nothing. Not usable; retry with this problem_id excluded so the
            # model doesn't just regenerate the same non-bug.
            avoid.append(task.problem_id)
            continue
        return task
    return None


def generate_probe_set(
    book: Book,
    adapter: ModelAdapter,
    categories: tuple[str, ...] = ("A", "B", "C"),
    max_attempts: int = 3,
) -> dict[str, Task | None]:
    """Generates one probe per requested category. A None entry for 'C' is
    expected and legitimate (see CATEGORY_C's own description above) -- a
    caller must NOT treat a None C as a bug in this generator, matching
    canary.py's own INVALID_EXAMPLES precedent (most hand-attempted C probes
    there were invalid; only currency and significant-figures ever
    validated). A None for A or B is more concerning and worth logging."""
    used_ids: list[str] = []
    probes: dict[str, Task | None] = {}
    for category in categories:
        task = generate_probe(book, category, adapter, avoid_problem_ids=used_ids, max_attempts=max_attempts)
        probes[category] = task
        if task is not None:
            used_ids.append(task.problem_id)
    return probes
