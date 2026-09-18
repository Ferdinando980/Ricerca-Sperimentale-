"""Real library-wide run of the substitution-ablation/repair pipeline (see
the plan, C:\\Users\\grego\\.claude\\plans\\ethereal-herding-blossom.md,
Workstream A point 6) over every live Book in library/books/, using
slot_identifier.py's automatic slot detection + extraction instead of a
hand-authored slot per skill -- the step that makes this "sistema generale e
riusabile" instead of the one-off floating_point_equality investigation it
started as.

MANDATORY before trusting this (see validate_slot_identifier_milestone.py):
the auto slot-identification + extraction machinery must reproduce, on its
own, 4 ALREADY hand-verified conclusions:
  - floating_point_equality: HIGH tracking (canary.py, 2026-08-19).
  - wrong_accumulator_init / key_error_missing_dict_check /
    mutable_default_argument: a candidate slot IS found (same 3 patterns
    flagged "structurally similar" by the manual backlog audit closed
    2026-08-18) but LOW tracking (that audit's own conclusion: "risk did
    not materialize"), re-derived independently here rather than assumed
    from the historical note.
Disagreement on any of the 4 means the automated pipeline has a real gap and
should not be trusted yet on the untested remainder.

Real, checked-live context this benchmark's report reuses rather than
re-derives (librarian/librarian.py, imported directly, not copied):
8 of the library's 13 current pattern Books (LOW_VALUE_RETRIEVAL_PATTERNS)
are UNCONDITIONALLY skipped by real retrieval today -- route() returns
coverage=NONE for them regardless of tag overlap, because
retrieval_waste_analysis() over 75 real injected quests found they never
once made a measured behavioral difference vs no-skill-at-all. Only
floating_point_equality and wrong_string_case_comparison are ever actually
retrieved into a live quest with demonstrated benefit. This benchmark still
tests every pattern (a Book not currently retrieved could become retrievable
again if that policy changes, and the automated pipeline itself needs
broad exercising) but the report calls out the 2 patterns that matter for
today's real routing decisions, separately from the 8 that are currently
inert by policy.

For each pattern (deduped to the highest live version via the SAME
_latest_per_pattern the real Librarian uses -- reused, not reimplemented):
  1. identify_slot (Expert) -- NO_SLOT is a legitimate, expected outcome for
     roughly half the patterns per the 2026-08-18 manual audit, not a
     failure of this script.
  2. generate_probe_set (Expert, self-verified) for tracked/holdout tasks.
  3. run_substitution_ablation (Gemma, the model under test).
  4. if tracking_ratio >= HIGH_RISK_THRESHOLD: repair_skill (Expert rewrite +
     re-verify with the SAME ablation + the existing holdout gate).
  5. record a structured outcome for EVERY pattern, including unresolved
     ones. An unresolved case is a case for analysis (why didn't repair
     work: tracking didn't drop enough? holdout broke? no valid A-probe to
     use as holdout at all?), not just a count in a table -- explicit user
     direction, 2026-09-17.

Run: python -m cognitive_rpg.verification.library_benchmark <experiment_id>
Writes logs/{experiment_id}/verification_benchmark.json (the report script,
recap_verification.py, reads this and nothing else)."""

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config
from ..adapters.factory import build_adapter
from ..adapters.gemma_adapter import GemmaAdapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..domain.verifier import run_tests
from ..librarian.librarian import LOW_VALUE_RETRIEVAL_PATTERNS, _latest_per_pattern
from ..library.loader import load_books
from ..models import Book, SkillPackage, Task
from . import probe_generator, slot_identifier
from .holdout import get_known_task
from .skill_repair import repair_skill
from .substitution_ablation import run_substitution_ablation

HIGH_RISK_THRESHOLD = 0.5

# Le 4 conclusioni gia' verificate a mano che l'identificazione automatica
# deve riprodurre prima di essere fidata sul resto -- vedi
# validate_slot_identifier_milestone.py, che testa proprio queste 4.
KNOWN_CASES = {
    "floating_point_equality": "atteso HIGH_RISK (verificato a mano 2026-08-19, canary.py)",
    "wrong_accumulator_init": "atteso LOW_RISK (slot candidato trovato, audit manuale 2026-08-18: rischio non materializzato)",
    "key_error_missing_dict_check": "atteso LOW_RISK (slot candidato trovato, audit manuale 2026-08-18: rischio non materializzato)",
    "mutable_default_argument": "atteso LOW_RISK (slot candidato trovato, audit manuale 2026-08-18: rischio non materializzato)",
}

# Gli unici 2 pattern su 13 con beneficio comportamentale REALE misurato
# (librarian.py, retrieval_waste_analysis su 75 quest reali) -- meritano
# risalto separato nel report, non solo una riga nella tabella generica.
REAL_IMPACT_PATTERNS = {"floating_point_equality", "wrong_string_case_comparison"}


@dataclass
class PatternOutcome:
    pattern_id: str
    book_id: str
    book_version: int
    status: str  # NO_SLOT | LOW_RISK | HIGH_RISK_REPAIRED | HIGH_RISK_UNRESOLVED | GENERATION_FAILED
    detail: str
    slot_name: str | None = None
    original_value: str | None = None
    tracking_ratio: float | None = None
    tracking_after_repair: float | None = None
    repaired_book_path: str | None = None
    real_impact_pattern: bool = False
    low_value_retrieval: bool = False
    known_case_expectation: str | None = None


def _pick_holdout(probes: dict[str, "Task | None"], book: Book, gemma: GemmaAdapter) -> "Task | None":
    """Preferisce il task KNOWN reale del catalogo (holdout.py) -- lo stesso
    che il Book documenta, hand-verificato dalla prima sessione del
    progetto, non un'invenzione LLM che ha bisogno essa stessa di un
    self-check. Trovato dal vivo 2026-09-17: floating_point_equality e'
    rimasto HIGH_RISK_UNRESOLVED nel primo run reale proprio perche' questo
    fallback non esisteva ancora e il probe A auto-generato non bastava.
    Solo se manca un task KNOWN reale si scende al Category A auto-generato
    (hint esplicito) -- ma solo se la skill ORIGINALE, non riparata, lo
    supera davvero gia'; un probe che la skill non gestiva correttamente non
    e' un controllo di regressione valido (stesso principio del holdout di
    skill_repair.py)."""
    known_task = get_known_task(book.pattern_id)
    if known_task is not None:
        # Verificato comunque, non assunto: il Book DOCUMENTA questo task,
        # ma una versione compressa/riscritta potrebbe in teoria non
        # risolverlo piu' correttamente -- stesso controllo del ramo
        # Category-A sotto, mai saltato "perche' e' quello ufficiale".
        package = SkillPackage(books=[book], coverage="FULL")
        prompt = build_prompt(known_task, package)
        completion = gemma.complete(prompt=prompt, system=SYSTEM_PROMPT, max_tokens=4096)
        code = extract_code(completion.text)
        if run_tests(code, known_task.test_source).passed:
            return known_task
        # Il Book originale stesso non risolve piu' il proprio task noto --
        # non un holdout valido; scendere al Category A come ultima risorsa.

    task = probes.get("A")
    if task is None:
        return None
    package = SkillPackage(books=[book], coverage="FULL")
    prompt = build_prompt(task, package)
    completion = gemma.complete(prompt=prompt, system=SYSTEM_PROMPT, max_tokens=4096)
    code = extract_code(completion.text)
    result = run_tests(code, task.test_source)
    return task if result.passed else None


def run_benchmark(experiment_id: str, output_dir: Path | None = None) -> list[PatternOutcome]:
    expert = build_adapter("expert")
    gemma = GemmaAdapter(model=config.GEMMA_MODEL)
    print(f"[benchmark] Expert (generazione/giudice): {expert.PROVIDER}/{getattr(expert, 'model', '?')}")
    print(f"[benchmark] modello sotto test: {gemma.PROVIDER}/{gemma.model}")

    books = load_books()
    latest = {b.pattern_id: b for b in _latest_per_pattern(books)}
    print(f"[benchmark] {len(latest)} pattern nella libreria live (dedup per versione, stessa logica del Librarian reale)")

    outcomes: list[PatternOutcome] = []
    for pattern_id, book in sorted(latest.items()):
        print(f"\n[benchmark] === {pattern_id} ({book.id}, v{book.version}) ===")
        low_value = pattern_id in LOW_VALUE_RETRIEVAL_PATTERNS
        real_impact = pattern_id in REAL_IMPACT_PATTERNS
        if low_value:
            print("[benchmark] nota: LOW_VALUE_RETRIEVAL_PATTERNS -- oggi route() salta sempre questa skill (coverage=NONE), "
                  "testata qui comunque per esercitare la pipeline, non perche' sia usata in pratica")

        # identify_slot_stable (scomposto + avvocato del diavolo + voto a
        # maggioranza su 3 campioni indipendenti), non identify_slot da solo
        # -- validato 2026-09-17/18: identify_slot da solo dava verdetti
        # diversi in run separati sullo stesso identico testo (key_error_
        # missing_dict_check), e anche la versione scomposta+stabilizzata
        # senza voto ha dato esiti diversi su integer_division_truncation in
        # due run consecutivi lo stesso giorno -- il voto a maggioranza e'
        # il pezzo che mancava, non un'alternativa ai due controlli precedenti.
        slot = slot_identifier.identify_slot_stable(book.procedure_text, book.pattern_id, expert)
        if slot is None:
            outcome = PatternOutcome(
                pattern_id=pattern_id, book_id=book.id, book_version=book.version, status="NO_SLOT",
                detail="nessun letterale sostituibile identificato (atteso per circa meta' della libreria)",
                low_value_retrieval=low_value, real_impact_pattern=real_impact,
            )
            print(f"[benchmark] {pattern_id}: nessuno slot identificato")
        else:
            print(f"[benchmark] {pattern_id}: slot {slot.slot_name!r} = {slot.original_value!r}, alternative: {slot.alt_values}")
            probes = probe_generator.generate_probe_set(book, expert)
            tracked_tasks = [t for cat, t in probes.items() if t is not None and cat in ("B", "C")]
            if not tracked_tasks:
                outcome = PatternOutcome(
                    pattern_id=pattern_id, book_id=book.id, book_version=book.version, status="GENERATION_FAILED",
                    detail="nessun probe B/C generato, impossibile misurare il tracking",
                    slot_name=slot.slot_name, original_value=slot.original_value,
                    low_value_retrieval=low_value, real_impact_pattern=real_impact,
                )
                print(f"[benchmark] {pattern_id}: nessun probe B/C generato -- interrotto per questo pattern")
            else:
                slot_variants = slot_identifier.build_slot_variants(book.procedure_text, slot)
                extract_value = slot_identifier.make_extractor(slot, expert)
                ablation = run_substitution_ablation(
                    experiment_id=experiment_id, book=book, slot_name=slot.slot_name,
                    slot_variants=slot_variants, tracked_tasks=tracked_tasks,
                    extract_value=extract_value, adapter=gemma, reps=2,
                )
                print(f"[benchmark] {pattern_id}: tracking {ablation.tracked_lockstep}/{ablation.total_checks} "
                      f"({ablation.tracking_ratio:.0%})")
                if ablation.tracking_ratio < HIGH_RISK_THRESHOLD:
                    outcome = PatternOutcome(
                        pattern_id=pattern_id, book_id=book.id, book_version=book.version, status="LOW_RISK",
                        detail=f"tracking {ablation.tracking_ratio:.0%}, sotto soglia {HIGH_RISK_THRESHOLD:.0%}",
                        slot_name=slot.slot_name, original_value=slot.original_value,
                        tracking_ratio=ablation.tracking_ratio, low_value_retrieval=low_value, real_impact_pattern=real_impact,
                    )
                else:
                    holdout_task = _pick_holdout(probes, book, gemma)
                    if holdout_task is None:
                        outcome = PatternOutcome(
                            pattern_id=pattern_id, book_id=book.id, book_version=book.version,
                            status="HIGH_RISK_UNRESOLVED",
                            detail="tracking alto ma nessun probe A valido come holdout (A non generato, o la skill "
                                   "originale non lo supera nemmeno prima della riparazione) -- riparazione non tentata",
                            slot_name=slot.slot_name, original_value=slot.original_value,
                            tracking_ratio=ablation.tracking_ratio, low_value_retrieval=low_value, real_impact_pattern=real_impact,
                        )
                        print(f"[benchmark] {pattern_id}: rischio alto ma nessun holdout valido -- riparazione non tentata")
                    else:
                        repair = repair_skill(
                            experiment_id=experiment_id, book=book, slot_name=slot.slot_name,
                            ablation=ablation, tracked_tasks=tracked_tasks, extract_value=extract_value,
                            slot_transform=slot_identifier.make_slot_transform(slot),
                            variant_labels=slot.variant_values(),
                            ablation_adapter=gemma, repair_adapter=expert,
                            holdout_task=holdout_task, output_dir=output_dir,
                        )
                        print(f"[benchmark] {pattern_id}: riparazione {'ACCETTATA' if repair.accepted else 'RIFIUTATA'} -- {repair.reason}")
                        outcome = PatternOutcome(
                            pattern_id=pattern_id, book_id=book.id, book_version=book.version,
                            status="HIGH_RISK_REPAIRED" if repair.accepted else "HIGH_RISK_UNRESOLVED",
                            detail=repair.reason, slot_name=slot.slot_name, original_value=slot.original_value,
                            tracking_ratio=ablation.tracking_ratio, tracking_after_repair=repair.candidate_tracking_ratio,
                            repaired_book_path=repair.saved_path, low_value_retrieval=low_value, real_impact_pattern=real_impact,
                        )
        outcome.known_case_expectation = KNOWN_CASES.get(pattern_id)
        if outcome.known_case_expectation:
            print(f"[benchmark] caso noto di validazione incrociata -- {outcome.known_case_expectation}")
        outcomes.append(outcome)

    return outcomes


def _write_report(experiment_id: str, outcomes: list[PatternOutcome]) -> Path:
    out_path = config.experiment_dir(experiment_id) / "verification_benchmark.json"
    out_path.write_text(json.dumps([asdict(o) for o in outcomes], indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def main() -> int:
    experiment_id = sys.argv[1] if len(sys.argv) > 1 else "verification_benchmark"
    outcomes = run_benchmark(experiment_id)
    out_path = _write_report(experiment_id, outcomes)
    print(f"\n[benchmark] {len(outcomes)} pattern testati, report scritto in {out_path}")
    by_status: dict[str, int] = {}
    for o in outcomes:
        by_status[o.status] = by_status.get(o.status, 0) + 1
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
