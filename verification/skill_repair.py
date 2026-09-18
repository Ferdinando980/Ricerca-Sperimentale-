"""Automated repair for a skill flagged as high mechanical-substitution risk
by substitution_ablation.py. Generates a rewrite guided by the same principle
that fixed floating_point_equality by hand (name the case explicitly / require
derivation from context instead of offering a literal, substitutable
constant -- the same text that became seed_skill_authoring_explicit_cases in
Aria), then re-verifies with BOTH:

  1. The SAME ablation test (substitution_ablation.run_substitution_ablation)
     on the candidate -- accepted only if tracking drops meaningfully.
  2. The existing holdout machinery, reused as-is
     (domain/verifier.run_tests against a known-good task the skill must
     keep passing) -- a repair that stops the substitution but also breaks
     a case the skill already handled correctly is not an improvement.

Never overwrites the original -- same non-destructive Book-versioning
pattern as librarian/optimizer.py (new "{id}_v{n+1}.yaml", derived_from,
generation_method distinct from "compression" so the two are never confused
in the library's genealogy)."""

from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from .. import config
from ..adapters.base import ModelAdapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..domain.verifier import run_tests
from ..models import Book, SkillPackage, Task
from typing import Callable

from .stabilizer import check_concreteness_preserved, check_content_preserved
from .substitution_ablation import AblationResult, ValueExtractor, run_substitution_ablation

# (base_procedure_text, variant_label) -> new_procedure_text -- applies the
# SAME kind of manipulation the original ablation used, but as a reusable
# function instead of a pre-baked dict of strings, so it can be re-applied to
# a REWRITTEN candidate's own text, not just the original's.
SlotTransform = Callable[[str, str], str]

# Minimum drop in tracking ratio (original - candidate) to count the repair
# as having actually reduced mechanical substitution, not just noise between
# two small samples. Loosely modeled on optimizer.py's _MIN_ACCEPT_RATIO
# (0.8) but inverted in spirit: here we want the RISK score to fall, not a
# pass-rate to stay high.
_MIN_TRACKING_DROP = 0.25

_REPAIR_SYSTEM_PROMPT = (
    "You edit a procedure (a 'skill') written for an economical language model to "
    "follow. Evidence shows this procedure has a designated slot that the model "
    "substitutes MECHANICALLY -- it reproduces whatever literal value/example is "
    "written there, verbatim, instead of deriving an answer from the specific "
    "situation it is actually given.\n\n"
    "A NAIVE fix ('require deriving the value from context, name the rule') was "
    "tried and often does NOT work: 'derive from context' is an ABSTRACT "
    "instruction a small model cannot reliably follow even when told to -- "
    "telling it to derive harder does not fix an inability to derive. Do not just "
    "ask it to 'derive the right value' -- DECOMPOSE the derivation into "
    "something mechanical, following this exact shape (the one that worked for a "
    "floating-point tolerance skill): a tiered, checkable procedure --\n"
    "1. If the situation states an explicit value/margin/rule, use exactly that.\n"
    "2. Else, if a well-known, checkable domain convention applies (name at least "
    "one concretely, e.g. a specific unit, a specific data type's sentinel, a "
    "specific standard default) state it and its trigger condition explicitly, "
    "as a direct mapping from an observable signal to a value -- not 'the right "
    "convention for the domain'.\n"
    "3. Else, do not guess: derive a conservative, well-defined fallback from the "
    "language/type system itself (not a real-world-scale guess) and say so "
    "explicitly in a comment, so a human reviewing the diff can correct it.\n\n"
    "IMPORTANT when your tiered rule introduces a variable/placeholder to cover "
    "rarer cases: for the common/fallback case (tier 3, or whichever tier "
    "matches what the ORIGINAL code sample already did), any code sample must "
    "stay LITERALLY concrete -- reuse the original's exact literal (e.g. "
    "`val is None`), never replace it with the new variable/placeholder even "
    "though that variable is needed to also cover the rarer tiers. Losing "
    "concreteness on the common case to gain generality for a rare one is "
    "exactly the kind of regression this rewrite must avoid.\n\n"
    "Keep every other instruction, case, and constraint in the procedure exactly "
    "as it is -- do not shorten, summarize, or drop anything unrelated to the "
    "flagged slot. Return ONLY the full rewritten procedure text, no preamble, "
    "no code fences."
)


@dataclass
class RepairResult:
    accepted: bool
    reason: str
    original_tracking_ratio: float
    candidate_tracking_ratio: float | None = None
    candidate_text: str | None = None
    holdout_passed: bool | None = None
    saved_path: str | None = None
    content_check_label: str | None = None
    verification_inconclusive: bool = False  # True when the candidate could NOT be
    # judged at all (verification infra failed to produce evidence), as opposed to
    # being judged and found wanting -- see inspector.py's judge_repair_result,
    # which routes these two cases to different retry strategies.


def _build_repair_prompt(book: Book, slot_name: str, ablation: AblationResult, prior_feedback: str | None = None) -> str:
    evidence_lines = []
    for variant, per_task in ablation.per_variant.items():
        for task_id, values in per_task.items():
            evidence_lines.append(f"  - with the slot set to {variant!r}, task {task_id!r} produced: {values}")
    evidence = "\n".join(evidence_lines)
    # prior_feedback (Inspector loop, 2026-09-18): questa NON e' la prima
    # riscrittura -- un tentativo precedente e' stato rifiutato per un motivo
    # specifico, gia' diagnosticato. Farlo leggere prima di riscrivere di
    # nuovo, non ripetere lo stesso errore alla cieca.
    feedback_block = f"\n\nPrevious attempt was REJECTED for this specific reason -- do not repeat it: {prior_feedback}\n" if prior_feedback else ""
    return (
        f"Procedure (flagged slot: {slot_name!r}):\n\n{book.procedure_text}\n\n"
        f"Ablation evidence (tracking ratio {ablation.tracking_ratio:.0%} -- the model's output matched "
        f"whichever value was written into the slot, {ablation.tracked_lockstep}/{ablation.total_checks} times):\n"
        f"{evidence}{feedback_block}\n\n"
        "Decompose the derivation into a concrete, tiered, checkable procedure as instructed, do not "
        "just add an abstract 'derive from context' instruction."
    )


def repair_skill(
    experiment_id: str,
    book: Book,
    slot_name: str,
    ablation: AblationResult,
    tracked_tasks: list[Task],
    extract_value: ValueExtractor,
    slot_transform: SlotTransform,
    variant_labels: list[str],
    ablation_adapter: ModelAdapter,
    repair_adapter: ModelAdapter,
    holdout_task: Task,
    output_dir: Path | None = None,
    unrelated_tasks: list[Task] | None = None,
    prior_feedback: str | None = None,
    reuse_candidate_text: str | None = None,
) -> RepairResult:
    """`slot_transform`/`variant_labels` must be the SAME ones used to build
    `ablation` in the first place, applied here to the ORIGINAL text again --
    real bug found live (2026-09-16): re-applying pre-baked replacement
    TEXTS built from the original book is silently meaningless once the
    rewrite has actually removed the literal slot (the swap becomes a no-op
    on text that no longer contains it, and the resulting "ablation" just
    measures sampling noise, not substitution risk). Passing the transform
    FUNCTION instead lets this re-derive variants from the CANDIDATE's own
    text, and detect when the slot is simply gone.

    `reuse_candidate_text` (2026-09-18): when set, SKIPS the Expert rewrite
    call and re-runs verification on this exact text instead -- for the
    Inspector loop to retry a flaky VERIFICATION step (e.g. transient
    generation failure downstream) without discarding a candidate that was
    never actually judged and burning another rewrite call for nothing. Only
    makes sense as a response to a previous `verification_inconclusive=True`
    result, never to a real quality rejection (see inspector.py)."""
    if ablation.total_checks == 0:
        return RepairResult(accepted=False, reason="ablation originale senza dati (total_checks=0)", original_tracking_ratio=0.0)

    if reuse_candidate_text is not None:
        candidate_text = reuse_candidate_text
    else:
        prompt = _build_repair_prompt(book, slot_name, ablation, prior_feedback)
        completion = repair_adapter.complete(prompt=prompt, system=_REPAIR_SYSTEM_PROMPT, max_tokens=2048)
        candidate_text = completion.text.strip()
        if not candidate_text:
            return RepairResult(accepted=False, reason="riscrittura vuota", original_tracking_ratio=ablation.tracking_ratio)

    candidate_book = Book(**{**asdict(book), "procedure_text": candidate_text})
    candidate_variants = {label: slot_transform(candidate_text, label) for label in variant_labels}
    slot_still_present = any(text != candidate_text for text in candidate_variants.values())

    if not slot_still_present:
        # Il letterale manipolabile non compare più nel testo riscritto --
        # non ha senso ri-applicare la stessa sostituzione testuale (sarebbe
        # uno swap a vuoto travestito da misura). La sua assenza è di per sé
        # la prova che quella specifica sostituzione meccanica non può più
        # avvenire allo stesso modo -- non equivale a "il rischio è zero" in
        # assoluto (potrebbe essercene un altro), ma è un segnale reale, non
        # rumore di campionamento spacciato per un dato.
        candidate_ablation = None
        candidate_tracking_ratio = None
        ablation_note = "il letterale manipolabile non è più presente nel testo riscritto (swap non più applicabile allo stesso modo)"
    else:
        candidate_ablation = run_substitution_ablation(
            experiment_id=experiment_id, book=candidate_book, slot_name=slot_name,
            slot_variants=candidate_variants, tracked_tasks=tracked_tasks,
            extract_value=extract_value, adapter=ablation_adapter, reps=2,
            unrelated_tasks=unrelated_tasks,
        )
        candidate_tracking_ratio = candidate_ablation.tracking_ratio
        drop = ablation.tracking_ratio - candidate_tracking_ratio
        ablation_note = f"tracking {ablation.tracking_ratio:.0%} -> {candidate_tracking_ratio:.0%}"
        if drop < _MIN_TRACKING_DROP:
            return RepairResult(
                accepted=False,
                reason=f"tracking non sceso a sufficienza ({ablation_note}, richiesto un calo di almeno {_MIN_TRACKING_DROP:.0%})",
                original_tracking_ratio=ablation.tracking_ratio,
                candidate_tracking_ratio=candidate_tracking_ratio,
                candidate_text=candidate_text,
            )

    # Holdout: il candidato deve continuare a risolvere un caso che la skill
    # già gestiva -- stesso principio del gate holdout di optimizer.py,
    # applicato qui a un task Category-A noto invece che alla storia di un
    # experiment_id specifico (la riparazione può scattare su una skill mai
    # ancora usata in un run vero).
    package = SkillPackage(books=[candidate_book], coverage="FULL")
    holdout_prompt = build_prompt(holdout_task, package)
    holdout_completion = ablation_adapter.complete(prompt=holdout_prompt, system=SYSTEM_PROMPT, max_tokens=4096)
    holdout_code = extract_code(holdout_completion.text)
    holdout_result = run_tests(holdout_code, holdout_task.test_source)

    if not holdout_result.passed:
        return RepairResult(
            accepted=False,
            reason=f"il candidato non supera più il task holdout noto ({holdout_task.task_id}): {holdout_result.error}",
            original_tracking_ratio=ablation.tracking_ratio,
            candidate_tracking_ratio=candidate_tracking_ratio,
            candidate_text=candidate_text,
            holdout_passed=False,
        )

    # Stabilizzatore generico (2026-09-17, gia' in uso da librarian/optimizer.py
    # per la compressione, mai collegato qui prima): tracking sceso e holdout
    # superato non bastano -- la riscrittura potrebbe aver comunque perso un
    # esempio concreto utile sostituendolo con un'astrazione vaga. Caso reale
    # che ha motivato l'aggiunta: wrong_string_case_comparison v3->v4 ha
    # rimosso '.casefold()' con un segnaposto, superando comunque gli altri due.
    content_check = check_content_preserved(book.procedure_text, candidate_text, repair_adapter)
    concreteness_check = check_concreteness_preserved(book.procedure_text, candidate_text, repair_adapter)
    if content_check["label"] != "PRESERVED" or concreteness_check["label"] != "PRESERVED":
        failing = content_check if content_check["label"] != "PRESERVED" else concreteness_check
        return RepairResult(
            accepted=False,
            reason=f"{ablation_note}, holdout superato ma contenuto non preservato: {failing['label']} -- {failing['reasoning']}",
            original_tracking_ratio=ablation.tracking_ratio,
            candidate_tracking_ratio=candidate_tracking_ratio,
            candidate_text=candidate_text,
            holdout_passed=True,
            content_check_label=failing["label"],
        )

    saved_path = _save_repaired_book(book, candidate_text, output_dir)
    return RepairResult(
        accepted=True,
        reason=f"{ablation_note}, holdout {holdout_task.task_id} superato, contenuto preservato",
        original_tracking_ratio=ablation.tracking_ratio,
        candidate_tracking_ratio=candidate_tracking_ratio,
        candidate_text=candidate_text,
        holdout_passed=True,
        saved_path=str(saved_path),
        content_check_label=content_check["label"],
    )


def _save_repaired_book(book: Book, repaired_text: str, output_dir: Path | None = None) -> Path:
    new_id = f"{book.id}_v{book.version + 1}"
    data = {
        "id": new_id,
        "version": book.version + 1,
        "title": f"{book.title} (substitution-repaired)",
        "domain": book.domain,
        "problem_tags": book.problem_tags,
        "capability_tags": book.capability_tags,
        "resource_tags": book.resource_tags,
        "pattern_id": book.pattern_id,
        "canonical_problem_id": book.canonical_problem_id,
        "status": "VERIFIED",
        "confidence": book.confidence,
        "verification_count": book.verification_count + 1,
        "verification_types": book.verification_types + ["substitution_repair_reverify"],
        "procedure_text": repaired_text,
        "derived_from": book.id,
        # Distinto da "compression" (optimizer.py) -- diversa trasformazione,
        # diversa genealogia da poter distinguere in un report.
        "generation_method": "substitution_repair",
    }
    out_path = (output_dir or config.LIBRARY_DIR) / f"{new_id}.yaml"
    out_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out_path
