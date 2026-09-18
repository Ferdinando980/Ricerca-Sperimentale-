"""Generic repair for a method-based skill flagged by method_trap.py as
mechanically-applied (the model uses the skill's method whenever the
symptom superficially matches, even when the method's own stated condition
for correctness doesn't hold). Same principle as skill_repair.py, one level
up: require an explicit check of applicability before applying a fixed
METHOD, instead of requiring derivation of a fixed VALUE -- one rewrite
strategy, two shapes of the same underlying failure (mechanical
substitution: something offered in the skill gets reused regardless of
whether it actually fits the case at hand).

Holdout: this pattern's own REAL, hand-authored canonical task (domain/
task_generator.py's KNOWN split) -- not an LLM-generated probe. This is
deliberately stronger than skill_repair.py's own holdout source (an
auto-generated Category-A probe), and is exactly the fix for the blocker
that stopped floating_point_equality's automated repair earlier today
(library_benchmark.py: HIGH_RISK_UNRESOLVED, "nessun probe A valido come
holdout") -- the real catalog task was sitting there the whole time,
unused. See get_holdout_task, reused by skill_repair-style callers too.

Never overwrites the original -- same non-destructive Book-versioning
pattern as skill_repair.py/optimizer.py (new "{id}_v{n+1}.yaml",
derived_from, a distinct generation_method so genealogies never mix)."""

from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from .. import config
from ..adapters.base import ModelAdapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..domain.verifier import run_tests
from ..models import Book, SkillPackage
from .holdout import get_known_task
from .method_trap import AggregatedMethodTrapResult, MethodSpec, MethodTrapResult, run_method_trap_checks
from .stabilizer import check_concreteness_preserved, check_content_preserved


def _conclusive_ratio(n_mechanical: int, n_avoided: int) -> float | None:
    """Stessa definizione di run_method_trap_checks's proprio verdetto
    HIGH_RISK/LOW_RISK: meccanici / (meccanici + evitati), SOLO scenari
    conclusivi al denominatore. Un INCONCLUSIVE non e' ne' rischio ne'
    sicurezza -- includerlo al denominatore (come faceva una versione
    precedente di questo modulo) diluisce artificialmente il rapporto,
    facendo sembrare una skill piu' sicura solo perche' produce PIU'
    fallimenti generici invece di MENO applicazioni meccaniche. None se
    zero scenari conclusivi (rapporto indefinito, non zero)."""
    conclusive = n_mechanical + n_avoided
    return n_mechanical / conclusive if conclusive else None

# Stesso valore e stesso significato di skill_repair.py's _MIN_TRACKING_DROP:
# il calo minimo nel tasso di applicazione meccanica per contare come un
# miglioramento reale, non rumore tra due campioni piccoli.
_MIN_MECHANICAL_DROP = 0.25

_REPAIR_SYSTEM_PROMPT = (
    "You edit a procedure (a 'skill') written for an economical language model to "
    "follow. Evidence shows this procedure prescribes a METHOD that the model "
    "applies MECHANICALLY whenever the symptom superficially matches, even in "
    "cases where the method's own stated condition for correctness does not "
    "actually hold.\n\n"
    "A NAIVE fix ('explicitly verify the condition before applying the method') "
    "was tried and often does NOT work: the condition as originally stated is an "
    "ABSTRACT judgment call (e.g. 'is this really a ratio, not an index?', 'does "
    "the boundary belong per spec?') that a small model cannot reliably make even "
    "when explicitly told to check it -- telling it to judge harder does not fix "
    "an inability to judge. Do not just insert 'first verify X' -- DECOMPOSE the "
    "judgment itself into something mechanical, following this exact shape (the "
    "one that worked for a floating-point tolerance skill):\n"
    "1. Name a SPECIFIC, OBSERVABLE signal actually present in the code or its "
    "comments/docstring/spec text that distinguishes the cases -- not an abstract "
    "property to assess, a concrete thing to look for (e.g. 'is this value's "
    "result used afterward as a sequence index/subscript, or does it flow "
    "directly into the return value combined arithmetically with other terms?', "
    "or 'does a comment or docstring near this branch use a specific boundary "
    "phrase such as at least / up to / more than / exactly?').\n"
    "2. Give a DIRECT, mechanical mapping from that observable signal to the "
    "choice -- an if/then a small model can follow by pattern-matching text, not "
    "a request to 'derive the right one'.\n"
    "3. State an explicit, conservative fallback for when the signal is absent "
    "(never a confident guess): flag the uncertainty in a comment rather than "
    "silently picking one.\n\n"
    "IMPORTANT when your rule introduces a variable/placeholder to cover "
    "multiple cases: for the common case (whichever matches what the ORIGINAL "
    "code sample already did), any code sample must stay LITERALLY concrete -- "
    "reuse the original's exact literal method/value, never replace it with a "
    "new variable/placeholder even though that variable is needed to also "
    "cover rarer cases. Losing concreteness on the common case to gain "
    "generality for a rare one is exactly the kind of regression to avoid.\n\n"
    "Keep every other instruction, case, and constraint in the procedure exactly "
    "as it is -- do not shorten, summarize, or drop anything unrelated to the "
    "flagged step. Return ONLY the full rewritten procedure text, no preamble, "
    "no code fences."
)


@dataclass
class MethodRepairResult:
    accepted: bool
    reason: str
    original_mechanical_ratio: float
    candidate_mechanical_ratio: float | None = None
    candidate_text: str | None = None
    holdout_passed: bool | None = None
    saved_path: str | None = None
    content_check_label: str | None = None


def _build_repair_prompt(book: Book, method: MethodSpec, n_mechanical: int, n_scenarios: int, example: MethodTrapResult | None = None, prior_feedback: str | None = None) -> str:
    example_block = ""
    if example is not None:
        # Un esempio CONCRETO di fallimento reale, non solo un conteggio --
        # da' all'Expert qualcosa di specifico da guardare invece di dover
        # immaginare astrattamente come appare il fallimento.
        example_block = (
            f"\n\nConcrete example of a real failure (executed, not hypothetical) -- the model's actual code:\n"
            f"{example.code}\n(this failed the real test suite for that specific case)"
        )
    # prior_feedback (Inspector loop, 2026-09-18): un tentativo precedente e'
    # stato rifiutato per un motivo specifico, gia' diagnosticato -- vedi
    # skill_repair.py per lo stesso pattern.
    feedback_block = f"\n\nPrevious attempt was REJECTED for this specific reason -- do not repeat it: {prior_feedback}\n" if prior_feedback else ""
    return (
        f"Procedure (flagged method: {method.method!r}, marker {method.method_marker!r}):\n\n{book.procedure_text}\n\n"
        f"Evidence: in {n_mechanical}/{n_scenarios} independently generated test cases where the method's own "
        f"correctness condition ({method.condition!r}) did NOT hold, the model applied the method anyway and "
        f"failed real tests as a result -- verified by executing the generated code, not assumed.{example_block}{feedback_block}\n\n"
        "Decompose the condition into a concrete, mechanical signal as instructed, do not just add an abstract "
        "verification step."
    )


def repair_method_skill(
    experiment_id: str,
    book: Book,
    method: MethodSpec,
    original: AggregatedMethodTrapResult,
    repair_adapter: ModelAdapter,
    ablation_adapter: ModelAdapter,
    output_dir: Path | None = None,
    example: MethodTrapResult | None = None,
    prior_feedback: str | None = None,
) -> MethodRepairResult:
    original_ratio = _conclusive_ratio(original.n_mechanical, original.n_avoided)
    if original_ratio is None:
        return MethodRepairResult(accepted=False, reason="nessuno scenario conclusivo originale (tutti INCONCLUSIVE)", original_mechanical_ratio=0.0)

    holdout_task = get_known_task(book.pattern_id)
    if holdout_task is None:
        return MethodRepairResult(
            accepted=False, reason="nessun task KNOWN reale nel catalogo per questo pattern -- impossibile un holdout affidabile",
            original_mechanical_ratio=original_ratio,
        )

    prompt = _build_repair_prompt(book, method, original.n_mechanical, original.n_scenarios, example, prior_feedback)
    completion = repair_adapter.complete(prompt=prompt, system=_REPAIR_SYSTEM_PROMPT, max_tokens=2048)
    candidate_text = completion.text.strip()
    if not candidate_text:
        return MethodRepairResult(accepted=False, reason="riscrittura vuota", original_mechanical_ratio=original_ratio)

    candidate_book = Book(**{**asdict(book), "procedure_text": candidate_text})

    # Holdout PRIMA della ri-ablazione -- piu' economico, e se il candidato
    # rompe il caso reale noto non serve nemmeno rigenerare scenari-trappola
    # freschi per scoprirlo.
    package = SkillPackage(books=[candidate_book], coverage="FULL")
    holdout_prompt = build_prompt(holdout_task, package)
    holdout_completion = ablation_adapter.complete(prompt=holdout_prompt, system=SYSTEM_PROMPT, max_tokens=4096)
    holdout_code = extract_code(holdout_completion.text)
    holdout_result = run_tests(holdout_code, holdout_task.test_source)
    if not holdout_result.passed:
        return MethodRepairResult(
            accepted=False, reason=f"il candidato non supera piu' il task KNOWN reale ({holdout_task.task_id}): {holdout_result.error}",
            original_mechanical_ratio=original_ratio, candidate_text=candidate_text, holdout_passed=False,
        )

    candidate_aggregated = run_method_trap_checks(
        experiment_id, candidate_book, method, repair_adapter, ablation_adapter, n_scenarios=original.n_scenarios,
    )
    if candidate_aggregated is None or candidate_aggregated.n_scenarios == 0:
        return MethodRepairResult(
            accepted=False, reason="impossibile rigenerare scenari-trappola per la riverifica del candidato",
            original_mechanical_ratio=original_ratio, candidate_text=candidate_text, holdout_passed=True,
        )
    candidate_ratio = _conclusive_ratio(candidate_aggregated.n_mechanical, candidate_aggregated.n_avoided)
    if candidate_ratio is None:
        # Tutti gli scenari del candidato sono INCONCLUSIVE -- non e' ne'
        # prova di miglioramento ne' di peggioramento, non accettare alla
        # cieca solo perche' "non c'e' piu' applicazione meccanica visibile".
        return MethodRepairResult(
            accepted=False, reason="riverifica del candidato tutta INCONCLUSIVE -- nessuna evidenza ne' di miglioramento ne' di rischio residuo",
            original_mechanical_ratio=original_ratio, candidate_text=candidate_text, holdout_passed=True,
        )
    drop = original_ratio - candidate_ratio
    if drop < _MIN_MECHANICAL_DROP:
        return MethodRepairResult(
            accepted=False,
            reason=f"applicazione meccanica non scesa a sufficienza ({original_ratio:.0%} -> {candidate_ratio:.0%}, "
                   f"richiesto un calo di almeno {_MIN_MECHANICAL_DROP:.0%})",
            original_mechanical_ratio=original_ratio, candidate_mechanical_ratio=candidate_ratio,
            candidate_text=candidate_text, holdout_passed=True,
        )

    # Stabilizzatore generico (2026-09-17, gia' in uso da librarian/optimizer.py
    # per la compressione, mai collegato qui prima): il tracking sceso e
    # l'holdout superato non bastano -- la riscrittura potrebbe comunque aver
    # perso un esempio concreto utile, sostituendolo con un'astrazione vaga.
    # Caso reale che ha motivato l'aggiunta: wrong_string_case_comparison
    # v3->v4 ha rimosso '.casefold()' sostituendolo con un segnaposto,
    # superando comunque tracking+holdout.
    content_check = check_content_preserved(book.procedure_text, candidate_text, repair_adapter)
    concreteness_check = check_concreteness_preserved(book.procedure_text, candidate_text, repair_adapter)
    if content_check["label"] != "PRESERVED" or concreteness_check["label"] != "PRESERVED":
        failing = content_check if content_check["label"] != "PRESERVED" else concreteness_check
        return MethodRepairResult(
            accepted=False,
            reason=f"applicazione meccanica scesa a sufficienza ({original_ratio:.0%} -> {candidate_ratio:.0%}) ma "
                   f"contenuto non preservato: {failing['label']} -- {failing['reasoning']}",
            original_mechanical_ratio=original_ratio, candidate_mechanical_ratio=candidate_ratio,
            candidate_text=candidate_text, holdout_passed=True, content_check_label=failing["label"],
        )

    saved_path = _save_repaired_book(book, candidate_text, output_dir)
    return MethodRepairResult(
        accepted=True,
        reason=f"applicazione meccanica {original_ratio:.0%} -> {candidate_ratio:.0%}, holdout {holdout_task.task_id} superato, contenuto preservato",
        original_mechanical_ratio=original_ratio, candidate_mechanical_ratio=candidate_ratio,
        candidate_text=candidate_text, holdout_passed=True, saved_path=str(saved_path),
        content_check_label=content_check["label"],
    )


def _save_repaired_book(book: Book, repaired_text: str, output_dir: Path | None = None) -> Path:
    new_id = f"{book.id}_v{book.version + 1}"
    data = {
        "id": new_id,
        "version": book.version + 1,
        "title": f"{book.title} (method-repaired)",
        "domain": book.domain,
        "problem_tags": book.problem_tags,
        "capability_tags": book.capability_tags,
        "resource_tags": book.resource_tags,
        "pattern_id": book.pattern_id,
        "canonical_problem_id": book.canonical_problem_id,
        "status": "VERIFIED",
        "confidence": book.confidence,
        "verification_count": book.verification_count + 1,
        "verification_types": book.verification_types + ["method_repair_reverify"],
        "procedure_text": repaired_text,
        "derived_from": book.id,
        # Distinto da "compression" (optimizer.py) e da "substitution_repair"
        # (skill_repair.py, asse valore-letterale) -- genealogia distinguibile.
        "generation_method": "method_repair",
    }
    out_path = (output_dir or config.LIBRARY_DIR) / f"{new_id}.yaml"
    out_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out_path
