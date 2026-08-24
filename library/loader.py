from functools import lru_cache
from pathlib import Path

import yaml

from .. import config
from ..models import Book


def _load_books_from(directory: Path) -> list[Book]:
    books = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        books.append(
            Book(
                id=data["id"],
                version=data["version"],
                title=data["title"],
                domain=data["domain"],
                problem_tags=data["problem_tags"],
                capability_tags=data["capability_tags"],
                resource_tags=data["resource_tags"],
                procedure_text=data["procedure_text"],
                pattern_id=data["pattern_id"],
                canonical_problem_id=data["canonical_problem_id"],
                status=data["status"],
                confidence=data["confidence"],
                verification_count=data["verification_count"],
                verification_types=data["verification_types"],
                # .get() with defaults, not data[...]: these fields were
                # added in Phase 4 (2026-08-18), after most existing YAML
                # files were written -- data[key] here would break every
                # file predating this change.
                derived_from=data.get("derived_from"),
                duplicate_of=data.get("duplicate_of"),
                related_skills=data.get("related_skills", []),
                parent_skills=data.get("parent_skills", []),
                supersedes=data.get("supersedes"),
                superseded_by=data.get("superseded_by"),
                generation_method=data.get("generation_method", "manual"),
            )
        )
    return books


@lru_cache(maxsize=1)
def load_books() -> list[Book]:
    """The LIVE, routable library -- what the Librarian actually retrieves
    from. Never includes archived_books/ (see load_archived_books)."""
    return _load_books_from(config.LIBRARY_DIR)


@lru_cache(maxsize=1)
def load_archived_books() -> list[Book]:
    """Confirmed-duplicate Books moved out of the live library (Similarity
    Checker, Phase 2/3, conversation 2026-08-18) -- never routable, but kept
    on disk because historical events.jsonl entries still reference their
    ids for cost attribution (see experiment/metrics.py's books_by_id, which
    unions this with load_books() specifically for that lookup)."""
    if not config.ARCHIVED_BOOKS_DIR.exists():
        return []
    return _load_books_from(config.ARCHIVED_BOOKS_DIR)


def id_to_pattern_map() -> dict[str, str]:
    """live + archived -- for resolving a historical skill_id to its
    pattern_id even if that exact Book file is no longer in the live
    library. Routing (_latest_per_pattern) must NOT use this -- only use
    load_books() directly for anything that affects retrieval."""
    books = load_books() + load_archived_books()
    return {b.id: b.pattern_id for b in books}


def library_pattern_ids() -> set[str]:
    return {book.pattern_id for book in load_books()}
