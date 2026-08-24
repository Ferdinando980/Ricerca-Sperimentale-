"""Similarity Checker (Phase 2 of the library evolution plan, conversation
2026-08-18: mandatory per spec before accepting any new skill, since no
Skill Generator exists yet this module runs as a standalone AUDIT of the
library that already exists on disk -- specifically to check whether the
version proliferation already visible there (e.g.
book_index_out_of_range_boundary_v2.yaml vs ..._v2_v3.yaml) is real
DUPLICATE content or genuinely DISTINCT).

WHO judges: the Small-role adapter (same precedent as optimizer.py: the
model that will actually use these skills, not a separate "editor" role),
via a pairwise LLM-as-judge prompt -- NOT plain text similarity. The prompt
explicitly asks for meaning (bug pattern / triggering condition / solution /
expected behavior), since two Books can be near-identical in meaning while
worded completely differently, or share vocabulary while addressing
different bugs.

SCOPE (deliberately not all-pairs -- 22 files would be 231 pairs, mostly
uninformative "unrelated pattern -> DISTINCT"):
  1. Within-pattern: every pair of on-disk versions of the SAME pattern_id
     (this is the real question -- is the _v2/_v2_v3 proliferation actual
     duplication?).
  2. Cross-pattern within-section: the LATEST version of each pattern,
     compared against the latest version of every OTHER pattern in the same
     section (library/sections.py, Phase 1) -- this is what "potenzialmente
     rilevanti" (spec #8) means in practice at this library size: skills in
     the same macro-area are the ones worth checking for RELATED links, not
     the whole library.

CLASSIFICATION LABELS (spec #8): DUPLICATE, NEAR_DUPLICATE, RELATED,
DISTINCT. This module only CLASSIFIES and REPORTS -- it does not act on the
result (spec #9's duplicate policy -- link instead of create, merge
variants, etc. -- has no Skill Generator to gate yet; automating the
DUPLICATE/NEAR_DUPLICATE response is explicitly deferred per the plan, a
human reading the report is the right amount of automation at 8 patterns).

GENEALOGY BACKFILL (Phase 4, added 2026-08-18): backfill_genealogy() writes
Book.derived_from/duplicate_of/related_skills onto EXISTING on-disk YAML
files -- only those genealogy fields, id/version/procedure_text/etc. stay
byte-identical. derived_from comes from the id naming convention
save_compressed_book() already uses ("{original_id}_v{n}"), not from this
module's own classification. duplicate_of/related_skills come from THIS
run's similarity results, but only record duplicate_of for the informative
case (cross-pattern) -- a within-pattern DUPLICATE is already fully
explained by derived_from, recording it again would be noise. Idempotent:
re-running after a fresh similarity_check.bat pass just overwrites with
current data, never accumulates duplicates in related_skills.

Run: python -m cognitive_rpg.librarian.similarity
Writes cognitive_rpg/library/similarity_report.yaml and backfills genealogy
fields into cognitive_rpg/library/books/*.yaml, then prints a summary.
"""

import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import yaml

from .. import config
from ..adapters import build_adapter
from ..library import sections as sections_mod
from ..library.loader import load_books
from .librarian import _latest_per_pattern

VALID_LABELS = {"DUPLICATE", "NEAR_DUPLICATE", "RELATED", "DISTINCT"}

_SIMILARITY_SYSTEM_PROMPT = (
    "You compare two debugging procedures (\"Books\") from a shared knowledge "
    "library and classify their relationship. Judge by MEANING, not wording: "
    "the bug pattern/concept each addresses, the triggering condition, the "
    "solution/procedure, and the expected behavior after the fix. Two books "
    "can be near-identical in meaning while using completely different "
    "words, or share vocabulary while addressing different bugs -- judge on "
    "substance. Classify as exactly one of:\n"
    "DUPLICATE -- same bug pattern, same solution, no real difference worth "
    "keeping both as separate entries.\n"
    "NEAR_DUPLICATE -- same underlying pattern but a meaningfully different "
    "scope, wording, or coverage -- worth a human decision on merging.\n"
    "RELATED -- different bug pattern but real shared conceptual ground "
    "(e.g. same broader domain, or a common root cause).\n"
    "DISTINCT -- unrelated.\n"
    "Reply with EXACTLY two lines: the label alone on line 1, one short "
    "sentence of reasoning on line 2. No other text, no preamble."
)


def classify_pair(book_a, book_b, adapter) -> dict:
    prompt = (
        f"Book A -- \"{book_a.title}\" (pattern: {book_a.pattern_id}):\n{book_a.procedure_text.strip()}\n\n"
        f"Book B -- \"{book_b.title}\" (pattern: {book_b.pattern_id}):\n{book_b.procedure_text.strip()}"
    )
    result = adapter.complete(prompt=prompt, system=_SIMILARITY_SYSTEM_PROMPT, max_tokens=200)
    lines = [l.strip() for l in result.text.strip().splitlines() if l.strip()]
    label = lines[0].upper() if lines else ""
    reasoning = lines[1] if len(lines) > 1 else ""
    if label not in VALID_LABELS:
        reasoning = f"[unparseable label {label!r}] {result.text.strip()}"
        label = "UNPARSEABLE"
    return {
        "book_a": book_a.id, "book_b": book_b.id,
        "pattern_a": book_a.pattern_id, "pattern_b": book_b.pattern_id,
        "label": label, "reasoning": reasoning,
    }


def _within_pattern_pairs() -> list[tuple]:
    all_books = load_books()
    by_pattern = {}
    for b in all_books:
        by_pattern.setdefault(b.pattern_id, []).append(b)
    pairs = []
    for pattern_id, books in by_pattern.items():
        books_sorted = sorted(books, key=lambda b: b.id)
        pairs.extend(combinations(books_sorted, 2))
    return pairs


def _cross_pattern_within_section_pairs() -> list[tuple]:
    latest_by_pattern = {b.pattern_id: b for b in _latest_per_pattern(load_books())}
    pairs = []
    for section_id in sections_mod.all_sections():
        pattern_ids = [p for p in sections_mod.patterns_in_section(section_id) if p in latest_by_pattern]
        for pa, pb in combinations(sorted(pattern_ids), 2):
            pairs.append((latest_by_pattern[pa], latest_by_pattern[pb]))
    return pairs


def check_library(adapter=None) -> list[dict]:
    adapter = adapter or build_adapter("small")
    pairs = _within_pattern_pairs() + _cross_pattern_within_section_pairs()
    return [classify_pair(a, b, adapter) for a, b in pairs]


def write_similarity_report(results: list[dict], out_path: Path | None = None) -> Path:
    out_path = out_path or (config.LIBRARY_DIR.parent / "similarity_report.yaml")
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_pairs": len(results),
        "pairs": results,
    }
    out_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out_path


_DERIVED_FROM_RE = re.compile(r"^(.*)_v(\d+)$")


def _derived_from_for(book_id: str) -> str | None:
    m = _DERIVED_FROM_RE.match(book_id)
    return m.group(1) if m else None


def backfill_genealogy(results: list[dict]) -> list[Path]:
    duplicate_of: dict[str, str] = {}
    related: dict[str, set] = defaultdict(set)
    for r in results:
        if r["label"] == "DUPLICATE":
            # Skip the expected case (same pattern_id -- a book and its own
            # compression, however many generations apart, SHOULD look like
            # duplicates; that's already explained by derived_from and isn't
            # informative). Only record duplicate_of for the informative
            # case: DIFFERENT patterns that still collapsed into the same
            # content. Comparing pattern_id (not a single-hop derived_from
            # check) so this is correct even when an intermediate version
            # was archived and is no longer the direct derived_from parent.
            if r["pattern_a"] == r["pattern_b"]:
                continue
            duplicate_of.setdefault(r["book_a"], r["book_b"])
            duplicate_of.setdefault(r["book_b"], r["book_a"])
        elif r["label"] == "RELATED":
            related[r["book_a"]].add(r["book_b"])
            related[r["book_b"]].add(r["book_a"])

    updated = []
    for path in sorted(config.LIBRARY_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        book_id = data["id"]
        changed = False

        # Authoritative, not patch-in-only: every field below is set to
        # exactly what this run's data says, including clearing a stale
        # value from a previous run whose classification no longer applies
        # (found in practice: a bug in an earlier version of this function
        # left a stale cross-pattern duplicate_of on integer_division_
        # truncation after the pattern_a==pattern_b skip logic was fixed --
        # a patch-only update can never self-correct that, only an
        # authoritative one can).
        d_from = _derived_from_for(book_id)
        if data.get("derived_from") != d_from:
            data["derived_from"] = d_from
            changed = True

        new_duplicate_of = duplicate_of.get(book_id)
        if data.get("duplicate_of") != new_duplicate_of:
            data["duplicate_of"] = new_duplicate_of
            changed = True

        new_related = sorted(related.get(book_id, set()))
        if sorted(data.get("related_skills", [])) != new_related:
            data["related_skills"] = new_related
            changed = True

        if changed:
            path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
            updated.append(path)
    return updated


if __name__ == "__main__":
    results = check_library()
    path = write_similarity_report(results)
    counts = {label: sum(1 for r in results if r["label"] == label) for label in VALID_LABELS | {"UNPARSEABLE"}}
    print(f"[similarity] {len(results)} coppie classificate -> {path}")
    for label, n in counts.items():
        if n:
            print(f"  {label}: {n}")
    dupes = [r for r in results if r["label"] in ("DUPLICATE", "NEAR_DUPLICATE")]
    if dupes:
        print("\n[similarity] coppie DUPLICATE/NEAR_DUPLICATE (revisione manuale consigliata):")
        for r in dupes:
            print(f"  {r['book_a']} <-> {r['book_b']}: {r['label']} -- {r['reasoning']}")

    updated = backfill_genealogy(results)
    print(f"\n[similarity] genealogia aggiornata su {len(updated)} file:")
    for p in updated:
        print(f"  {p.name}")
