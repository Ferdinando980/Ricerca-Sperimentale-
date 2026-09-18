"""Unified entry point (2026-09-17, generalization requested by the user
after a real gap: a skill can be NUMERIC -- an illustrative literal value,
like floating_point_equality's '1e-9' -- or TEXTUAL/METHOD-based -- a fixed
procedural approach, like wrong_string_case_comparison's '.casefold()' --
and the engine's job is to catch mechanical substitution risk in EITHER
shape, not just the one a human happened to test first.

Tries rule_generalization.py's axis (a literal value + a general derivation
rule + contrasting scenarios) first; if the skill has no such literal, falls
back to method_trap.py's axis (a fixed method + a condition for when it
applies + trap scenarios where it doesn't). If NEITHER axis finds anything
to test, that is reported honestly as NOT_TESTED, never silently treated as
"safe" -- see [[the recap's own NO_SLOT-vs-LOW_RISK distinction]]."""

from dataclasses import dataclass

from ..adapters.base import ModelAdapter
from ..models import Book
from . import method_trap, rule_generalization


@dataclass
class PatternRiskResult:
    pattern_id: str
    book_id: str
    axis: str  # NUMERIC_RULE | METHOD_TRAP | NONE_APPLICABLE
    verdict: str
    detail: str


def check_pattern_risk(
    experiment_id: str,
    book: Book,
    generator_adapter: ModelAdapter,
    test_adapter: ModelAdapter,
    n_method_scenarios: int = 3,
) -> PatternRiskResult:
    rule = rule_generalization.extract_rule_stable(book, generator_adapter)
    if rule is not None:
        scenarios = rule_generalization.generate_contrasting_scenarios(book, rule, generator_adapter)
        if scenarios is None:
            # Regola trovata ma impossibile generare scenari contrastanti
            # auto-verificati -- non scendere silenziosamente all'asse
            # metodo: sarebbe un test diverso da quello per cui la regola e'
            # stata trovata, non un fallback legittimo.
            return PatternRiskResult(
                pattern_id=book.pattern_id, book_id=book.id, axis="NUMERIC_RULE", verdict="INCONCLUSIVE",
                detail="regola trovata ma impossibile generare scenari contrastanti auto-verificati",
            )
        result = rule_generalization.run_rule_generalization_check(
            experiment_id, book, rule, scenarios, test_adapter, generator_adapter,
        )
        return PatternRiskResult(pattern_id=book.pattern_id, book_id=book.id, axis="NUMERIC_RULE", verdict=result.verdict, detail=result.judge_reason)

    method = method_trap.extract_method_stable(book, generator_adapter)
    if method is not None:
        aggregated = method_trap.run_method_trap_checks(
            experiment_id, book, method, generator_adapter, test_adapter, n_scenarios=n_method_scenarios,
        )
        if aggregated is None:
            return PatternRiskResult(
                pattern_id=book.pattern_id, book_id=book.id, axis="METHOD_TRAP", verdict="INCONCLUSIVE",
                detail="metodo condizionato identificato ma impossibile generare scenari-trappola auto-verificati",
            )
        return PatternRiskResult(
            pattern_id=book.pattern_id, book_id=book.id, axis="METHOD_TRAP", verdict=aggregated.verdict,
            detail=f"{aggregated.n_mechanical}/{aggregated.n_scenarios} scenari con applicazione meccanica reale "
                   f"(verificata per esecuzione), {aggregated.n_avoided} evitati, {aggregated.n_inconclusive} non conclusivi",
        )

    return PatternRiskResult(
        pattern_id=book.pattern_id, book_id=book.id, axis="NONE_APPLICABLE", verdict="NOT_TESTED",
        detail="nessun valore letterale ne' metodo fisso condizionato identificato -- nessuno dei due assi si applica "
               "a questa skill (non equivale a 'sicura', solo a 'non misurabile con questi due test')",
    )
