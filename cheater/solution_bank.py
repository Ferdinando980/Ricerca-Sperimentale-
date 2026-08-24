"""Solution Bank for the Cheater Agent (base implementation, conversation
2026-08-18). Config C: same Small model as B/F, but instead of a general
procedure (F's Skill Library) it gets access to a PAST SOLUTION -- the
experimental question is how much of F's advantage over B comes from real
generalizable competence vs. from having effectively "seen the answer"
before.

WHAT COUNTS AS "THE SOLUTION": deliberately the canonical correct_source
already in domain/bug_catalog.py (the ground truth every buggy variant is
derived from), NOT a real transcript of what Expert actually generated at
runtime -- this codebase never persists raw model completions anywhere
(quest_runner.py: no candidate_source in any log/event, by design, to avoid
a chain-of-thought leak). Building a Solution Bank from real Expert output
would mean revisiting that principle; this base deliberately doesn't, and
uses the ground truth instead (a reasonable proxy: Config A empirically
gets ~95-100% accuracy in this experiment, so "what Expert produces" and
"the canonical correct_source" are close in practice).

THE EXACT/SEEN/NOVEL SPLIT COMES FOR FREE: every pattern in TASK_TEMPLATES
has a "known_example" role tied to one specific problem_id -- except the 3
permanently-NOVEL patterns (variable_shadowing, incorrect_sort_key_or_order,
wrong_return_in_loop), which use only novel_a/novel_b roles by design and
so have no canonical worked example at all. That means, with zero new
classification logic:
  - a task whose OWN role is "known_example"  -> the bank has the EXACT
    solution to this exact task (same problem_id).
  - a task whose role is "variant" (same pattern, different problem_id)
    -> the bank has a solution to a DIFFERENT problem of the SAME pattern
    -- a related-but-not-identical prior case (SEEN).
  - a task of one of the 3 permanently-NOVEL patterns -> no solution
    exists anywhere in the bank for that pattern -- the Cheater has
    nothing to fall back on, same as B.
This lines up exactly with task_generator.py's existing KNOWN/VARIANT/NOVEL
split, just computed independently here (the Skill Library's coverage
depends on which Books a human/Skill Generator wrote; the Solution Bank's
coverage is unconditional -- every non-excluded pattern has a
known_example, always, by the dataset's own construction).
"""

from ..domain.bug_catalog import BASE_PROBLEMS, TASK_TEMPLATES
from ..models import Book, SkillPackage, Task


def _known_example_problem_id(pattern_id: str) -> str | None:
    for pid, problem_id, role, _ in TASK_TEMPLATES:
        if pid == pattern_id and role == "known_example":
            return problem_id
    return None


def lookup(task: Task) -> dict | None:
    """None if this pattern has no known_example at all (the 3 permanent
    NOVEL patterns). Otherwise {"source", "match" ("EXACT"|"SEEN"),
    "source_problem_id"}."""
    known_problem_id = _known_example_problem_id(task.pattern_id)
    if known_problem_id is None:
        return None
    return {
        "source": BASE_PROBLEMS[known_problem_id]["correct_source"],
        "match": "EXACT" if task.problem_id == known_problem_id else "SEEN",
        "source_problem_id": known_problem_id,
    }


def route(task: Task) -> SkillPackage:
    """Same injection mechanism librarian.route() uses (a Book wrapped in a
    SkillPackage, consumed by agents.worker.build_prompt unchanged) -- the
    difference is entirely in WHAT's injected: a specific past solution
    instead of a general procedure. coverage="FULL" for an exact match
    (the literal answer), "PARTIAL" for a same-pattern-different-problem
    match (has to be adapted, not just copied), "NONE" if nothing is
    available for this pattern at all."""
    result = lookup(task)
    if result is None:
        return SkillPackage(books=[], coverage="NONE")

    book = Book(
        id=f"solution_{result['source_problem_id']}",
        version=1,
        title=f"Previously solved problem ({result['match'].lower()} match): {result['source_problem_id']}",
        domain="programming",
        problem_tags=[],
        capability_tags=task.capability_tags,
        resource_tags=["python"],
        procedure_text=result["source"],
        pattern_id=task.pattern_id,
        canonical_problem_id=result["source_problem_id"],
        status="SOLUTION",
        confidence=1.0,
        verification_count=0,
        verification_types=[],
    )
    coverage = "FULL" if result["match"] == "EXACT" else "PARTIAL"
    return SkillPackage(books=[book], coverage=coverage)
