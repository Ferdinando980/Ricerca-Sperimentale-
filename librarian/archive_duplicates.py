"""Moves confirmed-superseded Book files out of the live library into
archived_books/ (conversation 2026-08-18: library density stuck at 29% -- 31
files on disk for 10 "current" skills -- because nothing ever retired the
older versions the Optimizer leaves behind every time it compresses a Book).

Never deletes anything (see library/loader.py's load_archived_books -- moved
files stay resolvable for historical events.jsonl cost attribution via
id_to_pattern_map, they just stop being routable). Only moves a file when
BOTH are true:
  1. It is NOT the highest-version Book for its pattern_id (i.e. _latest_per_
     pattern, the exact same "current skill" logic route() uses, doesn't pick
     it) -- so it is structurally superseded within its own version chain.
  2. The Similarity Checker (library/similarity_report.yaml) has a DUPLICATE
     edge between it and the CURRENT winner for that same pattern_id -- not
     just "some DUPLICATE edge to something", specifically to the winner, so
     a file that happens to be an older version AND was never actually
     confirmed equivalent-content to the new one is left alone for manual
     review instead of silently archived.
A pattern with no confirmed edge to its winner is reported but left in place.

Run: python -m cognitive_rpg.librarian.archive_duplicates
Costo: no (nessuna chiamata ai modelli -- solo file locali + similarity_report.yaml
gia' su disco; rilancia prima similarity_check.bat se quel file e' vecchio).
"""

import sys

import yaml

from .. import config
from ..library.loader import load_books
from .librarian import _latest_per_pattern


def _similarity_pairs() -> list[dict]:
    path = config.LIBRARY_DIR.parent / "similarity_report.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("pairs", [])


def _duplicate_edges(pairs: list[dict]) -> set[frozenset[str]]:
    return {
        frozenset((r["book_a"], r["book_b"]))
        for r in pairs
        if r["label"] == "DUPLICATE"
    }


def plan_archival() -> tuple[list[tuple[str, str]], list[str]]:
    """Returns (to_archive, skipped) where to_archive is [(book_id, winner_id), ...]
    and skipped is book_ids that are superseded but have no confirmed DUPLICATE
    edge to their pattern's current winner (left for manual review)."""
    books = load_books()
    winners = {b.pattern_id: b.id for b in _latest_per_pattern(books)}
    dup_edges = _duplicate_edges(_similarity_pairs())

    to_archive = []
    skipped = []
    for book in books:
        winner_id = winners.get(book.pattern_id)
        if winner_id is None or book.id == winner_id:
            continue
        if frozenset((book.id, winner_id)) in dup_edges:
            to_archive.append((book.id, winner_id))
        else:
            skipped.append(book.id)
    return to_archive, skipped


def archive(dry_run: bool = False) -> None:
    to_archive, skipped = plan_archival()
    if not to_archive and not skipped:
        print("[archive_duplicates] nessun file superato trovato -- libreria gia' pulita.")
        return

    id_conflicts = []
    moved = []
    if to_archive:
        config.ARCHIVED_BOOKS_DIR.mkdir(parents=True, exist_ok=True)
        # id -> source path, found by parsing each file's own "id" field
        # (Book doesn't carry its path -- see models.py) rather than assuming
        # filename == id, since the Optimizer's naming (book_X_v2_v3.yaml) has
        # drifted from a strict id-based scheme in places.
        id_to_path = {}
        for path in config.LIBRARY_DIR.glob("*.yaml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            id_to_path[data["id"]] = path

        for book_id, winner_id in to_archive:
            src = id_to_path.get(book_id)
            if src is None:
                print(f"[archive_duplicates] ATTENZIONE: id {book_id} non trovato su disco, salto.")
                continue
            dest = config.ARCHIVED_BOOKS_DIR / src.name
            if dest.exists():
                # A different file with the SAME id is already archived under
                # this name (found 2026-08-18: book_index_out_of_range_boundary_v2
                # exists in both books/ and archived_books/ with different
                # procedure_text -- an id collision, not a re-archive of the
                # same file). Don't overwrite silently; needs a human decision.
                id_conflicts.append(src.name)
                continue
            print(f"[archive_duplicates] {'(dry-run) ' if dry_run else ''}{src.name} "
                  f"-> archived_books/ (DUPLICATE di {winner_id})")
            moved.append(src.name)
            if not dry_run:
                src.rename(dest)

    if id_conflicts:
        print(
            f"\n[archive_duplicates] ATTENZIONE -- {len(id_conflicts)} file NON spostati: "
            "esiste gia' un file DIVERSO con lo stesso id in archived_books/ (id duplicato, "
            "non lo stesso file archiviato due volte). Richiede una decisione manuale:"
        )
        for name in id_conflicts:
            print(f"  - {name}")

    if skipped:
        print(
            f"\n[archive_duplicates] {len(skipped)} file superati ma SENZA edge DUPLICATE "
            "confermato verso il winner del loro pattern -- lasciati sul posto, revisione manuale:"
        )
        for book_id in skipped:
            print(f"  - {book_id}")

    print(f"\n[archive_duplicates] {'simulati' if dry_run else 'archiviati'}: {len(moved)} file.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    archive(dry_run=dry_run)
