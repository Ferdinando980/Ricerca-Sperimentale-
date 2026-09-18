"""Real run of rule_generalization.py against a live Book -- default target
is floating_point_equality, the one pattern with an already-known, hand-
verified mechanical-substitution finding (canary.py, validated again this
session via substitution_ablation.py: 50% tracking). Checking whether THIS,
differently-shaped test (vary the scenario, not the skill) ALSO detects a
real problem here is the validation step before trusting it on anything
untested -- same discipline as every other milestone in this package.

Run: python -m cognitive_rpg.verification.run_rule_generalization [pattern_id]
(requires the local Gemma server already running -- Ai/start-gemma-benchmark.ps1)
"""

import sys

from .. import config
from ..adapters.factory import build_adapter
from ..adapters.gemma_adapter import GemmaAdapter
from ..librarian.librarian import _latest_per_pattern
from ..library.loader import load_books
from .rule_generalization import extract_rule, generate_contrasting_scenarios, run_rule_generalization_check


def main() -> int:
    # Vedi run_method_repair.py: console Windows in cp1252, testo generato
    # puo' contenere Unicode reale -- niente UnicodeEncodeError a meta' run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pattern_id = sys.argv[1] if len(sys.argv) > 1 else "floating_point_equality"
    # _latest_per_pattern, non load_books() grezzo -- stesso bug reale
    # trovato in run_method_repair.py (2026-09-17).
    book = next((b for b in _latest_per_pattern(load_books()) if b.pattern_id == pattern_id), None)
    if book is None:
        print(f"[rule-gen] nessun Book live per pattern {pattern_id!r}")
        return 1

    expert = build_adapter("expert")
    gemma = GemmaAdapter(model=config.GEMMA_MODEL)
    print(f"[rule-gen] Expert (regola/scenari/giudice): {expert.PROVIDER}/{getattr(expert, 'model', '?')}")
    print(f"[rule-gen] modello sotto test: {gemma.PROVIDER}/{gemma.model}")
    print(f"[rule-gen] Book: {book.id} (v{book.version})")

    rule = extract_rule(book, expert)
    if rule is None:
        print("[rule-gen] nessuna regola generalizzabile identificata -- interrotto (esito legittimo, non un errore)")
        return 0
    print(f"[rule-gen] regola: {rule.rule}")
    print(f"[rule-gen] letterale da evitare: {rule.literal_to_avoid!r}")
    print(f"[rule-gen] anti-pattern: {rule.anti_pattern}")

    scenarios = generate_contrasting_scenarios(book, rule, expert)
    if scenarios is None:
        print("[rule-gen] impossibile generare 2 scenari contrastanti auto-verificati -- interrotto")
        return 1
    print(f"[rule-gen] scenario A: {scenarios.task_a.problem_id}")
    print(f"[rule-gen] scenario B: {scenarios.task_b.problem_id}")
    print(f"[rule-gen] direzione attesa: {scenarios.direction}")

    result = run_rule_generalization_check(
        experiment_id="verification_rule_generalization", book=book, rule=rule,
        scenarios=scenarios, test_adapter=gemma, judge_adapter=expert,
    )

    print(f"\n[rule-gen] === CODICE A ({scenarios.task_a.problem_id}) ===\n{result.code_a}")
    print(f"[rule-gen] === CODICE B ({scenarios.task_b.problem_id}) ===\n{result.code_b}")
    print(f"\n[rule-gen] anti-pattern innescato (controllo deterministico, letterale {rule.literal_to_avoid!r} presente): {result.anti_pattern_triggered}")
    print(f"[rule-gen] giudizio comparativo: generalizes={result.generalizes} -- {result.judge_reason}")
    print(f"[rule-gen] VERDETTO FINALE: {result.verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
