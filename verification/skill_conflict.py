"""Detects whether two Books retrieved together for the SAME task prescribe
genuinely incompatible actions, and -- the distinction that matters most --
tells that apart from a task that legitimately needs BOTH instructions for
DIFFERENT cases/steps (2026-09-18, user-raised: "un conflitto potrebbe anche
essere richiesto, tipo fammi A ma fammi anche B che è la negazione di A").

A naive "do these two skills disagree?" judge would flag that second
situation as a bug when it is not one -- the task has two distinct
cases/steps, each skill is correct for its own case, and the right action is
to apply both (in sequence, or one per case), not to pick a winner. So the
classification is not binary. It reuses the SAME decomposition principle
already validated live this session for calculate_median (index the cases,
solve each, merge) applied here to relating two skills instead of solving a
single problem:

  1. Index the distinct cases/situations the TASK's own test suite actually
     exercises (a task can legitimately require different actions for
     different cases in the same function).
  2. For each skill, identify its concrete instruction (verbatim quote) and
     which case(s) it applies to.
  3. Classify the relationship as exactly one of:
       INDEPENDENT   -- unrelated aspects, no interaction.
       COMPOUND       -- apply to DIFFERENT cases/steps of the same task;
                         both are correct, used in sequence or per-case
                         (covers "do A here, do A's negation there").
       REAL_CONFLICT  -- apply to the EXACT SAME case and disagree there;
                         only one can be correct.
       INCONCLUSIVE   -- cannot tell from the given text.
  4. Any REAL_CONFLICT candidate must survive an adversarial "try to
     reconcile this as COMPOUND instead" check before being accepted as
     real -- same devil's-advocate idiom as stabilizer.survives_adversarial_
     check, applied here against the more alarming label instead of a
     single fact, because a false REAL_CONFLICT is the failure mode with
     the worse blast radius (it would tell the Worker two correct
     instructions are broken).
  5. The whole classification is stabilized with stabilizer.vote_for_result
     (same self-consistency fix built earlier today for slot/rule/method
     identification) -- a holistic "how do these two relate" judgment is
     exactly the kind of call that has been unstable everywhere else in
     this package.

Deliberately NOT wired into quest_runner.py by default. Same lesson as
librarian.ALWAYS_INCLUDED_PATTERN_IDS: a mechanism that sounds obviously
useful must be validated on real, broad data (does it change worker output
for the better, does it have real precision -- few false REAL_CONFLICTs on
genuinely unrelated/compound real skill pairs) before being trusted as an
always-on addition, not wired in on the strength of a good design
conversation alone."""

import json
import re
from dataclasses import dataclass

from ..adapters.base import ModelAdapter
from ..models import Book, SkillPackage, Task
from .stabilizer import vote_for_result

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

VALID_RELATIONSHIPS = {"INDEPENDENT", "COMPOUND", "REAL_CONFLICT", "INCONCLUSIVE"}


@dataclass
class ConflictReport:
    book_a_id: str
    book_b_id: str
    task_id: str
    relationship: str  # INDEPENDENT | COMPOUND | REAL_CONFLICT | INCONCLUSIVE
    cases: list[str]
    quote_a: str
    quote_b: str
    applies_to_a: list[str]
    applies_to_b: list[str]
    reasoning: str
    reconciled: bool = False  # True if a REAL_CONFLICT was downgraded to COMPOUND by the adversarial check


_CLASSIFY_RELATIONSHIP_SYSTEM_PROMPT = (
    "You are given ONE task (its buggy source and test suite) and TWO "
    "debugging procedures ('skills') both retrieved as potentially relevant "
    "to it. First, index the distinct cases/situations this task's test "
    "suite actually exercises -- a single function can legitimately need "
    "different actions for different cases. For EACH skill, quote its "
    "concrete instruction VERBATIM from that skill's own text, and state "
    "which case(s) above it applies to. Then classify the relationship "
    "between the two skills for THIS specific task as exactly one of:\n"
    "- INDEPENDENT: they concern unrelated aspects, no real interaction.\n"
    "- COMPOUND: they apply to DIFFERENT cases/steps of the SAME task -- "
    "both are correct, meant to be applied in sequence or one per case. "
    "This includes a skill and something that reads like its negation, when "
    "the task genuinely has two different situations, one needing each.\n"
    "- REAL_CONFLICT: they apply to the EXACT SAME case/situation and give "
    "mutually exclusive instructions for it -- only one can be correct "
    "there.\n"
    "- INCONCLUSIVE: cannot determine this from the given text.\n\n"
    "Return ONLY a single JSON object, no prose, no markdown fences: "
    '{"cases": ["case description", ...], "skill_a_quote": "verbatim quote '
    'from skill A", "applies_to_a": ["case description(s)"], "skill_b_quote": '
    '"verbatim quote from skill B", "applies_to_b": ["case description(s)"], '
    '"relationship": "INDEPENDENT|COMPOUND|REAL_CONFLICT|INCONCLUSIVE", '
    '"reasoning": "one sentence"}\n'
    "The two quote fields must be copyable verbatim from each skill's own "
    "text -- do not paraphrase."
)

_RECONCILE_SYSTEM_PROMPT = (
    "You previously classified two skills as REAL_CONFLICT for a specific "
    "task -- meaning you believe they truly cannot both be correct for the "
    "same case. Now argue AGAINST your own conclusion: try hard to "
    "construct a plausible reading where the task actually has two "
    "distinct cases/steps, one that needs each skill's instruction, making "
    "this COMPOUND instead of a genuine conflict. If you can construct such "
    "a reading, describe it concretely (which case needs which "
    "instruction). If you honestly cannot find one, say so.\n\n"
    'Return ONLY JSON: {"reconciling_reading": "description of the two '
    'cases" or null}'
)


def _task_context(task: Task) -> str:
    return f"Buggy function:\n```python\n{task.buggy_source}\n```\n\nTest suite:\n```python\n{task.test_source}\n```"


def _classify_once(book_a: Book, book_b: Book, task: Task, adapter: ModelAdapter) -> dict | None:
    prompt = (
        f"{_task_context(task)}\n\n"
        f"Skill A ({book_a.id}):\n{book_a.procedure_text.strip()}\n\n"
        f"Skill B ({book_b.id}):\n{book_b.procedure_text.strip()}"
    )
    completion = adapter.complete(prompt=prompt, system=_CLASSIFY_RELATIONSHIP_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    relationship = data.get("relationship")
    if relationship not in VALID_RELATIONSHIPS:
        return None
    quote_a = data.get("skill_a_quote")
    quote_b = data.get("skill_b_quote")
    if relationship in ("COMPOUND", "REAL_CONFLICT"):
        # Le citazioni verbatim sono l'unica prova mecc anica che il modello
        # non si sia inventato un'istruzione mai scritta nella skill --
        # stesso principio del controllo verbatim di slot_identifier.py.
        if not isinstance(quote_a, str) or quote_a not in book_a.procedure_text:
            return None
        if not isinstance(quote_b, str) or quote_b not in book_b.procedure_text:
            return None
    return {
        "cases": [c for c in (data.get("cases") or []) if isinstance(c, str)],
        "quote_a": quote_a or "",
        "quote_b": quote_b or "",
        "applies_to_a": [c for c in (data.get("applies_to_a") or []) if isinstance(c, str)],
        "applies_to_b": [c for c in (data.get("applies_to_b") or []) if isinstance(c, str)],
        "relationship": relationship,
        "reasoning": str(data.get("reasoning") or ""),
    }


def _survives_reconciliation_check(book_a: Book, book_b: Book, task: Task, classification: dict, adapter: ModelAdapter) -> bool:
    """Returns True if the REAL_CONFLICT claim survives (no plausible
    COMPOUND reading found) -- False means it should be downgraded. Mirrors
    stabilizer.survives_adversarial_check's fail-closed shape: an
    unparseable or missing response means the check could not find a
    reconciliation, so the conflict claim survives (True), never the
    opposite."""
    prompt = (
        f"{_task_context(task)}\n\n"
        f"Skill A ({book_a.id}):\n{book_a.procedure_text.strip()}\n\n"
        f"Skill B ({book_b.id}):\n{book_b.procedure_text.strip()}\n\n"
        f"Your classification: REAL_CONFLICT -- {classification['reasoning']}"
    )
    completion = adapter.complete(prompt=prompt, system=_RECONCILE_SYSTEM_PROMPT, max_tokens=512, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return True
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return True
    reading = data.get("reconciling_reading")
    if not isinstance(reading, str) or not reading.strip():
        return True
    return False


def check_conflict(book_a: Book, book_b: Book, task: Task, adapter: ModelAdapter, n_samples: int = 3) -> ConflictReport | None:
    """None means INCONCLUSIVE/unparseable on the majority of samples --
    fail closed, same as every other identify_* in this package: a caller
    must not treat 'could not classify' as 'no conflict'."""

    def _once() -> dict | None:
        result = _classify_once(book_a, book_b, task, adapter)
        if result is None:
            return None
        if result["relationship"] == "REAL_CONFLICT":
            if not _survives_reconciliation_check(book_a, book_b, task, result, adapter):
                result = {**result, "relationship": "COMPOUND", "reconciled": True}
        return result

    voted = vote_for_result(identify_fn=_once, key_fn=lambda r: r["relationship"], n_samples=n_samples)
    if voted is None:
        return None
    return ConflictReport(
        book_a_id=book_a.id,
        book_b_id=book_b.id,
        task_id=task.task_id,
        relationship=voted["relationship"],
        cases=voted["cases"],
        quote_a=voted["quote_a"],
        quote_b=voted["quote_b"],
        applies_to_a=voted["applies_to_a"],
        applies_to_b=voted["applies_to_b"],
        reasoning=voted["reasoning"],
        reconciled=voted.get("reconciled", False),
    )


def check_package_conflicts(package: SkillPackage, task: Task, adapter: ModelAdapter, n_samples: int = 3) -> list[ConflictReport]:
    """Pairwise over every book actually present together in this
    SkillPackage for this task -- with librarian.route()'s default
    max_books=2 this is at most one pair, but written for any size so it
    still works if that cap is ever raised."""
    reports = []
    books = package.books
    for i in range(len(books)):
        for j in range(i + 1, len(books)):
            report = check_conflict(books[i], books[j], task, adapter, n_samples=n_samples)
            if report is not None and report.relationship != "INDEPENDENT":
                reports.append(report)
    return reports
