"""Detective: generates a verified hypothesis about WHICH CASE of a skill's
own multi-case decision rule applies to one specific task -- the piece a
small model needs, and (per this whole session's findings) does not
spontaneously supply, before it can apply a tiered rule like floating_point_
equality's "explicit value > known domain convention > conservative
fallback" correctly to a NEW, unseen task instead of copying whichever
example it happened to see.

Design history (2026-09-18): the user's own proposal was a Detective that
finds hints about "what type of problem this is." First implementation used
a fixed checklist of 4 clue types (named concept / symptom type / branching
presence / domain convention) -- the user correctly rejected this as the
same mistake as a hardcoded keyword list, just one level up: not genuinely
generic, and liable to miss whatever a future skill's real distinguishing
signal turns out to be.

This version is generic across ANY skill with a multi-case rule, via the
SAME index-then-solve-each decomposition already validated live this
session for calculate_median (index the cases, solve each independently,
merge) and reused again in skill_conflict.py (index the task's own cases
before comparing two skills):

  1. Extract the DISTINCT CASES from the skill's own decision rule
     MECHANICALLY (a listing task, like slot_identifier's
     _EXTRACT_LITERALS_SYSTEM_PROMPT -- not a judgment call).
  2. For EACH case, generate the SPECIFIC QUESTION whose answer would
     confirm or rule out that case for THIS task -- open-ended per case,
     never drawn from a fixed list of question/clue types. A skill with
     different cases gets different questions, generated fresh every time;
     nothing here names "check for a percentage" or "check for a named
     domain" in advance.
  3. Answer each question using ONLY the task's own text (buggy_source,
     docstring, test_source) -- a VERBATIM quote from the task is required
     as evidence, or that case gets no support. Same fail-closed evidence
     bar as every other identify_*/extract_* function in this package.
  4. Exactly ONE case with real supporting evidence -> that is the
     hypothesis. Zero or more-than-one supported case -> INCONCLUSIVE, not
     an arbitrary pick -- ambiguity is a real, reportable outcome.
  5. Voted across samples (stabilizer.vote_for_result) for the same
     holistic-judgment stability reason as every identify_*/extract_*
     function elsewhere in this package.

What this is NOT: a repair mechanism. Detective does not rewrite the skill
or the task -- it produces a HYPOTHESIS (which case, backed by which real
quote) meant to be handed to the Worker as extra context, the same role
skill_conflict.py's COMPOUND annotation plays. Like skill_conflict.py, this
is deliberately NOT wired into quest_runner.py's real pipeline yet -- it
needs its own broad, real A/B/F/C-style validation of net effect before
being trusted as an always-on addition, exactly the lesson `general_case_
completeness` taught the hard way."""

import json
import re
from dataclasses import dataclass

from ..adapters.base import ModelAdapter
from ..models import Book, Task
from .stabilizer import vote_for_result

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class DetectiveHypothesis:
    book_id: str
    task_id: str
    cases: list[str]
    case_questions: dict[str, str]
    supported_case: str | None  # None means INCONCLUSIVE
    evidence_quote: str | None
    all_verdicts: dict[str, str | None]  # case -> evidence quote or None (transparency/logging)
    status: str  # RESOLVED | INCONCLUSIVE


_EXTRACT_CASES_SYSTEM_PROMPT = (
    "You are given a procedure ('skill') that describes a MULTI-CASE decision "
    "rule -- a rule that tells a reader to pick between two or more different "
    "cases/tiers/branches depending on the situation (e.g. 'if X, do A; else "
    "if Y, do B; else do C'). List each distinct case EXACTLY as it is "
    "described, in the order given. This is a MECHANICAL LISTING task, not a "
    "judgment call about which case applies to anything -- just enumerate the "
    "cases the rule itself defines.\n\n"
    "If the procedure has no such multi-case rule (a single, unconditional "
    "instruction), return an empty list.\n\n"
    "Return ONLY a JSON array of short strings, one per case, e.g. "
    '["an explicit tolerance is stated in the problem", "a known domain '
    'convention applies", "neither applies"]. Empty array [] if there is no '
    "multi-case rule."
)

_GENERATE_QUESTION_SYSTEM_PROMPT = (
    "You are given a procedure's multi-case decision rule and ONE specific "
    "case from it. Write the single most concrete, specific question whose "
    "answer -- if you could inspect a NEW, unrelated task -- would tell you "
    "whether THIS case applies to that task or not. The question must be "
    "answerable by pointing at concrete text in the task (a stated number, a "
    "named domain, a specific phrase), not by opinion or by re-reading the "
    "rule itself.\n\n"
    'Return ONLY JSON: {"question": "..."}'
)

_ANSWER_QUESTION_SYSTEM_PROMPT = (
    "You are given a specific task (its buggy source code, docstring, and "
    "test suite) and ONE yes/no question about it. Answer the question ONLY "
    "using what is actually stated in the task's own text. If your answer is "
    "yes, quote the EXACT substring from the task's text that supports it, "
    "copyable verbatim. If the task's text does not actually say anything "
    "that answers the question, answer no -- do not infer, assume, or guess "
    "from general knowledge of the domain.\n\n"
    'Return ONLY JSON: {"answer": true|false, "evidence_quote": "exact '
    'verbatim substring from the task" or null}'
)


def _task_text(task: Task) -> str:
    return f"{task.buggy_source}\n\n# Tests:\n{task.test_source}"


def _extract_cases(book: Book, adapter: ModelAdapter) -> list[str]:
    prompt = f"Procedure text (pattern: {book.pattern_id!r}):\n\n{book.procedure_text}"
    completion = adapter.complete(prompt=prompt, system=_EXTRACT_CASES_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
    match = re.search(r"\[.*\]", completion.text, re.DOTALL)
    if not match:
        return []
    try:
        cases = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [c for c in cases if isinstance(c, str) and c.strip()]


def _generate_question(book: Book, case: str, adapter: ModelAdapter) -> str | None:
    prompt = f"Procedure's decision rule:\n\n{book.procedure_text}\n\nSpecific case: {case!r}"
    completion = adapter.complete(prompt=prompt, system=_GENERATE_QUESTION_SYSTEM_PROMPT, max_tokens=512, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    question = data.get("question")
    return question if isinstance(question, str) and question.strip() else None


def _answer_question(task: Task, question: str, adapter: ModelAdapter) -> str | None:
    """Returns the verbatim evidence quote if the question is answered YES
    with real, checkable support -- None otherwise (no, or unparseable, or a
    hallucinated quote not actually in the task's text)."""
    prompt = f"Task:\n\n{_task_text(task)}\n\nQuestion: {question}"
    completion = adapter.complete(prompt=prompt, system=_ANSWER_QUESTION_SYSTEM_PROMPT, max_tokens=512, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if data.get("answer") is not True:
        return None
    quote = data.get("evidence_quote")
    if not isinstance(quote, str) or not quote.strip():
        return None
    task_text = _task_text(task)
    if quote not in task_text:
        # Citazione allucinata -- non recuperabile, stesso principio
        # verbatim di ogni altro identify_*/extract_* in questo package.
        return None
    return quote


def _investigate_once(book: Book, task: Task, cases: list[str], case_questions: dict[str, str], adapter: ModelAdapter) -> dict:
    all_verdicts: dict[str, str | None] = {}
    for case in cases:
        question = case_questions.get(case)
        if question is None:
            all_verdicts[case] = None
            continue
        all_verdicts[case] = _answer_question(task, question, adapter)
    supported = [c for c, q in all_verdicts.items() if q is not None]
    if len(supported) == 1:
        return {"status": "RESOLVED", "supported_case": supported[0], "evidence_quote": all_verdicts[supported[0]], "all_verdicts": all_verdicts}
    return {"status": "INCONCLUSIVE", "supported_case": None, "evidence_quote": None, "all_verdicts": all_verdicts}


def investigate(book: Book, task: Task, adapter: ModelAdapter, n_samples: int = 3) -> DetectiveHypothesis | None:
    """None means the skill has no multi-case rule to investigate at all
    (extract_cases found nothing) -- a caller should not treat this the same
    as INCONCLUSIVE (a real rule whose applicable case could not be
    determined for this task): NONE means there was nothing to investigate,
    INCONCLUSIVE means investigation genuinely could not resolve it."""
    cases = _extract_cases(book, adapter)
    if len(cases) < 2:
        return None
    case_questions = {case: _generate_question(book, case, adapter) for case in cases}
    if not any(q is not None for q in case_questions.values()):
        return None

    voted = vote_for_result(
        identify_fn=lambda: _investigate_once(book, task, cases, case_questions, adapter),
        key_fn=lambda r: r["supported_case"] or "__INCONCLUSIVE__",
        n_samples=n_samples,
    )
    if voted is None:
        return DetectiveHypothesis(
            book_id=book.id, task_id=task.task_id, cases=cases, case_questions=case_questions,
            supported_case=None, evidence_quote=None, all_verdicts={}, status="INCONCLUSIVE",
        )
    return DetectiveHypothesis(
        book_id=book.id, task_id=task.task_id, cases=cases, case_questions=case_questions,
        supported_case=voted["supported_case"], evidence_quote=voted["evidence_quote"],
        all_verdicts=voted["all_verdicts"], status=voted["status"],
    )
