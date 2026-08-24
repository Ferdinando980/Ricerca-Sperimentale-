"""Knowledge Map: sections -> skills -> coverage/usage/economics, over real
data already on disk. Phase 1 of the library evolution plan (conversation
2026-08-18, see the plan for the full 6-phase roadmap this is step 1 of).

This module changes ZERO retrieval or generation behavior -- it never
touches librarian/librarian.py, librarian/optimizer.py, or any file under
library/books/. It only reads: the section taxonomy (library/sections.py,
pure data), the live library (library/loader.py), and the same
event/record aggregation experiment/metrics.py already provides to
recap.py. Verifying this module therefore does NOT mean re-running an A/B/F
experiment (that would trivially show "unchanged", which is the correct but
uninformative result) -- it means reconciling these numbers against
recap.py's existing numbers on the same experiment_id: e.g. a pattern's
build_cost/n_uses here must equal recap.md section 4's numbers exactly,
since both now call the same experiment.metrics.skill_amortization().

Lives in experiment/, not library/, matching where recap.py and
observer_table.py already live (log/event aggregation is an experiment/
concern) -- library/ never depends on experiment/ anywhere in this codebase,
and this module doesn't start that.

Run: python -m cognitive_rpg.experiment.knowledge_map <experiment_id>
Writes logs/{experiment_id}/knowledge_map.md
"""

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .. import config
from ..librarian.librarian import _latest_per_pattern  # reuse the dedup logic, don't reimplement it
from ..library import sections as sections_mod
from ..library.loader import id_to_pattern_map, load_books
from . import economics, metrics
from .events import read_events, read_events_all_experiments
from .experiment_log import read_all


def _similarity_results() -> list[dict] | None:
    """Reads library/similarity_report.yaml if it exists (written by
    librarian/similarity.py, Phase 2 -- not tied to any experiment_id, it's
    about the library's own content). None if the Similarity Checker hasn't
    been run yet, distinct from an empty list (checker ran, found nothing)."""
    path = config.LIBRARY_DIR.parent / "similarity_report.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("pairs", [])


def _library_growth() -> list[dict]:
    """Book count per snapshot in library/snapshots/, timestamp-ordered by
    directory name (snapshot.py labels default to a UTC timestamp; manual
    labels sort wherever they alphabetically fall -- good enough to see
    growth over time without new infrastructure)."""
    snapshots_dir = config.LIBRARY_DIR.parent / "snapshots"
    if not snapshots_dir.exists():
        return []
    rows = []
    for d in sorted(snapshots_dir.iterdir()):
        if d.is_dir():
            rows.append({"label": d.name, "n_books": len(list(d.glob("*.yaml")))})
    return rows


def section_rows(experiment_id: str) -> list[dict]:
    all_books = load_books()
    latest_books = _latest_per_pattern(all_books)
    latest_by_pattern = {b.pattern_id: b for b in latest_books}
    files_per_pattern = defaultdict(int)
    for b in all_books:
        files_per_pattern[b.pattern_id] += 1

    records = read_all(experiment_id)
    events = read_events(experiment_id)
    tasks_by_id = {}
    try:
        from ..domain.task_generator import generate_tasks
        tasks_by_id = {t.task_id: t for t in generate_tasks(seed=42)}
    except Exception:
        pass

    usage_by_skill = metrics.skill_usage(events, records)
    amort_by_pattern = {
        row["pattern"]: row
        for row in metrics.skill_amortization(events, records, build_cost_events=read_events_all_experiments())
    }
    # usage_by_skill is keyed by exact skill_id (whatever was actually
    # retrieved -- could be an older version than latest_by_pattern if a
    # newer compression landed after that retrieval happened, or since moved
    # to archived_books/ as a confirmed duplicate). Aggregate up to
    # pattern_id via live+archived (id_to_pattern_map), same join
    # skill_amortization uses, so a moved-out id doesn't silently vanish.
    books_by_id = id_to_pattern_map()
    usage_by_pattern = defaultdict(lambda: {"n": 0, "tokens": []})
    for skill_id, u in usage_by_skill.items():
        pattern = books_by_id.get(skill_id)
        if pattern:
            usage_by_pattern[pattern]["n"] += u["n"]
            usage_by_pattern[pattern]["tokens"].extend([u["avg_tokens"]] * u["n"])

    rows = []
    for section_id in sections_mod.all_sections():
        pattern_ids = sections_mod.patterns_in_section(section_id)
        covered = [p for p in pattern_ids if p in latest_by_pattern]
        if len(covered) == len(pattern_ids) and pattern_ids:
            coverage = "COVERED"
        elif covered:
            coverage = "PARTIALLY_COVERED"
        else:
            coverage = "EMPTY"

        n_books = len(covered)
        n_files = sum(files_per_pattern.get(p, 0) for p in pattern_ids)
        n_uses = sum(usage_by_pattern[p]["n"] for p in pattern_ids)
        build_cost = sum(amort_by_pattern[p]["build_cost"] for p in pattern_ids if p in amort_by_pattern)
        saving_vals = [amort_by_pattern[p]["saving"] for p in pattern_ids if p in amort_by_pattern]
        avg_saving = sum(saving_vals) / len(saving_vals) if saving_vals else None

        rows.append({
            "section_id": section_id,
            "title": sections_mod.SECTIONS[section_id]["title"],
            "patterns": pattern_ids,
            "coverage": coverage,
            "n_books": n_books,
            "n_files_on_disk": n_files,
            "n_uses": n_uses,
            "build_cost": build_cost,
            "avg_saving": avg_saving,
        })
    return rows


def build_knowledge_map(experiment_id: str) -> str:
    L = []
    L.append(f"# Knowledge Map -- {experiment_id}")
    L.append(f"_Generato: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    L.append("")
    L.append(
        "Fase 1 dell'evoluzione della libreria (vedi conversazione 2026-08-18): "
        "sola lettura, nessun cambio di comportamento a retrieval o generazione. "
        "COVERED = tutti i pattern della sezione hanno un Book; EMPTY = nessuno "
        "(i 3 pattern NOVEL permanenti -- variable_shadowing, "
        "incorrect_sort_key_or_order, wrong_return_in_loop -- risultano sempre "
        "EMPTY per design, non e' un gap da colmare)."
    )
    L.append("")

    rows = section_rows(experiment_id)
    L.append("| sezione | pattern | coverage | book attuali | file su disco | usi | costo costruzione | risparmio medio/uso |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        saving = f"{r['avg_saving']:+.0f}" if r["avg_saving"] is not None else "n/d"
        L.append(
            f"| `{r['section_id']}` ({r['title']}) | {', '.join(r['patterns'])} | {r['coverage']} | "
            f"{r['n_books']} | {r['n_files_on_disk']} | {r['n_uses']} | {r['build_cost']} | {saving} |"
        )
    L.append("")
    total_files = sum(r["n_files_on_disk"] for r in rows)
    total_books = sum(r["n_books"] for r in rows)
    if total_files > total_books:
        L.append(
            f"- **{total_files} file su disco per {total_books} skill "
            f"\"attuali\"** ({total_files - total_books} versioni superate/compresse "
            f"ancora presenti) -- vedi sotto la sezione Similarity per sapere quante "
            f"di queste sono davvero DUPLICATE."
        )
    L.append("")

    # similarity / duplicate detection (Phase 2) -------------------------
    L.append("## Similarity / Duplicate detection")
    sim = _similarity_results()
    if sim is None:
        L.append("- Non ancora lanciato (`python -m cognitive_rpg.librarian.similarity`).")
    elif not sim:
        L.append("- Ultimo run: nessuna coppia trovata (libreria troppo piccola/vuota).")
    else:
        counts = {}
        for r in sim:
            counts[r["label"]] = counts.get(r["label"], 0) + 1
        L.append("- " + ", ".join(f"{label}: {n}" for label, n in sorted(counts.items())) + f" (totale {len(sim)} coppie)")
        cross_pattern_dupes = [
            r for r in sim
            if r["pattern_a"] != r["pattern_b"] and r["label"] in ("DUPLICATE", "NEAR_DUPLICATE")
        ]
        if cross_pattern_dupes:
            L.append("")
            L.append(
                "**Coppie DUPLICATE/NEAR_DUPLICATE tra pattern DIVERSI** (non semplice "
                "versione dello stesso skill -- segnale che la compressione puo' aver "
                "eroso le differenze specifiche del pattern, o che i due pattern sono "
                "concettualmente piu' vicini di quanto la tassonomia assuma):"
            )
            for r in cross_pattern_dupes:
                L.append(f"  - `{r['pattern_a']}`/`{r['book_a']}` <-> `{r['pattern_b']}`/`{r['book_b']}`: "
                          f"{r['label']} -- {r['reasoning']}")
    L.append("")

    # genealogy (Phase 4) -------------------------------------------------
    L.append("## Genealogia")
    L.append(
        "`derived_from` (compressione meccanica -- dalla convenzione di naming "
        "dell'optimizer) e `duplicate_of`/`related_skills` (solo il caso "
        "informativo cross-pattern -- vedi Similarity sopra) sui file attuali."
    )
    L.append("")
    genealogy_rows = [
        b for b in load_books()
        if b.derived_from or b.duplicate_of or b.related_skills
    ]
    if not genealogy_rows:
        L.append("- Nessun dato (lancia `similarity_check.bat`, fa anche il backfill).")
    else:
        L.append("| book | derived_from | duplicate_of | related_skills |")
        L.append("|---|---|---|---|")
        for b in sorted(genealogy_rows, key=lambda b: b.id):
            L.append(
                f"| `{b.id}` | {b.derived_from or '-'} | {b.duplicate_of or '-'} | "
                f"{', '.join(b.related_skills) or '-'} |"
            )
    L.append("")

    # economic classification (Phase 3) -----------------------------------
    L.append("## Classificazione economica")
    L.append(
        "Due assi per pattern: **accuracy_value** = HIGH se F ha davvero salvato "
        "un fallimento di A o B su un task di quel pattern (non solo \"F ha "
        "accuracy alta\" in astratto); **economic_value** = HIGH se il risparmio "
        "e' positivo e il breakeven e' entro 20 usi (soglia dichiarata in "
        "`economics.py`, non nascosta). **NEGATIVE non significa \"elimina\"** -- "
        "puo' avere valore strategico non catturato da queste due metriche con "
        "cosi' pochi dati."
    )
    L.append("")
    econ_rows = economics.economic_classification(experiment_id)
    if not econ_rows:
        L.append("- Nessun dato (serve almeno una compressione + un retrieval per lo stesso pattern).")
    else:
        L.append("| pattern | accuracy_value | economic_value | classificazione |")
        L.append("|---|---|---|---|")
        for r in econ_rows:
            L.append(f"| `{r['pattern']}` | {r['accuracy_value']} | {r['economic_value']} | {r['label']} |")
    L.append("")

    density = economics.library_density()
    L.append("## Library usefulness (densita' di conoscenza utile)")
    if density is None:
        L.append("- Non calcolabile finche' il Similarity Checker non e' stato lanciato.")
    else:
        L.append(
            f"- {density['n_clusters']} contenuti distinti su {density['n_files']} file "
            f"su disco -> densita' {density['density']:.0%} (spec #21: il numero di skill "
            f"non e' la metrica giusta, questa lo e')."
        )
        if density["clusters"]:
            L.append("- Cluster di duplicati diretti trovati:")
            for cluster in density["clusters"]:
                L.append(f"  - {', '.join(f'`{c}`' for c in cluster)}")
    L.append("")

    growth = _library_growth()
    if growth:
        L.append("## Crescita della libreria (snapshot nel tempo)")
        L.append("| snapshot | n. book |")
        L.append("|---|---|")
        for g in growth:
            L.append(f"| `{g['label']}` | {g['n_books']} |")
        L.append("")

    return "\n".join(L) + "\n"


def write_knowledge_map(experiment_id: str) -> Path:
    text = build_knowledge_map(experiment_id)
    out_path = config.experiment_dir(experiment_id) / "knowledge_map.md"
    out_path.write_text(text, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    experiment_id = sys.argv[1] if len(sys.argv) > 1 else config.get_current_experiment_id()
    path = write_knowledge_map(experiment_id)
    print(f"[knowledge_map] scritto {path}")
