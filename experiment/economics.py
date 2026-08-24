"""Economic classification (Phase 3 of the library evolution plan,
conversation 2026-08-18). Almost entirely reuse: skill_amortization() and
token_accounting() (experiment/metrics.py, Phase 1) already compute
everything needed here -- this module just derives a label from numbers that
already exist, plus one small new computation (library density) that reuses
Phase 2's similarity results. No new LLM calls, no change to any live
behavior.

TWO AXES, per bug-pattern (spec #14):
  ACCURACY VALUE  -- HIGH if F actually rescued a failure: does at least one
    (task_id, split) covered by this pattern exist where A or B failed and
    F passed? This is deliberately about ACTUAL rescued failures, not
    "F's accuracy is high" in the abstract -- a pattern where A/B/F all pass
    every task has HIGH raw accuracy for everyone but the skill made no real
    difference, which is LOW accuracy_value by this definition.
  ECONOMIC VALUE  -- HIGH if metrics.skill_amortization's saving>0 AND
    breakeven <= _ECONOMIC_BREAKEVEN_THRESHOLD (a stated, not hidden,
    cutoff -- default 20 uses, arbitrary but explicit and overridable).

FINAL LABEL (spec #14's four categories, derived from the two axes above --
economic HIGH takes priority when both are HIGH, since spec #14's own
example is "a skill can be useful for reliability even when NOT more
economical", i.e. accuracy_value is the fallback reason to keep something,
not the primary one):
  ECONOMICALLY_POSITIVE -- economic_value HIGH (regardless of accuracy_value)
  ACCURACY_POSITIVE     -- economic_value LOW, accuracy_value HIGH
  NEGATIVE              -- both LOW
  NEUTRAL               -- insufficient data (no A/F or no build_cost data)
Per spec #14: NEGATIVE must NOT be read as "delete this skill" -- it may
still have strategic/reliability value not captured by these two axes with
this little data. This module only labels, it doesn't act.

LIBRARY DENSITY (spec #16/#21: "useful knowledge density", not skill count):
  density = distinct_content_clusters / n_files_on_disk, where a cluster is
  a connected component of DUPLICATE edges from Phase 2's similarity report
  (files A-B-C where A~B and B~C via DUPLICATE all collapse to one cluster,
  even without a direct A~C edge). NEAR_DUPLICATE/RELATED/DISTINCT don't
  merge clusters -- only DUPLICATE does, since those are the pairs the spec
  says shouldn't have been kept as two separate entries in the first place.
"""

import sys
from collections import defaultdict

import yaml

from .. import config
from . import metrics
from .events import read_events, read_events_all_experiments
from .experiment_log import read_all

_ECONOMIC_BREAKEVEN_THRESHOLD = 20.0  # uses; stated explicitly, not hidden


def _accuracy_rescued(pattern: str, records, tasks_by_id) -> bool:
    by_task_cfg = {(r["task_id"], r["config_name"]): r["passed"] for r in records}
    task_ids = {tid for tid, t in tasks_by_id.items() if t.pattern_id == pattern}
    for task_id in task_ids:
        f_passed = by_task_cfg.get((task_id, "F"))
        if not f_passed:
            continue
        a_passed = by_task_cfg.get((task_id, "A"))
        b_passed = by_task_cfg.get((task_id, "B"))
        if a_passed is False or b_passed is False:
            return True
    return False


def economic_classification(experiment_id: str) -> list[dict]:
    from ..domain.task_generator import generate_tasks
    records = read_all(experiment_id)
    events = read_events(experiment_id)
    tasks_by_id = {t.task_id: t for t in generate_tasks(seed=42)}

    rows = []
    for row in metrics.skill_amortization(events, records, build_cost_events=read_events_all_experiments()):
        pattern = row["pattern"]
        accuracy_value = "HIGH" if _accuracy_rescued(pattern, records, tasks_by_id) else "LOW"
        economic_value = (
            "HIGH" if row["saving"] > 0 and row["breakeven"] is not None
            and row["breakeven"] <= _ECONOMIC_BREAKEVEN_THRESHOLD
            else "LOW"
        )
        if economic_value == "HIGH":
            label = "ECONOMICALLY_POSITIVE"
        elif accuracy_value == "HIGH":
            label = "ACCURACY_POSITIVE"
        else:
            label = "NEGATIVE"
        rows.append({
            "pattern": pattern, "accuracy_value": accuracy_value,
            "economic_value": economic_value, "label": label,
            "breakeven": row["breakeven"], "saving": row["saving"],
        })
    return rows


def library_density() -> dict | None:
    """None if the Similarity Checker hasn't run yet (Phase 2).

    n_files/clusters are scoped to the CURRENT live library (load_books()),
    not to every id similarity_report.yaml has ever mentioned. Files archived
    out of books/ (see librarian/archive_duplicates.py) stop counting against
    the denominator immediately, without needing a fresh (paid) Similarity
    Checker run first -- otherwise archiving duplicates would never move this
    number until the next re-run, defeating the point of tracking it (found
    2026-08-18: this was the original bug behind density looking "stuck")."""
    path = config.LIBRARY_DIR.parent / "similarity_report.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    pairs = data.get("pairs", [])

    from ..library.loader import load_books
    live_ids = {b.id for b in load_books()}
    if not live_ids:
        return None
    parent = {b: b for b in live_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for r in pairs:
        if r["label"] == "DUPLICATE" and r["book_a"] in live_ids and r["book_b"] in live_ids:
            union(r["book_a"], r["book_b"])

    clusters = defaultdict(set)
    for b in live_ids:
        clusters[find(b)].add(b)

    n_files = len(live_ids)
    n_clusters = len(clusters)
    return {
        "n_files": n_files, "n_clusters": n_clusters,
        "density": n_clusters / n_files if n_files else None,
        "clusters": [sorted(members) for members in clusters.values() if len(members) > 1],
    }
