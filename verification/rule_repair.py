"""Repair for a RULE-based skill flagged by rule_generalization.py as
ANTI_PATTERN (a literal example recited verbatim in a deliberately different
situation) or DOES_NOT_GENERALIZE (the judge found the two contrasting
responses did not diverge the way the rule's own stated direction requires).

Sibling of skill_repair.py (slot-based) and method_repair.py (method-based)
-- same non-destructive versioning, same prior_feedback/reuse_candidate_text
shape, same content/concreteness gates, so inspector.py's run_repair_loop
and judge_repair_result work with this UNCHANGED (both read fields by name/
getattr, not by isinstance) -- this file's whole job is producing a result
object shaped like RepairResult/MethodRepairResult, not adding new Inspector
logic. Built 2026-09-18 after a real gap found live: the comprehensive
pattern-risk-batch test found TWO real ANTI_PATTERN/DOES_NOT_GENERALIZE
verdicts (floating_point_equality's currency tier hardcoding 0.01 regardless
of a currency's actual subunit precision -- wrong for JPY/KWD;
key_error_missing_dict_check defaulting to 1 instead of the additive
identity 0) with NO existing repair path for that axis at all."""

from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from .. import config
from ..adapters.base import ModelAdapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..domain.verifier import run_tests
from ..models import Book, SkillPackage
from .holdout import get_known_task
from .rule_generalization import AggregatedGeneralizationResult, RuleSpec, run_rule_generalization_checks
from .stabilizer import check_concreteness_preserved, check_content_preserved


@dataclass
class RuleRepairResult:
    accepted: bool
    reason: str
    original_verdict: str
    candidate_verdict: str | None = None
    candidate_text: str | None = None
    holdout_passed: bool | None = None
    saved_path: str | None = None
    content_check_label: str | None = None
    verification_inconclusive: bool = False


_REPAIR_SYSTEM_PROMPT = (
    "You edit a procedure (a 'skill') written for an economical language model to "
    "follow. Evidence shows this procedure's rule does not actually generalize the "
    "way it claims to: the model either recites the rule's own illustrative literal "
    "verbatim in a deliberately different situation, or produces a response that "
    "does not diverge the way the rule's stated direction requires.\n\n"
    "A NAIVE fix ('state the rule more emphatically', 'add another example') often "
    "does NOT work -- the underlying problem is usually that the rule's existing "
    "tiers/conditions do not actually COVER the case that broke it (a new sub-case "
    "hiding inside what looked like one case). DECOMPOSE the failing tier further, "
    "following the same shape already used elsewhere in this project: name a "
    "SPECIFIC, OBSERVABLE signal that distinguishes the sub-case that broke it "
    "(e.g. not just 'a currency amount' but 'a currency amount, where the exact "
    "subunit precision depends on WHICH currency -- most use 2 decimal places, but "
    "not all do'), give a DIRECT mechanical mapping from that signal to the correct "
    "value/derivation for that sub-case, and state a conservative fallback for when "
    "the signal cannot be determined.\n\n"
    "Before writing your final answer, silently (in your own reasoning, never in "
    "the visible output) list every numbered step/instruction in the original "
    "procedure OTHER than the one you are fixing, and for each one confirm it "
    "still appears in your rewritten version, in substance and in the same "
    "relative position -- if any is missing, add it back before finalizing.\n\n"
    "Your visible output must contain ONLY the full rewritten procedure text -- "
    "no preamble, no code fences, no meta-commentary about your own process, and "
    "not one word of the checklist above."
)


def _build_repair_prompt(book: Book, rule: RuleSpec, original: AggregatedGeneralizationResult, prior_feedback: str | None = None) -> str:
    example = original.example
    if example is not None and example.anti_pattern_triggered:
        evidence = (
            f"The rule's own illustrative literal ({rule.literal_to_avoid!r}) was recited verbatim in a "
            f"deliberately different situation (expected direction: {example.direction!r}):\n"
            f"Response A:\n{example.code_a}\n\nResponse B:\n{example.code_b}"
        )
    elif example is not None:
        evidence = (
            f"The two contrasting responses did not diverge the way the rule's stated direction "
            f"({example.direction!r}) requires -- judge's reasoning: {example.judge_reason}\n\n"
            f"Response A:\n{example.code_a}\n\nResponse B:\n{example.code_b}"
        )
    else:
        evidence = "no conclusive example available."
    feedback_block = f"\n\nPrevious attempt was REJECTED for this specific reason -- do not repeat it: {prior_feedback}\n" if prior_feedback else ""
    return (
        f"Procedure (rule: {rule.rule!r}):\n\n{book.procedure_text}\n\n"
        f"Evidence of failure to generalize (executed, not hypothetical; {original.n_does_not_generalize} of "
        f"{original.n_trials} independent trials failed this way, {original.n_anti_pattern} triggered the literal "
        f"anti-pattern directly):\n{evidence}{feedback_block}\n\n"
        "Decompose the failing tier into a concrete, checkable sub-case as instructed, do not just restate the "
        "rule more strongly."
    )


def repair_rule_skill(
    experiment_id: str,
    book: Book,
    rule: RuleSpec,
    original: AggregatedGeneralizationResult,
    repair_adapter: ModelAdapter,
    ablation_adapter: ModelAdapter,
    output_dir: Path | None = None,
    prior_feedback: str | None = None,
    reuse_candidate_text: str | None = None,
) -> RuleRepairResult:
    """repair_adapter is the Expert (rewrites + judges the re-verification,
    same role split as skill_repair.py/method_repair.py); ablation_adapter is
    the model under test (generates the contrasting responses). `original`
    is the MAJORITY-AGGREGATED verdict across multiple independent trials
    (run_rule_generalization_checks), not a single sample -- a single
    contrasting-scenario pair was found live to flip verdict across
    separate runs on the SAME unchanged book, exactly the instability
    voting fixes everywhere else in this package."""
    holdout_task = get_known_task(book.pattern_id)
    if holdout_task is None:
        return RuleRepairResult(
            accepted=False, reason="nessun task KNOWN reale nel catalogo per questo pattern -- impossibile un holdout affidabile",
            original_verdict=original.verdict,
        )

    if reuse_candidate_text is not None:
        candidate_text = reuse_candidate_text
    else:
        prompt = _build_repair_prompt(book, rule, original, prior_feedback)
        completion = repair_adapter.complete(prompt=prompt, system=_REPAIR_SYSTEM_PROMPT, max_tokens=4096)
        candidate_text = completion.text.strip()
        if not candidate_text:
            return RuleRepairResult(accepted=False, reason="riscrittura vuota", original_verdict=original.verdict)

    candidate_book = Book(**{**asdict(book), "procedure_text": candidate_text})

    package = SkillPackage(books=[candidate_book], coverage="FULL")
    holdout_prompt = build_prompt(holdout_task, package)
    holdout_completion = ablation_adapter.complete(prompt=holdout_prompt, system=SYSTEM_PROMPT, max_tokens=4096)
    holdout_code = extract_code(holdout_completion.text)
    holdout_result = run_tests(holdout_code, holdout_task.test_source)
    if not holdout_result.passed:
        return RuleRepairResult(
            accepted=False, reason=f"il candidato non supera piu' il task KNOWN reale ({holdout_task.task_id}): {holdout_result.error}",
            original_verdict=original.verdict, candidate_text=candidate_text, holdout_passed=False,
        )

    candidate_result = run_rule_generalization_checks(experiment_id, candidate_book, rule, repair_adapter, ablation_adapter)
    if candidate_result is None:
        return RuleRepairResult(
            accepted=False, reason="impossibile rigenerare scenari contrastanti per la riverifica del candidato",
            original_verdict=original.verdict, candidate_text=candidate_text, holdout_passed=True,
            verification_inconclusive=True,
        )
    if candidate_result.verdict != "GENERALIZES":
        detail = candidate_result.example.judge_reason if candidate_result.example else "letterale ancora ripetuto"
        return RuleRepairResult(
            accepted=False,
            reason=f"il candidato non generalizza ancora correttamente ({candidate_result.verdict}, "
                   f"{candidate_result.n_generalizes}/{candidate_result.n_trials} trial ok): {detail}",
            original_verdict=original.verdict, candidate_verdict=candidate_result.verdict,
            candidate_text=candidate_text, holdout_passed=True,
        )

    content_check = check_content_preserved(book.procedure_text, candidate_text, repair_adapter)
    concreteness_check = check_concreteness_preserved(book.procedure_text, candidate_text, repair_adapter)
    if content_check["label"] != "PRESERVED" or concreteness_check["label"] != "PRESERVED":
        failing = content_check if content_check["label"] != "PRESERVED" else concreteness_check
        return RuleRepairResult(
            accepted=False,
            reason=f"generalizza correttamente ma contenuto non preservato: {failing['label']} -- {failing['reasoning']}",
            original_verdict=original.verdict, candidate_verdict=candidate_result.verdict,
            candidate_text=candidate_text, holdout_passed=True, content_check_label=failing["label"],
        )

    saved_path = _save_repaired_book(book, candidate_text, output_dir)
    return RuleRepairResult(
        accepted=True,
        reason=f"{original.verdict} -> GENERALIZES, holdout {holdout_task.task_id} superato, contenuto preservato",
        original_verdict=original.verdict, candidate_verdict=candidate_result.verdict,
        candidate_text=candidate_text, holdout_passed=True, saved_path=str(saved_path),
        content_check_label=content_check["label"],
    )


def _save_repaired_book(book: Book, repaired_text: str, output_dir: Path | None = None) -> Path:
    new_id = f"{book.id}_v{book.version + 1}"
    data = {
        "id": new_id,
        "version": book.version + 1,
        "title": f"{book.title} (rule-repaired)",
        "domain": book.domain,
        "problem_tags": book.problem_tags,
        "capability_tags": book.capability_tags,
        "resource_tags": book.resource_tags,
        "pattern_id": book.pattern_id,
        "canonical_problem_id": book.canonical_problem_id,
        "status": "VERIFIED",
        "confidence": book.confidence,
        "verification_count": book.verification_count + 1,
        "verification_types": list(book.verification_types) + ["rule_repair_reverify"],
        "procedure_text": repaired_text,
        "derived_from": book.id,
        "generation_method": "rule_repair",
    }
    out_dir = output_dir or config.LIBRARY_DIR
    out_path = out_dir / f"{new_id}.yaml"
    out_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out_path
