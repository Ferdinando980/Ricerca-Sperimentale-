"""Inspector: coordinates and verifies the output of a repair attempt across
the whole retry loop, then hands a specific, actionable diagnosis back to the
component that must regenerate -- until the result is SOLID, or a cap is
hit. Built 2026-09-18, user-designed after a real, extended conversation
about what generalizes vs. what needs concrete signals (see the session's
own Detective/Inspector discussion).

Design constraints, explicit and deliberate:
  - The Inspector NEVER originates new evidence. It only aggregates and
    cross-checks what repair_skill.py/method_repair.py ALREADY produce (the
    accept/reject gates built earlier this session: tracking/mechanical-
    application drop, real holdout, content preservation, concreteness
    preservation). Inventing its own judgment on top of those would make it
    just another unverified oracle -- exactly the failure mode this whole
    session has been fixing everywhere else.
  - Every attempt is logged, not just the final one -- the explicit point of
    building this is to be able to review the WHOLE sequence of tries later
    and find optimizations/problems in the Inspector mechanism itself, not
    just trust it because the final result looks fine.
  - The verdict always names the SPECIFIC responsible check (holdout /
    content / concreteness / tracking), and the feedback text handed back
    for regeneration is the SAME concrete reason already produced by the
    existing gates -- not a vague "try again".
  - This mechanism is itself subject to the lesson that motivated it
    (general_case_completeness): it must be validated on a real, broad
    sample (e.g. re-running experiment_0) before being trusted as a net
    improvement, not just because it sounds like a good idea. Not yet done
    -- see run_inspector_loop.py's own docstring.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .. import config
from .skill_conflict import ConflictReport

VALID_STATUSES = {"SOLID", "INCONSISTENT", "INCONCLUSIVE"}


@dataclass
class InspectorVerdict:
    status: str  # SOLID | INCONSISTENT | INCONCLUSIVE
    reason: str
    responsible: str  # which existing check/component this traces back to ("" if SOLID)
    feedback_for_regeneration: str  # "" if SOLID -- fed verbatim into the next attempt's prompt


def judge_repair_result(result: Any) -> InspectorVerdict:
    """Aggregation only -- every field read here already exists on
    RepairResult/MethodRepairResult, produced by the real gates in
    skill_repair.py/method_repair.py. The Inspector's only original work is
    naming which gate is responsible and phrasing that as something the
    repair prompt can act on directly.

    2026-09-18, real bug found via a genuine 4-attempt trajectory on
    wrong_comparison_operator: attempts 2-4 all failed because the trap-
    scenario generator downstream could not produce fresh, execution-
    verified scenarios (or produced only INCONCLUSIVE ones) -- NOT because
    the candidate text was bad. The loop kept asking for a brand-new
    rewrite each time anyway, which cannot fix a flaky VERIFIER and wastes
    an Expert call rewriting something that was never actually judged.
    `verification_inconclusive=True` on the result (set only at the specific
    "could not measure anything" return points, never at a real quality
    gate) now routes this to its own status/responsible pair instead of
    being folded into an ordinary quality rejection -- see run_repair_loop,
    which reuses the SAME candidate_text and retries verification only,
    rather than regenerating."""
    if result.accepted:
        return InspectorVerdict(status="SOLID", reason=result.reason, responsible="", feedback_for_regeneration="")

    if getattr(result, "verification_inconclusive", False):
        return InspectorVerdict(
            status="INCONCLUSIVE",
            reason=result.reason,
            responsible="verification_infrastructure",
            feedback_for_regeneration=result.reason,
        )

    if result.holdout_passed is False:
        responsible = "holdout"
    elif getattr(result, "content_check_label", None) not in (None, "PRESERVED"):
        responsible = f"content_check:{result.content_check_label}"
    else:
        responsible = "tracking_drop"

    return InspectorVerdict(
        status="INCONSISTENT",
        reason=result.reason,
        responsible=responsible,
        feedback_for_regeneration=result.reason,
    )


def judge_skill_package_conflicts(reports: list[ConflictReport]) -> InspectorVerdict:
    """Second evidence source the Inspector oversees (2026-09-18, per the
    user's explicit point that the Inspector must not handle only the
    Detective/repair-loop evidence but every part) -- aggregation only,
    every field read here already comes from skill_conflict.py's own
    verified, adversarially-checked classification. Unlike judge_repair_
    result, there is nothing to regenerate here (the books involved are
    each individually correct; the issue, if any, is only in how they
    combine for ONE specific task) -- so `feedback_for_regeneration` here
    means "annotation text to inject into the Worker's prompt context",
    not "retry the same generation step differently". A real, unreconciled
    REAL_CONFLICT makes the package INCONSISTENT (must be surfaced to the
    Worker explicitly rather than silently handed over); a COMPOUND
    relationship is NOT a problem -- it is useful disambiguating
    information (which skill applies to which case) worth handing to the
    Worker too, but the package itself is still SOLID."""
    real_conflicts = [r for r in reports if r.relationship == "REAL_CONFLICT"]
    if real_conflicts:
        r = real_conflicts[0]
        return InspectorVerdict(
            status="INCONSISTENT",
            reason=f"{r.book_a_id} e {r.book_b_id} danno istruzioni incompatibili per lo stesso caso ({r.reasoning})",
            responsible=f"skill_conflict:{r.book_a_id}+{r.book_b_id}",
            feedback_for_regeneration=(
                f"Le skill '{r.book_a_id}' e '{r.book_b_id}' si contraddicono per lo stesso caso di questo task: "
                f"la prima dice \"{r.quote_a}\", la seconda dice \"{r.quote_b}\". Valuta tu, per questo caso "
                f"specifico, quale applicare -- non sono entrambe applicabili insieme qui."
            ),
        )
    compounds = [r for r in reports if r.relationship == "COMPOUND"]
    if compounds:
        detail = "; ".join(
            f"'{r.book_a_id}' per {r.applies_to_a or 'un caso'}, '{r.book_b_id}' per {r.applies_to_b or 'un altro caso'}"
            for r in compounds
        )
        return InspectorVerdict(
            status="SOLID",
            reason=f"skill in relazione COMPOUND (si applicano a casi diversi dello stesso task, non in conflitto): {detail}",
            responsible="",
            feedback_for_regeneration=f"Nota: {detail} -- applica ciascuna al proprio caso, non sono in contrasto.",
        )
    inconclusive = [r for r in reports if r.relationship == "INCONCLUSIVE"]
    if inconclusive:
        # Non collassare su SOLID -- non e' la stessa cosa di "verificato,
        # nessun conflitto" (stesso principio di pattern_risk.py's
        # NOT_TESTED, mai spacciato per "sicuro"). Non blocca la pipeline,
        # ma va dichiarato onestamente com'e': non sappiamo se c'e' un
        # conflitto o no.
        r = inconclusive[0]
        return InspectorVerdict(
            status="INCONCLUSIVE",
            reason=f"relazione tra '{r.book_a_id}' e '{r.book_b_id}' non determinabile dal testo disponibile per questo task",
            responsible=f"skill_conflict:{r.book_a_id}+{r.book_b_id}",
            feedback_for_regeneration="",
        )
    return InspectorVerdict(status="SOLID", reason="nessun conflitto reale rilevato tra le skill del package", responsible="", feedback_for_regeneration="")


def _attempts_log_path(experiment_id: str) -> Path:
    return config.experiment_dir(experiment_id) / "inspector_attempts.jsonl"


def _log_attempt(experiment_id: str, pattern_id: str, attempt_n: int, verdict: InspectorVerdict, result: Any) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment_id": experiment_id,
        "pattern_id": pattern_id,
        "attempt": attempt_n,
        "verdict": asdict(verdict),
        # candidate_text incluso per esteso -- e' il punto stesso del log:
        # poter rivedere TUTTI i tentativi insieme, non solo l'ultimo, per
        # trovare ottimizzazioni/problemi del meccanismo stesso.
        "candidate_text": getattr(result, "candidate_text", None),
        "saved_path": getattr(result, "saved_path", None),
    }
    path = _attempts_log_path(experiment_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_repair_loop(
    repair_fn: Callable[..., Any],
    repair_kwargs: dict,
    experiment_id: str,
    pattern_id: str,
    max_attempts: int = 4,
) -> tuple[Any, list[InspectorVerdict]]:
    """Generic across both repair pipelines -- repair_fn is repair_skill or
    repair_method_skill, repair_kwargs is everything it needs EXCEPT
    prior_feedback (this loop supplies that itself, attempt to attempt).
    Returns (final_result, all_verdicts) -- the caller decides what to do
    with an UNRESOLVED-after-cap outcome (this loop does not silently retry
    forever, and does not silently accept a non-SOLID result either)."""
    verdicts: list[InspectorVerdict] = []
    prior_feedback: str | None = None
    reuse_candidate_text: str | None = None
    just_reused = False
    result = None
    for attempt_n in range(1, max_attempts + 1):
        result = repair_fn(**repair_kwargs, prior_feedback=prior_feedback, reuse_candidate_text=reuse_candidate_text)
        verdict = judge_repair_result(result)
        verdicts.append(verdict)
        _log_attempt(experiment_id, pattern_id, attempt_n, verdict, result)
        if verdict.status == "SOLID":
            break
        # Riuso al massimo UNA volta di fila (2026-09-18, bug reale trovato
        # dal vivo): se anche la verifica riprovata sullo STESSO testo torna
        # 'infrastruttura', il sospetto cambia -- non e' detto sia solo il
        # verificatore instabile, potrebbe essere il testo stesso a essere
        # troppo incoerente da verificare (visto dal vivo: una riscrittura
        # troncata/con ragionamento trapelato non e' che fa fallire la
        # rigenerazione degli scenari per sfortuna, la fa fallire perche' non
        # descrive piu' un metodo leggibile). Ririprovare all'infinito sullo
        # stesso testo sospetto spreca l'intero budget di tentativi su un
        # candidato che andava comunque scartato -- dopo un solo riuso, forza
        # una rigenerazione fresca indipendentemente dal verdetto.
        if verdict.responsible == "verification_infrastructure" and not just_reused:
            # Il candidato non e' mai stato davvero giudicato -- ririprovare
            # SOLO la verifica sullo stesso testo, non chiederne uno nuovo
            # (vedi judge_repair_result: rigenerare non risolve un verificatore
            # instabile, e spreca una chiamata Expert su un rifacimento inutile).
            reuse_candidate_text = getattr(result, "candidate_text", None)
            prior_feedback = None
            just_reused = True
        else:
            reuse_candidate_text = None
            prior_feedback = verdict.feedback_for_regeneration
            just_reused = False
    return result, verdicts
