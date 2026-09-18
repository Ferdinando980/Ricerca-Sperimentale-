"""Real run of method_repair.py against a live Book flagged HIGH_RISK by
method_trap.py: extract the method fresh, measure mechanical-application
rate with fresh scenarios, and if it's high, attempt a repair -- reporting
whatever actually happens, accepted or not.

Run: python -m cognitive_rpg.verification.run_method_repair <pattern_id> [n_scenarios]
(requires the local Gemma server already running)."""

import sys

from .. import config
from ..adapters.factory import build_adapter
from ..adapters.gemma_adapter import GemmaAdapter
from ..librarian.librarian import _latest_per_pattern
from ..library.loader import load_books
from .method_repair import repair_method_skill
from .method_trap import extract_method, run_method_trap_checks


def main() -> int:
    # Bug reale trovato dal vivo (2026-09-17): la console di Windows usa
    # cp1252 di default, e un testo di skill/candidato puo' contenere
    # caratteri Unicode reali (es. wrong_comparison_operator usa la freccia
    # "<->") -- un print() normale va in UnicodeEncodeError DOPO che il
    # risultato vero e' gia' stato calcolato, perdendo solo l'output
    # leggibile, non il dato.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("uso: python -m cognitive_rpg.verification.run_method_repair <pattern_id> [n_scenarios]")
        return 1
    pattern_id = sys.argv[1]
    n_scenarios = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    # _latest_per_pattern, non load_books() grezzo -- bug reale trovato dal
    # vivo (2026-09-17): un next() sulla lista piatta prendeva la PRIMA
    # versione trovata per ordine alfabetico dei file, non la piu' recente
    # (per 3 pattern con vecchia+nuova versione live contemporaneamente,
    # "_v2_v3.yaml" ordina PRIMA di "_v2_v3_v4.yaml" perche' '.' < '_').
    # Analizzava wrong_comparison_operator v3 (vecchia) invece di v4 (quella
    # davvero flaggata HIGH_RISK nel batch) senza nessun errore visibile.
    book = next((b for b in _latest_per_pattern(load_books()) if b.pattern_id == pattern_id), None)
    if book is None:
        print(f"[method-repair] nessun Book live per pattern {pattern_id!r}")
        return 1

    expert = build_adapter("expert")
    gemma = GemmaAdapter(model=config.GEMMA_MODEL)
    print(f"[method-repair] Expert: {expert.PROVIDER}/{getattr(expert, 'model', '?')}")
    print(f"[method-repair] modello sotto test: {gemma.PROVIDER}/{gemma.model}")
    print(f"[method-repair] Book: {book.id} (v{book.version})")

    method = extract_method(book, expert)
    if method is None:
        print("[method-repair] nessun metodo condizionato identificato -- interrotto")
        return 1
    print(f"[method-repair] metodo: {method.method}")
    print(f"[method-repair] marcatore: {method.method_marker!r}")
    print(f"[method-repair] condizione: {method.condition}")

    print(f"\n[method-repair] misuro il rischio originale con {n_scenarios} scenari freschi...")
    original = run_method_trap_checks("method_repair", book, method, expert, gemma, n_scenarios=n_scenarios)
    if original is None or original.n_scenarios == 0:
        print("[method-repair] impossibile generare scenari-trappola -- interrotto")
        return 1
    print(f"[method-repair] rischio originale: {original.n_mechanical}/{original.n_scenarios} meccanici, "
          f"{original.n_avoided} evitati, {original.n_inconclusive} non conclusivi -> {original.verdict}")

    if original.verdict != "HIGH_RISK":
        print("[method-repair] rischio non alto su questo giro -- riparazione non tentata (nessun bug da correggere qui ora)")
        return 0

    print("\n[method-repair] tentativo di riparazione...")
    example = next((r for r in original.per_scenario if r.verdict == "MECHANICAL_APPLICATION"), None)
    result = repair_method_skill(
        experiment_id="method_repair", book=book, method=method, original=original,
        repair_adapter=expert, ablation_adapter=gemma, example=example,
    )
    print(f"\n[method-repair] {'ACCETTATA' if result.accepted else 'RIFIUTATA'} -- {result.reason}")
    if result.candidate_text:
        print(f"\n[method-repair] === TESTO CANDIDATO ===\n{result.candidate_text}")
    if result.saved_path:
        print(f"\n[method-repair] salvato in: {result.saved_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
