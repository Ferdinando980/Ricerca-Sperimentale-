"""End-to-end test of skill_repair.py on floating_point_equality, reusing the
exact same tasks/variants as the validation milestone so the before/after
tracking ratios are directly comparable. Writes to a SCRATCH output_dir
(library/_repair_scratch/), never the real library/books/, until a human
reviews the result -- same "never risk the real library" discipline already
used elsewhere in this codebase for first-time smoke tests of a new
automated-writer.

Run: python -m cognitive_rpg.verification.run_repair_floating_point
"""

import sys
from pathlib import Path

from .. import config
from ..adapters.factory import build_adapter
from ..adapters.gemma_adapter import GemmaAdapter
from ..experiment.canary import CANARY_SETS, INVALID_EXAMPLES
from ..library.loader import load_books
from .skill_repair import repair_skill
from .substitution_ablation import run_substitution_ablation
from .validate_floating_point_milestone import _canonical, _replace_tier_c_constant, extract_epsilon


def main() -> int:
    # Vedi run_method_repair.py: console Windows in cp1252, testo generato
    # puo' contenere Unicode reale -- niente UnicodeEncodeError a meta' run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    books = {b.id: b for b in load_books()}
    book = next(b for b in books.values() if b.pattern_id == "floating_point_equality")

    canary = CANARY_SETS["floating_point_equality"]
    tracked_tasks = [canary.b, INVALID_EXAMPLES["sensor_readings_agree"]]
    unrelated_tasks = [canary.c]
    variant_values = [2.5e-6, 7e-4]
    # variant_label (canonico, .2e) -> valore RAW passato a str() -- lo stesso
    # scarto già presente nella milestone: l'etichetta usata per il confronto
    # è normalizzata, il testo iniettato nel Book usa la forma str() grezza di
    # Python. slot_transform riapplica esattamente questa stessa coppia
    # (etichetta canonica -> valore raw) così il confronto resta coerente sia
    # sul testo originale sia, più avanti, su quello riscritto.
    _label_to_raw = {_canonical(v): str(v) for v in variant_values}
    slot_variants = {label: _replace_tier_c_constant(book.procedure_text, raw) for label, raw in _label_to_raw.items()}
    variant_labels = list(_label_to_raw.keys())

    def slot_transform(base_text: str, variant_label: str) -> str:
        return _replace_tier_c_constant(base_text, _label_to_raw[variant_label])

    adapter = GemmaAdapter(model=config.GEMMA_MODEL)
    # Riparazione con l'Expert configurato (.env), non Gemma -- bug reale
    # trovato dal vivo nel primo giro: Gemma, come modello di riscrittura, si
    # è limitata a echeggiare l'intero prompt (comprese le istruzioni), non
    # ha davvero riscritto nulla. Coerente con il piano ("ruolo Expert, non
    # Gemma -- è infrastruttura di generazione, non il modello sotto test").
    repair_adapter = build_adapter("expert")
    print(f"[repair] modello ablazione (sotto test): {adapter.PROVIDER}/{adapter.model}")
    print(f"[repair] modello riscrittura (Expert): {repair_adapter.PROVIDER}/{getattr(repair_adapter, 'model', '?')}")
    print(f"[repair] ablazione originale su {book.id} (riuso gli stessi task della milestone)...")

    original_ablation = run_substitution_ablation(
        experiment_id="verification_repair_test", book=book, slot_name="tier_c_epsilon",
        slot_variants=slot_variants, tracked_tasks=tracked_tasks, extract_value=extract_epsilon,
        adapter=adapter, reps=2, unrelated_tasks=unrelated_tasks,
    )
    print(f"[repair] tracking originale: {original_ablation.tracked_lockstep}/{original_ablation.total_checks} "
          f"({original_ablation.tracking_ratio:.0%})")

    scratch_dir = Path(__file__).resolve().parent.parent / "library" / "_repair_scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    result = repair_skill(
        experiment_id="verification_repair_test", book=book, slot_name="tier_c_epsilon",
        ablation=original_ablation, tracked_tasks=tracked_tasks, extract_value=extract_epsilon,
        slot_transform=slot_transform, variant_labels=variant_labels,
        ablation_adapter=adapter, repair_adapter=repair_adapter,
        holdout_task=canary.a, output_dir=scratch_dir, unrelated_tasks=unrelated_tasks,
    )

    print(f"\n[repair] accettata: {result.accepted}")
    print(f"[repair] motivo: {result.reason}")
    if result.candidate_tracking_ratio is not None:
        print(f"[repair] tracking: {result.original_tracking_ratio:.0%} -> {result.candidate_tracking_ratio:.0%}")
    else:
        print("[repair] tracking candidato: n/d")
    if result.candidate_text:
        candidate_path = scratch_dir / "last_candidate.txt"
        candidate_path.write_text(result.candidate_text, encoding="utf-8")
        print(f"\n[repair] testo candidato ({len(result.candidate_text)} caratteri, originale {len(book.procedure_text)}) "
              f"salvato per intero in: {candidate_path}")
    if result.saved_path:
        print(f"\n[repair] salvato in: {result.saved_path} (scratch, non la libreria reale)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
