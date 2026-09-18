"""Automatic re-verification of whether a pattern's skill actually helps --
generalizes librarian.py's LOW_VALUE_RETRIEVAL_PATTERNS from a manually-
maintained, one-time snapshot (computed 2026-08-19, on the book content THAT
day) into a callable check anyone can re-run after a skill changes.

Built 2026-09-18 after a direct, correct user challenge: "se non c'e' un
sistema che verifica che la skill peggiorerebbe, come faro' in futuro a
capire se usarla o meno? esiste gia' uno strumento per questo, perche' non
viene verificato cosi'?" -- there IS one (experiment/metrics.py's
retrieval_waste_analysis()), but it only ever ran once, against a batch of
75 historical quests, and nothing re-runs it when a Book actually changes
(exactly what happened today: mutable_default_argument and wrong_
comparison_operator were both repaired, and their LOW_VALUE membership
still reflects the OLD, pre-repair content).

Reuses retrieval_waste_analysis() UNCHANGED -- same WASTE/HURT/HELPED/
NEITHER classification, same definition of "value" (a real quest where B
failed and F, with the skill, passed) -- this module's only job is
supplying it FRESH B-vs-F data for one pattern's real catalog tasks instead
of reading a historical experiment log, and forcing retrieval past route()'s
own value-policy short-circuit (respect_value_policy=False) so a currently-
excluded pattern can be tested at all, since testing it IS the point."""

from ..adapters.base import ModelAdapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..domain.task_generator import generate_tasks
from ..domain.verifier import run_tests
from ..experiment.metrics import retrieval_waste_analysis
from . import librarian


def revalidate_pattern_value(pattern_id: str, adapter: ModelAdapter, n_reps: int = 3) -> dict:
    """Real B-vs-F comparison for every real catalog task of this pattern,
    n_reps independent repetitions each -- single-shot noise is exactly what
    misled key_error_missing_dict_check's rule-generalization verdict
    earlier today (2/3 GENERALIZES, 1/3 DOES_NOT on the SAME unchanged
    book), the same risk applies here to a pass/fail comparison. Returns
    retrieval_waste_analysis()'s own dict (n_injected/n_waste/n_hurt/
    n_helped/n_neither/wasted_tokens/helped_patterns) plus should_exclude:
    True means NOT ONE real HELPED instance was found across every real
    repetition run here -- the current LOW_VALUE membership still holds on
    fresh evidence. False means real value was demonstrated and the
    pattern should be reconsidered for removal from the blocklist."""
    tasks = [t for t in generate_tasks(seed=42) if t.pattern_id == pattern_id]
    if not tasks:
        return {"pattern_id": pattern_id, "error": "nessun task reale nel catalogo per questo pattern"}

    records = []
    for task in tasks:
        for rep in range(n_reps):
            rep_task_id = f"{task.task_id}__rep{rep}"

            b_prompt = build_prompt(task, None)
            b_completion = adapter.complete(prompt=b_prompt, system=SYSTEM_PROMPT, max_tokens=4096)
            b_passed = run_tests(extract_code(b_completion.text), task.test_source).passed
            records.append({
                "task_id": rep_task_id, "config_name": "B", "passed": b_passed,
                "input_tokens": b_completion.input_tokens, "coverage": "N/A",
            })

            # respect_value_policy=False: e' esattamente la policy sotto
            # esame qui, rispettarla renderebbe il test un no-op (package
            # sempre vuoto per un pattern gia' escluso).
            package = librarian.route(task, respect_value_policy=False)
            f_prompt = build_prompt(task, package)
            f_completion = adapter.complete(prompt=f_prompt, system=SYSTEM_PROMPT, max_tokens=4096)
            f_passed = run_tests(extract_code(f_completion.text), task.test_source).passed
            records.append({
                "task_id": rep_task_id, "config_name": "F", "passed": f_passed,
                "input_tokens": f_completion.input_tokens, "coverage": package.coverage,
            })

    analysis = retrieval_waste_analysis(records)
    analysis["pattern_id"] = pattern_id
    analysis["n_tasks"] = len(tasks)
    analysis["n_reps"] = n_reps
    analysis["should_exclude"] = pattern_id not in analysis["helped_patterns"]
    return analysis
