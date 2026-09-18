"""Validation milestone (see the plan, Workstream A point 4): before trusting
substitution_ablation.py on any untested skill, reproduce the ALREADY-KNOWN,
hand-verified finding for floating_point_equality (canary.py, 2026-08-19:
tier-c's fallback constant tracked in lockstep 12/12 times on Gemini, tier-b
unaffected 6/6, no cross-tier leakage). If this engine can't reproduce that
qualitative shape, it isn't trustworthy on anything new yet -- do not skip
this and go straight to a real benchmark run.

Runs on Gemma (local, via GemmaAdapter -- not the Gemini this was originally
found on), so the exact ratio may legitimately differ; what this milestone
checks is that the MACHINERY correctly measures and detects the phenomenon,
not that Gemma behaves identically to Gemini. A different model behaving
differently here is itself a real, reportable finding, not a failure of the
milestone.

Run: python -m cognitive_rpg.verification.validate_floating_point_milestone
(requires the local Gemma server already running -- Ai/start-gemma-benchmark.ps1)
"""

import re
import sys

from .. import config
from ..adapters.gemma_adapter import GemmaAdapter
from ..experiment.canary import CANARY_SETS, INVALID_EXAMPLES
from ..library.loader import load_books
from .substitution_ablation import run_substitution_ablation

# Copre le varianti di nome più comuni per una tolleranza, non solo
# "epsilon" alla lettera -- un modello potrebbe scrivere eps/tolerance/tol.
_EPSILON_ASSIGN_RE = re.compile(r"\b(?:epsilon|eps|tolerance|tol)\s*=\s*([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)", re.IGNORECASE)
# Bug reale trovato dal vivo (2026-09-16, milestone probe_generator): non
# ogni modello nomina una variabile -- Gemma spesso scrive la tolleranza
# INLINE dentro il confronto stesso (`abs(a - b) < 1e-9`), senza mai
# assegnarla a un nome. Il solo pattern "nome = numero" sopra dava un falso
# None su probe strutturati diversamente (confronto dentro un loop invece che
# come valore di ritorno diretto), non perché il modello non applicasse la
# skill ma perché l'estrattore non guardava la forma giusta.
_EPSILON_INLINE_RE = re.compile(r"abs\([^)]*\)\s*<=?\s*([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)", re.IGNORECASE)


def _canonical(value: float) -> str:
    """Canonical string form used both as the variant label (the value we
    manipulate tier-c TO) and as the extractor's return value, so the
    engine's plain string equality check works correctly regardless of how
    the model formats the number in its own generated code (1e-9 vs 1e-09
    vs 0.000000001 all normalize to the same label)."""
    return f"{value:.2e}"


def extract_epsilon(code: str) -> str | None:
    match = _EPSILON_ASSIGN_RE.search(code) or _EPSILON_INLINE_RE.search(code)
    if not match:
        return None
    try:
        return _canonical(float(match.group(1)))
    except ValueError:
        return None


def _replace_tier_c_constant(procedure_text: str, new_value: str) -> str:
    """Tier-c's live wording (book_floating_point_equality_v4_v5.yaml) states
    the fallback as literal "1e-9" in two places (the rule and the worked
    example number) -- replace both occurrences, nothing else in the text
    matches this exact literal."""
    return procedure_text.replace("1e-9", new_value)


def main() -> int:
    # Vedi run_method_repair.py: console Windows in cp1252, testo generato
    # puo' contenere Unicode reale -- niente UnicodeEncodeError a meta' run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    books = {b.id: b for b in load_books()}
    book = next((b for b in books.values() if b.pattern_id == "floating_point_equality"), None)
    if book is None:
        print("[milestone] nessun Book floating_point_equality trovato in library/books/ -- interrotto.")
        return 1
    if "1e-9" not in book.procedure_text:
        print(f"[milestone] {book.id}: procedure_text non contiene più il letterale '1e-9' atteso -- "
              "la skill è stata riscritta da quando questo script è stato scritto, aggiornare l'ablazione.")
        return 1

    canary = CANARY_SETS["floating_point_equality"]
    tracked_tasks = [canary.b, INVALID_EXAMPLES["sensor_readings_agree"]]  # same_destination + sensor_readings_agree, i due no-hint originali
    unrelated_tasks = [canary.c]  # invoice_totals_match, tier-b/currency -- selettività

    variant_values = [2.5e-6, 7e-4]  # gli stessi due usati nell'ablazione originale (oltre a 1e-9, il default live)
    slot_variants = {
        _canonical(v): _replace_tier_c_constant(book.procedure_text, str(v))
        for v in variant_values
    }

    # Esplicitamente Gemma locale, non build_adapter("small") -- quella legge
    # SMALL_PROVIDER da .env, che potrebbe essere configurato su un provider
    # reale a pagamento (bug reale trovato dal vivo: il primo giro di questo
    # script ha chiamato gemini_vertex invece di Gemma perché SMALL_PROVIDER
    # non era "gemma" in .env). Questo script DEVE usare Gemma, sempre.
    adapter = GemmaAdapter(model=config.GEMMA_MODEL)
    print(f"[milestone] modello sotto test: {adapter.PROVIDER}/{adapter.model}")
    print(f"[milestone] Book: {book.id} (v{book.version}), slot: tier-c epsilon")
    print(f"[milestone] task tracciati: {[t.task_id for t in tracked_tasks]}")
    print(f"[milestone] task non correlato (selettività): {canary.c.task_id}")

    result = run_substitution_ablation(
        experiment_id="verification_milestone",
        book=book,
        slot_name="tier_c_epsilon",
        slot_variants=slot_variants,
        tracked_tasks=tracked_tasks,
        extract_value=extract_epsilon,
        adapter=adapter,
        reps=2,
        unrelated_tasks=unrelated_tasks,
    )

    print(f"\n[milestone] tracking in lockstep: {result.tracked_lockstep}/{result.total_checks} "
          f"({result.tracking_ratio:.0%})")
    for variant, per_task in result.per_variant.items():
        for task_id, values in per_task.items():
            print(f"    variante {variant} · {task_id}: estratti={values}")
    print(f"[milestone] baseline (nessuna skill): {result.baseline}")
    selectivity = result.selectivity_ok({canary.c.task_id})
    print(f"[milestone] selettività (tier-b non deve seguire tier-c): "
          f"{'OK, nessuna leakage' if selectivity else 'FALLITA' if selectivity is False else 'non testata'}")

    print(
        "\n[milestone] Nota: questo run è su Gemma locale, il finding originale era su Gemini -- "
        "un rapporto diverso da 12/12 non è di per sé un fallimento della macchina, è un dato reale "
        "su un modello diverso. Verificare comunque che il meccanismo di misura si comporti in modo "
        "sensato (variante seguita quando applicabile, baseline diversa dalla variante quando il "
        "modello ragiona davvero, nessuna leakage su tier-b)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
