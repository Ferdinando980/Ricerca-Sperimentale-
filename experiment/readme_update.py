"""Regenerates the "Cosa mostrano i run completi" section of README.md from
whatever real experiment logs exist under logs/ -- table, aggregate F-vs-B
delta, the retrieval-overhead range, and the economic classification counts.
Same spirit as recap.py/thesis_doc.py: pure aggregation of numbers already on
disk, zero LLM calls, safe to run any time (2026-08-24, so the README stops
going stale the way it did before -- a corrected claim sitting there for
weeks after the data underneath it had already changed).

The rest of README.md (the research question, the four configs, the canary
methodology, the architecture list) describes the system's design, not a
specific run's numbers -- it doesn't need to regenerate and isn't touched
here. Only the block between the two HTML comment markers below is replaced.

Run: python -m cognitive_rpg.experiment.readme_update
Writes cognitive_rpg/README.md (in place).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .. import config
from . import metrics
from .economics import economic_classification
from .events import _EXPERIMENT_ID_RE
from .experiment_log import read_all

MARKER_START = "<!-- AUTO:RISULTATI:START -->"
MARKER_END = "<!-- AUTO:RISULTATI:END -->"

README_PATH = Path(__file__).resolve().parent.parent / "README.md"

# Fixed historical fact, not a per-run number -- describes something that
# already happened once (the README used to claim no benefit, based on a run
# smaller and older than any tracked here) and doesn't need to regenerate.
_HISTORY_NOTE = (
    "Il primissimo run mai fatto su questo progetto (n=6-16 per cella, più piccolo "
    "e più vecchio di ognuno di quelli sopra) non mostrava alcun beneficio, ed è "
    "rimasto per un po' come unica conclusione scritta in questo README anche dopo "
    "che i run sotto lo avevano già smentito — non perché nascosto di proposito, "
    "solo perché nessuno aveva ricontrollato. Non l'ho cancellato dalla storia per "
    "pulizia, semplicemente non è più la conclusione giusta."
)


def _discover_experiment_ids() -> list[str]:
    if not config.LOG_DIR.exists():
        return []
    ids = [d.name for d in config.LOG_DIR.iterdir() if d.is_dir() and _EXPERIMENT_ID_RE.match(d.name)]
    return sorted(ids, key=lambda s: int(s.removeprefix("experiment")))


def _pct(n: int, passed: int) -> str:
    return f"{100 * passed / n:.1f}%" if n else "—"


def _run_summary(experiment_id: str) -> dict | None:
    records = read_all(experiment_id)
    if not records:
        return None
    by_config = metrics.overall(records)
    n = max((v["n"] for v in by_config.values()), default=0)
    b = by_config.get("B")
    f = by_config.get("F")
    delta = None
    if b and f and b["n"] and f["n"]:
        delta = 100 * f["passed"] / f["n"] - 100 * b["passed"] / b["n"]
    return {
        "id": experiment_id,
        "records": records,
        "n": n,
        "cells": {cfg: _pct(by_config[cfg]["n"], by_config[cfg]["passed"]) if cfg in by_config else "—"
                  for cfg in ("A", "B", "F", "C")},
        "b": b,
        "f": f,
        "delta": delta,
    }


def _table(runs: list[dict]) -> str:
    lines = [
        "| run | n | A (Expert) | B (Small) | F (Skill Library) | C (Cheater) | F vs B |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        delta_str = f"{r['delta']:+.1f}%" if r["delta"] is not None else "—"
        lines.append(
            f"| {r['id']} | {r['n']} | {r['cells']['A']} | {r['cells']['B']} | "
            f"{r['cells']['F']} | {r['cells']['C']} | {delta_str} |"
        )
    return "\n".join(lines)


def _sweep_sentence(runs: list[dict]) -> str:
    deltas = [r["delta"] for r in runs if r["delta"] is not None]
    n_runs = len(deltas)
    if n_runs == 0:
        return "Non ci sono ancora abbastanza run con sia B che F per un confronto."
    total_b_n = sum(r["b"]["n"] for r in runs if r["delta"] is not None)
    total_b_passed = sum(r["b"]["passed"] for r in runs if r["delta"] is not None)
    total_f_n = sum(r["f"]["n"] for r in runs if r["delta"] is not None)
    total_f_passed = sum(r["f"]["passed"] for r in runs if r["delta"] is not None)
    aggregate = 100 * total_f_passed / total_f_n - 100 * total_b_passed / total_b_n
    n_positive = sum(1 for d in deltas if d > 0)
    n_negative = sum(1 for d in deltas if d < 0)
    if n_runs == 1:
        streak = "nell'unico run disponibile finora"
    elif n_positive == n_runs:
        streak = f"in tutti e {n_runs} i run completi, mai pari o peggio"
    elif n_negative == 0:
        streak = f"in {n_positive} di {n_runs} run completi (mai peggio, qualche pareggio)"
    else:
        streak = f"in {n_positive} di {n_runs} run completi -- non più una striscia pulita, {n_negative} run mostrano F pari o peggio di B"
    return (
        f"F batte B {streak} — aggregato su n={total_f_n}, {aggregate:+.1f} punti percentuali."
    )


def _limits_paragraph(runs: list[dict]) -> str:
    most_complete = max(runs, key=lambda r: r["n"])
    records = most_complete["records"]
    by_cov = metrics.by_config_coverage(records)
    parts = []
    for cfg, label in (("F", "F"), ("C", "C")):
        full = by_cov.get((cfg, "FULL"))
        none = by_cov.get((cfg, "NONE"))
        if full and none and full["n"] and none["n"]:
            d = 100 * full["passed"] / full["n"] - 100 * none["passed"] / none["n"]
            sign = "positiva" if d > 0 else ("a zero, mai negativa" if d == 0 else "negativa")
            parts.append(f"quella di {label} è {sign} ({d:+.1f}%)" if d != 0 else f"quella di {label} è {sign}")
    detail = "; ".join(parts) if parts else "il dettaglio per coverage non è ancora disponibile su questo run"
    return (
        f"**Il guadagno non è uniforme, meccanismo per meccanismo.** Guardando il run più completo "
        f"finora (`{most_complete['id']}`, n={most_complete['n']}) sulla componente Δ Retrieval (FULL meno "
        f"NONE, dentro la stessa config): {detail} — il meccanismo di retrieval non aiuta allo stesso modo "
        f"in ogni config, anche quando l'accuracy finale coincide. Il dettaglio task-per-task è in "
        f"`logs/{most_complete['id']}/recap.md` e in `logs/{most_complete['id']}/thesis.html`."
    )


def _cost_paragraph(runs: list[dict]) -> str:
    overheads = []
    for r in runs:
        diffs = metrics.librarian_overhead(r["records"])
        if diffs:
            overheads.append(sum(diffs) / len(diffs))
    overhead_str = (
        f"tra {min(overheads):+.0f} e {max(overheads):+.0f}".replace("+-", "-")
        if len(overheads) > 1
        else (f"circa {overheads[0]:+.0f}" if overheads else "un numero non ancora disponibile")
    )
    most_complete = max(runs, key=lambda r: r["n"])
    rows = economic_classification(most_complete["id"])
    n_econ = sum(1 for row in rows if row["label"] == "ECONOMICALLY_POSITIVE")
    n_acc = sum(1 for row in rows if row["label"] == "ACCURACY_POSITIVE")
    n_neg = sum(1 for row in rows if row["label"] == "NEGATIVE")
    n_total = len(rows)
    return (
        f"Sul costo: F paga in media {overhead_str} token di input in più rispetto a B per usare una skill "
        f"già pronta (l'\"overhead di retrieval\", diverso in ogni run a seconda di quali skill vengono "
        f"recuperate), mentre costruire una skill nuova (l'Optimizer che comprime e riverifica) costa "
        f"circa 1000-2000 token una tantum per pattern. Ogni `recap.md` calcola un breakeven per pattern "
        f"(dopo quanti usi il costo di costruzione si ripaga rispetto a chiamare sempre Expert) e una "
        f"classificazione economica a tre vie — `ECONOMICALLY_POSITIVE` se conviene sui token, "
        f"`ACCURACY_POSITIVE` se non conviene sui token ma ha risolto qualcosa che A o B non risolvevano, "
        f"`NEGATIVE` altrimenti (che non significa \"butta via la skill\": con questi numeri piccoli può "
        f"avere valore che le due metriche non catturano). Sul run più completo (`{most_complete['id']}`), "
        f"di {n_total} pattern coperti {n_econ} {'risulta' if n_econ == 1 else 'risultano'} economicamente "
        f"{'positivo' if n_econ == 1 else 'positivi'} e {n_acc} accuracy-positiv{'o' if n_acc == 1 else 'i'} "
        f"— gli altri {n_neg} sono `NEGATIVE`, un dato scomodo che è più onesto mostrare che nascondere."
    )


def build_section() -> str:
    ids = _discover_experiment_ids()
    runs = [s for s in (_run_summary(i) for i in ids) if s]
    if not runs:
        return (
            f"{MARKER_START}\n## Cosa mostrano i run completi\n\nNessun run completo ancora nei log.\n{MARKER_END}"
        )
    body = "\n\n".join([
        "## Cosa mostrano i run completi",
        _table(runs),
        f"{_sweep_sentence(runs)} {_HISTORY_NOTE}",
        "Due limiti veri, non nascosti sotto la tabella:",
        (
            "**Non sono repliche indipendenti pulite.** I run condividono in gran parte lo stesso "
            "catalogo di task, e tra un run e l'altro l'Optimizer ha compresso e riverificato le skill "
            "esistenti (vedi la sezione Optimizer in ogni `recap.md`). Parte del vantaggio di F potrebbe "
            "riflettere la libreria che si affina su questi task specifici, non generalizzazione a task "
            "mai visti."
        ),
        _limits_paragraph(runs),
        _cost_paragraph(runs),
    ])
    return f"{MARKER_START}\n{body}\n{MARKER_END}"


def update_readme() -> bool:
    """Returns True if README.md changed."""
    text = README_PATH.read_text(encoding="utf-8")
    if MARKER_START not in text or MARKER_END not in text:
        raise RuntimeError(
            f"README.md is missing {MARKER_START}/{MARKER_END} markers -- "
            "add them around the results section once, by hand, before this can auto-update it."
        )
    pattern = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.DOTALL)
    new_text = pattern.sub(lambda _m: build_section(), text, count=1)
    changed = new_text != text
    if changed:
        README_PATH.write_text(new_text, encoding="utf-8")
    return changed


def main() -> int:
    changed = update_readme()
    print(f"[readme_update] {'README.md aggiornato.' if changed else 'README.md già allineato ai log, nessuna modifica.'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
