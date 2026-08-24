"""Skill Generator (Phase 6 of the library evolution plan, conversation
2026-08-18) -- gap-driven, not "generate a skill for every concept" (spec
#4/#17). Implements the spec's rigid 10-step procedure, reusing existing
machinery rather than duplicating it:

  1. identify the section's domain           -> library/sections.py
  2. find relevant tasks/evidence             -> domain/bug_catalog.py's
                                                 TASK_TEMPLATES for the gap
                                                 pattern (already exist --
                                                 written by a human, this
                                                 module doesn't invent tasks)
  3. recurring error pattern?                 -> BUG_PATTERNS[pattern_id]
                                                 (already exists, same reason)
  4. check related skills elsewhere           -> librarian/similarity.py's
                                                 classify_pair, scoped to the
                                                 gap's own section (same
                                                 "potentially relevant" scope
                                                 Phase 2 already established)
  5. equivalent found -> LINK, not duplicate  -> reported, not auto-acted
                                                 (same policy as Phase 2/3:
                                                 classify and report, a human
                                                 decides, not automated)
  6. generate candidate                       -> generate_candidate() below,
                                                 Expert adapter (spec's own
                                                 component list names Expert
                                                 as the "Skill Builder")
  7. verify candidate                          -> verify_candidate() below,
                                                 same real pytest verify as
                                                 everywhere else in this repo
  8-9. optimize + re-verify                    -> NOT done here. Compression
                                                 needs real usage data
                                                 (min_uses>=2 from actual
                                                 RETRIEVAL_RESULT events,
                                                 librarian/optimizer.py's
                                                 find_candidates()) that a
                                                 brand-new skill doesn't have
                                                 yet. Run optimizer.py on it
                                                 later, same as any other
                                                 skill, once it's been used.
  10. only if it passes the gate, add          -> save_generated_book(),
                                                 status VERIFIED only if
                                                 verify_candidate got 2/2;
                                                 otherwise nothing is written.

GATE: must pass BOTH the known_example and variant task for its pattern
(2/2, no partial credit) -- this is originating a skill from nothing, held
to a stricter bar than the Optimizer's 80%-of-original compression
threshold, matching spec #6's "se supera la verifica, entra nella libreria
-- se fallisce, NON entra" (no tolerance language there, unlike compression).

HARD CONSTRAINT: only ever called for a pattern_id where
library.sections.GENERATION_ELIGIBLE[pattern_id] is True. The 3 permanently-
NOVEL patterns (variable_shadowing, incorrect_sort_key_or_order,
wrong_return_in_loop) are the experiment's control group by original design
-- find_gaps() filters them out itself, but every entry point re-checks
GENERATION_ELIGIBLE too, since a constraint checked in only one place is a
constraint one refactor away from silently breaking.

Run: python -m cognitive_rpg.librarian.skill_generator
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .. import config
from ..adapters import build_adapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..domain.bug_catalog import BUG_PATTERNS, TASK_TEMPLATES
from ..domain.task_generator import generate_tasks
from ..domain.verifier import run_tests
from ..library import sections as sections_mod
from ..library.loader import load_books
from ..models import Book, SkillPackage
from .librarian import _latest_per_pattern
from .similarity import classify_pair

_GENERATION_SYSTEM_PROMPT = (
    "You write debugging procedures (\"Books\") for a shared knowledge "
    "library used by a smaller/cheaper model to fix bugs it wouldn't "
    "reliably catch alone. You will be given: a bug pattern name and "
    "description, and ONE worked example (buggy code + the corrected "
    "version). Write a general procedure that lets someone recognize and "
    "fix OTHER instances of this SAME pattern, not just this one example. "
    "Structure: a Symptom line (how to recognize it), a numbered Procedure "
    "(concrete, actionable steps), and an Example line referencing the "
    "worked example you were given. Do not pad with generic advice -- every "
    "line must be something a reader could not already infer from the "
    "function signature alone. Return ONLY the procedure text, no preamble, "
    "no code fences."
)


def find_gaps() -> list[dict]:
    """A legitimate gap: GENERATION_ELIGIBLE (not one of the 3 permanent-
    NOVEL control patterns) AND no Book currently covers it. Not "section is
    EMPTY" alone -- spec #5 requires evidence before deciding to build, and
    the evidence here is exactly "this eligible pattern still has zero
    coverage", read straight from the same source task_generator.py uses."""
    covered = {b.pattern_id for b in load_books()}
    gaps = []
    for pattern_id, eligible in sections_mod.GENERATION_ELIGIBLE.items():
        if not eligible or pattern_id in covered:
            continue
        gaps.append({
            "pattern_id": pattern_id,
            "section_id": sections_mod.section_of(pattern_id),
            "capability_tags": BUG_PATTERNS[pattern_id]["capability_tags"],
            "description": BUG_PATTERNS[pattern_id]["description"],
        })
    return gaps


def _example_tasks(pattern_id: str) -> dict:
    """The known_example/variant buggy_source for this pattern, straight
    from TASK_TEMPLATES -- these are hand-written by a human (bug_catalog.py),
    this function doesn't invent example code, only looks it up."""
    tasks_by_id = {t.task_id: t for t in generate_tasks(seed=42)}
    examples = {}
    for pid, problem_id, role, buggy_source in TASK_TEMPLATES:
        if pid != pattern_id or role not in ("known_example", "variant"):
            continue
        task_id = f"{pid}__{problem_id}__{role}"
        examples[role] = tasks_by_id[task_id]
    return examples


def check_related(pattern_id: str, draft_procedure_text: str, adapter=None) -> list[dict]:
    """Step 4/5: compare the draft against every Book in the SAME section
    (Phase 2's "potentially relevant" scope). Returns classify_pair results
    -- this function only reports, it never blocks generation; a DUPLICATE
    finding here is meant for a human to read before deciding whether to
    LINK instead (spec #9), same as Phase 2/3's policy everywhere else."""
    adapter = adapter or build_adapter("small")
    section_id = sections_mod.section_of(pattern_id)
    section_patterns = [p for p in sections_mod.patterns_in_section(section_id) if p != pattern_id]
    latest_by_pattern = {b.pattern_id: b for b in _latest_per_pattern(load_books())}

    draft_book = Book(
        id=f"draft_{pattern_id}", version=0, title=f"Draft: {pattern_id}", domain="programming",
        problem_tags=[], capability_tags=BUG_PATTERNS[pattern_id]["capability_tags"],
        resource_tags=["python"], procedure_text=draft_procedure_text, pattern_id=pattern_id,
        canonical_problem_id="", status="DRAFT", confidence=0.0, verification_count=0, verification_types=[],
    )
    results = []
    for other_pattern in section_patterns:
        other_book = latest_by_pattern.get(other_pattern)
        if other_book is None:
            continue
        results.append(classify_pair(draft_book, other_book, adapter))
    return results


def generate_candidate(pattern_id: str, adapter=None) -> str:
    adapter = adapter or build_adapter("expert")
    examples = _example_tasks(pattern_id)
    known = examples.get("known_example")
    if known is None:
        raise ValueError(f"no known_example task found for pattern {pattern_id!r}")

    from ..domain.bug_catalog import BASE_PROBLEMS
    correct_source = BASE_PROBLEMS[known.problem_id]["correct_source"]
    prompt = (
        f"Bug pattern: {pattern_id}\n"
        f"Description: {BUG_PATTERNS[pattern_id]['description']}\n\n"
        f"Worked example -- buggy version:\n```python\n{known.buggy_source}\n```\n\n"
        f"Worked example -- corrected version:\n```python\n{correct_source}\n```"
    )
    # 2048, not 1024: the first real run (2026-08-18) truncated mid-sentence
    # at 1024 for a candidate that still passed verification -- worked by
    # luck, not by design. Matches the same lesson worker.py's
    # MAX_OUTPUT_TOKENS already learned for reasoning-heavy models.
    result = adapter.complete(prompt=prompt, system=_GENERATION_SYSTEM_PROMPT, max_tokens=2048)
    return result.text.strip()


def verify_candidate(pattern_id: str, procedure_text: str, adapter=None) -> dict:
    """Step 7: real pytest verification, on the known_example AND variant
    task for this pattern (both exist in TASK_TEMPLATES already) -- the same
    two roles a Book for this pattern would eventually make KNOWN/VARIANT
    once it exists. Uses the Small adapter + the same build_prompt/
    extract_code path every other quest in this repo uses, not a special
    generator-only path, so "verified" means the same thing here as
    everywhere else in the system."""
    adapter = adapter or build_adapter("small")
    examples = _example_tasks(pattern_id)
    package = SkillPackage(books=[Book(
        id=f"draft_{pattern_id}", version=0, title=pattern_id, domain="programming",
        problem_tags=[], capability_tags=BUG_PATTERNS[pattern_id]["capability_tags"],
        resource_tags=["python"], procedure_text=procedure_text, pattern_id=pattern_id,
        canonical_problem_id="", status="DRAFT", confidence=0.0, verification_count=0, verification_types=[],
    )])

    per_role = {}
    for role, task in examples.items():
        prompt = build_prompt(task, package)
        result = adapter.complete(prompt=prompt, system=SYSTEM_PROMPT, max_tokens=4096)
        candidate_source = extract_code(result.text)
        verification = run_tests(candidate_source, task.test_source)
        per_role[role] = verification.passed

    n_passed = sum(1 for p in per_role.values() if p)
    return {"per_role": per_role, "n_passed": n_passed, "n_total": len(per_role), "gate_passed": n_passed == len(per_role) and len(per_role) > 0}


def save_generated_book(pattern_id: str, procedure_text: str, output_dir: Path | None = None) -> Path:
    examples = _example_tasks(pattern_id)
    known = examples["known_example"]
    data = {
        "id": f"book_{pattern_id}",
        "version": 1,
        "title": f"Fixing {pattern_id.replace('_', ' ')} bugs",
        "domain": "programming",
        "problem_tags": ["wrong-output", "runtime-bug"],
        "capability_tags": BUG_PATTERNS[pattern_id]["capability_tags"],
        "resource_tags": ["python"],
        "pattern_id": pattern_id,
        "canonical_problem_id": known.problem_id,
        "status": "VERIFIED",
        "confidence": 1.0,
        "verification_count": 1,
        "verification_types": ["skill_generator_initial_verification"],
        "procedure_text": procedure_text,
        "generation_method": "skill_generator",
    }
    out_path = (output_dir or config.LIBRARY_DIR) / f"book_{pattern_id}.yaml"
    out_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out_path


def generate_for_gap(gap: dict) -> dict:
    """Runs steps 4-10 for one gap. Returns a result dict; never raises on a
    failed verification -- that's an expected, reportable outcome (spec #6:
    "se fallisce, NON entra"), not an error."""
    pattern_id = gap["pattern_id"]
    if not sections_mod.GENERATION_ELIGIBLE.get(pattern_id, False):
        raise ValueError(f"{pattern_id!r} is not GENERATION_ELIGIBLE -- refusing to generate a skill for it")

    procedure_text = generate_candidate(pattern_id)
    related = check_related(pattern_id, procedure_text)
    verification = verify_candidate(pattern_id, procedure_text)

    saved_path = None
    if verification["gate_passed"]:
        saved_path = save_generated_book(pattern_id, procedure_text)

    return {
        "pattern_id": pattern_id, "procedure_text": procedure_text,
        "related": related, "verification": verification,
        "saved_path": str(saved_path) if saved_path else None,
    }


if __name__ == "__main__":
    gaps = find_gaps()
    if not gaps:
        print("[skill_generator] nessun gap legittimo trovato (tutti i pattern eligible sono gia' coperti).")
        sys.exit(0)

    print(f"[skill_generator] {len(gaps)} gap trovati: {[g['pattern_id'] for g in gaps]}")
    for gap in gaps:
        pattern_id = gap["pattern_id"]
        print(f"\n[skill_generator] {pattern_id} (sezione {gap['section_id']}) -- genero candidato...")
        result = generate_for_gap(gap)

        if result["related"]:
            print("[skill_generator]   confronto con skill correlate nella stessa sezione:")
            for r in result["related"]:
                print(f"    {r['book_a']} <-> {r['book_b']}: {r['label']} -- {r['reasoning']}")
        else:
            print("[skill_generator]   nessun'altra skill nella stessa sezione da confrontare.")

        v = result["verification"]
        print(f"[skill_generator]   verifica: {v['n_passed']}/{v['n_total']} ({v['per_role']})")
        if result["saved_path"]:
            print(f"[skill_generator]   ACCETTATA -> {result['saved_path']}")
        else:
            print("[skill_generator]   RESPINTA -- non aggiunta alla libreria.")
