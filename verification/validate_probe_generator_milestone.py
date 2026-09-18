"""Validation milestone for probe_generator.py (see the plan, Workstream A
point 2): before trusting LLM-generated probes on any skill this project has
no independent ground truth for, check they reproduce the ALREADY-KNOWN shape
for floating_point_equality -- a no-hint probe should show the tier-c literal
tracked in lockstep when manipulated, the same phenomenon canary.py found by
hand and validate_floating_point_milestone.py already reproduced with the
hand-written probes.

This does NOT require the generated probe to be identical to canary.py's own
same_destination/sensor_readings_agree -- only that the GENERATOR produces a
probe that, when run through the SAME ablation engine, shows the same kind of
signal. If it doesn't, the generator (not the ablation engine, already
validated separately) is the thing to fix before using it on an untested
skill.

Run: python -m cognitive_rpg.verification.validate_probe_generator_milestone
(requires the local Gemma server already running -- Ai/start-gemma-benchmark.ps1)
"""

import sys

from .. import config
from ..adapters.factory import build_adapter
from ..adapters.gemma_adapter import GemmaAdapter
from ..library.loader import load_books
from .probe_generator import generate_probe_set
from .substitution_ablation import run_substitution_ablation
from .validate_floating_point_milestone import _canonical, _replace_tier_c_constant, extract_epsilon


def main() -> int:
    # Vedi run_method_repair.py: console Windows in cp1252, testo generato
    # puo' contenere Unicode reale -- niente UnicodeEncodeError a meta' run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    books = {b.id: b for b in load_books()}
    book = next((b for b in books.values() if b.pattern_id == "floating_point_equality"), None)
    if book is None:
        print("[probe-milestone] nessun Book floating_point_equality trovato -- interrotto.")
        return 1
    if "1e-9" not in book.procedure_text:
        print(f"[probe-milestone] {book.id}: procedure_text non contiene più '1e-9' -- skill riscritta, aggiornare.")
        return 1

    expert_adapter = build_adapter("expert")
    print(f"[probe-milestone] modello generatore (Expert): {expert_adapter.PROVIDER}/{getattr(expert_adapter, 'model', '?')}")
    print(f"[probe-milestone] generando probe A/B/C per {book.id}...")
    probes = generate_probe_set(book, expert_adapter, categories=("A", "B", "C"), max_attempts=3)
    for category, task in probes.items():
        if task is None:
            print(f"[probe-milestone] categoria {category}: NESSUN probe self-check-valido generato "
                  f"({'atteso, C spesso non valida' if category == 'C' else 'INATTESO per A/B'})")
        else:
            print(f"[probe-milestone] categoria {category}: {task.problem_id} ({task.fn_name}) -- self-check ok "
                  f"(buggy_source fallisce davvero i propri test)")

    # Il probe interessante per l'ablazione tier-c e' quello senza indizio
    # numerico (B o C, quale dei due e' stato effettivamente generato) --
    # stesso ruolo di same_destination/sensor_readings_agree nella milestone
    # originale.
    no_hint_probe = probes.get("C") or probes.get("B")
    if no_hint_probe is None:
        print("\n[probe-milestone] nessun probe B o C generato -- impossibile testare la sostituzione "
              "meccanica su questo giro (il generatore stesso e' il problema, non l'ablazione).")
        return 1

    variant_values = [2.5e-6, 7e-4]
    slot_variants = {_canonical(v): _replace_tier_c_constant(book.procedure_text, str(v)) for v in variant_values}

    adapter = GemmaAdapter(model=config.GEMMA_MODEL)
    print(f"\n[probe-milestone] modello sotto test: {adapter.PROVIDER}/{adapter.model}")
    print(f"[probe-milestone] probe senza indizio usato per l'ablazione: {no_hint_probe.task_id}")

    result = run_substitution_ablation(
        experiment_id="verification_probe_generator_milestone",
        book=book,
        slot_name="tier_c_epsilon",
        slot_variants=slot_variants,
        tracked_tasks=[no_hint_probe],
        extract_value=extract_epsilon,
        adapter=adapter,
        reps=3,
    )

    print(f"\n[probe-milestone] tracking in lockstep sul probe generato: "
          f"{result.tracked_lockstep}/{result.total_checks} ({result.tracking_ratio:.0%})")
    for variant, per_task in result.per_variant.items():
        for task_id, values in per_task.items():
            print(f"    variante {variant} · {task_id}: estratti={values}")
    print(f"[probe-milestone] baseline (nessuna skill): {result.baseline}")

    print(
        "\n[probe-milestone] Lettura: un tracking sostanzialmente sopra 0% su questo probe GENERATO "
        "(mai visto da canary.py, mai usato per scrivere la skill) e' la prova che il generatore produce "
        "probe utili al motore di ablazione, non solo probe sintatticamente validi. Un tracking vicino a 0% "
        "non prova che il generatore sia rotto di per se' -- puo' significare che questo specifico probe "
        "generato somiglia piu' a un caso A/B (indizio residuo) che a un vero no-hint; confrontare con la "
        "milestone su probe scritti a mano (stesso modulo, validate_floating_point_milestone.py) come termine "
        "di paragone, non come pass/fail assoluto."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
