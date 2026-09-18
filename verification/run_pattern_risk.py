"""Real run of the unified dispatcher (pattern_risk.py) against a live Book.
Run: python -m cognitive_rpg.verification.run_pattern_risk <pattern_id>
(requires the local Gemma server already running)."""

import sys

from .. import config
from ..adapters.factory import build_adapter
from ..adapters.gemma_adapter import GemmaAdapter
from ..librarian.librarian import _latest_per_pattern
from ..library.loader import load_books
from .pattern_risk import check_pattern_risk


def main() -> int:
    # Vedi run_method_repair.py: console Windows in cp1252, testo generato
    # puo' contenere Unicode reale -- niente UnicodeEncodeError a meta' run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("uso: python -m cognitive_rpg.verification.run_pattern_risk <pattern_id>")
        return 1
    pattern_id = sys.argv[1]
    # _latest_per_pattern, non load_books() grezzo -- stesso bug reale
    # trovato in run_method_repair.py (2026-09-17): un next() sulla lista
    # piatta puo' prendere una versione vecchia e stale per puro ordine
    # alfabetico dei file.
    book = next((b for b in _latest_per_pattern(load_books()) if b.pattern_id == pattern_id), None)
    if book is None:
        print(f"[pattern-risk] nessun Book live per pattern {pattern_id!r}")
        return 1

    expert = build_adapter("expert")
    gemma = GemmaAdapter(model=config.GEMMA_MODEL)
    print(f"[pattern-risk] Expert: {expert.PROVIDER}/{getattr(expert, 'model', '?')}")
    print(f"[pattern-risk] modello sotto test: {gemma.PROVIDER}/{gemma.model}")
    print(f"[pattern-risk] Book: {book.id} (v{book.version})")

    result = check_pattern_risk("verification_pattern_risk", book, expert, gemma)
    print(f"\n[pattern-risk] asse usato: {result.axis}")
    print(f"[pattern-risk] VERDETTO: {result.verdict}")
    print(f"[pattern-risk] dettaglio: {result.detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
