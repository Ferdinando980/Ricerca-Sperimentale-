"""Validation milestone for slot_identifier.py (see the plan, Workstream A
points 2 and 4): before trusting library_benchmark.py's fully-automated
slot-detection + extraction on any pattern this project has no independent
ground truth for, check it reproduces 4 ALREADY hand-verified conclusions --
not just floating_point_equality (validate_floating_point_milestone.py) and
not just "the generator writes usable probes"
(validate_probe_generator_milestone.py), but the actual identify_slot +
build_slot_variants + make_extractor machinery this module adds:

  - floating_point_equality: a slot SHOULD be found, and tracking should be
    HIGH (>= library_benchmark.HIGH_RISK_THRESHOLD) -- the known, hand-fixed
    case (canary.py, 2026-08-19).
  - wrong_accumulator_init, key_error_missing_dict_check,
    mutable_default_argument: a candidate slot SHOULD be found (the manual
    backlog audit closed 2026-08-18 flagged all 3 as "structurally similar"
    to floating_point_equality's risk shape -- an illustrative literal
    default in the procedure text) but tracking should be LOW -- that same
    audit's own conclusion ("risk did not materialize for this pattern"),
    re-derived independently here with the automated pipeline instead of
    trusted secondhand from the historical note.

Disagreement on ANY of the 4 (wrong slot-found/not-found verdict, or the
wrong HIGH/LOW side) means the automated pipeline has a real gap -- fix
slot_identifier.py before running library_benchmark.py on the rest of the
library, do not proceed on partial agreement.

Run: python -m cognitive_rpg.verification.validate_slot_identifier_milestone
(requires the local Gemma server already running -- Ai/start-gemma-benchmark.ps1,
and a real Expert provider configured in .env -- this makes real Expert calls,
unlike the Gemma-only milestones)."""

import sys

from .. import config
from ..adapters.factory import build_adapter
from ..adapters.gemma_adapter import GemmaAdapter
from ..library.loader import load_books
from .library_benchmark import HIGH_RISK_THRESHOLD
from .probe_generator import generate_probe_set
from .slot_identifier import build_slot_variants, identify_slot, make_extractor
from .substitution_ablation import run_substitution_ablation

EXPECTED = {
    "floating_point_equality": "HIGH",
    "wrong_accumulator_init": "LOW",
    "key_error_missing_dict_check": "LOW",
    "mutable_default_argument": "LOW",
}


def _check_one(pattern_id: str, expected: str, books_by_pattern, expert, gemma) -> tuple[bool, str]:
    book = books_by_pattern.get(pattern_id)
    if book is None:
        return False, f"nessun Book live per {pattern_id!r} -- impossibile verificare"

    slot = identify_slot(book.procedure_text, book.pattern_id, expert)
    if slot is None:
        # In tutti e 4 i casi noti l'audit manuale ha trovato un letterale
        # candidato (anche quando il rischio non si e' poi materializzato) --
        # nessuno slot e' sempre un disaccordo qui, non solo per il caso HIGH.
        return False, f"nessuno slot identificato (atteso: slot trovato, poi {expected})"

    print(f"    slot trovato: {slot.slot_name!r} = {slot.original_value!r}, alternative: {slot.alt_values}")
    probes = generate_probe_set(book, expert)
    tracked = [t for cat, t in probes.items() if t is not None and cat in ("B", "C")]
    if not tracked:
        return False, "slot trovato ma nessun probe B/C generato -- impossibile misurare il tracking"

    slot_variants = build_slot_variants(book.procedure_text, slot)
    extract_value = make_extractor(slot, expert)
    result = run_substitution_ablation(
        experiment_id="verification_slot_identifier_milestone", book=book, slot_name=slot.slot_name,
        slot_variants=slot_variants, tracked_tasks=tracked, extract_value=extract_value, adapter=gemma, reps=2,
    )
    observed = "HIGH" if result.tracking_ratio >= HIGH_RISK_THRESHOLD else "LOW"
    detail = f"tracking {result.tracked_lockstep}/{result.total_checks} ({result.tracking_ratio:.0%}) -> {observed}, atteso {expected}"
    return observed == expected, detail


def main() -> int:
    # Vedi run_method_repair.py: console Windows in cp1252, testo generato
    # puo' contenere Unicode reale -- niente UnicodeEncodeError a meta' run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    books_by_pattern = {b.pattern_id: b for b in load_books()}
    expert = build_adapter("expert")
    gemma = GemmaAdapter(model=config.GEMMA_MODEL)
    print(f"[slot-milestone] Expert (identificazione/giudice): {expert.PROVIDER}/{getattr(expert, 'model', '?')}")
    print(f"[slot-milestone] modello sotto test: {gemma.PROVIDER}/{gemma.model}")

    all_agree = True
    for pattern_id, expected in EXPECTED.items():
        print(f"\n[slot-milestone] === {pattern_id} (atteso: {expected}) ===")
        agree, detail = _check_one(pattern_id, expected, books_by_pattern, expert, gemma)
        print(f"[slot-milestone] {pattern_id}: {'ACCORDO' if agree else 'DISACCORDO'} -- {detail}")
        all_agree = all_agree and agree

    print("\n[slot-milestone] " + ("TUTTI i 4 casi noti confermati -- procedere con library_benchmark.py sul resto "
          "della libreria." if all_agree else "ALMENO UN caso noto NON riprodotto -- non fidarsi ancora di "
          "slot_identifier.py su pattern mai controllati a mano, correggere prima di procedere."))
    return 0 if all_agree else 1


if __name__ == "__main__":
    sys.exit(main())
