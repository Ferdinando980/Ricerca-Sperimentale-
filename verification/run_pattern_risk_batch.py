"""Extends today's real coverage: the unified dispatcher (pattern_risk.py)
tries BOTH the numeric-rule axis AND the method-trap axis, so it can catch
risk in patterns the earlier library_benchmark.py run (numeric axis only)
reported as NO_SLOT -- that result only ever meant "no LITERAL value to
substitute", never "no risk of any kind" (the exact distinction the user
pushed back on for wrong_string_case_comparison, which turned out to have a
real, execution-verified method-substitution risk).

Re-runs every pattern that came back NO_SLOT in logs/verification_benchmark_
2026_09_17b/verification_benchmark.json through the full dispatcher, so
patterns that are actually method-based (a fixed procedural choice, not a
literal example) finally get a real test instead of being left as an
untested negative.

Run: python -m cognitive_rpg.verification.run_pattern_risk_batch [pattern_id ...]
With no arguments, defaults to every NO_SLOT pattern from the last real
library_benchmark.py run on disk."""

import json
import sys
from dataclasses import asdict

from .. import config
from ..adapters.factory import build_adapter
from ..adapters.gemma_adapter import GemmaAdapter
from ..librarian.librarian import _latest_per_pattern
from ..library.loader import load_books
from .pattern_risk import check_pattern_risk

_DEFAULT_SOURCE = config.experiment_dir("verification_benchmark_2026_09_17b") / "verification_benchmark.json"


def _default_patterns() -> list[str]:
    if not _DEFAULT_SOURCE.exists():
        return []
    data = json.loads(_DEFAULT_SOURCE.read_text(encoding="utf-8"))
    return [o["pattern_id"] for o in data if o["status"] == "NO_SLOT"]


def main() -> int:
    # Vedi run_method_repair.py: console Windows in cp1252, testo generato
    # puo' contenere Unicode reale -- niente UnicodeEncodeError a meta' run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    patterns = sys.argv[1:] or _default_patterns()
    if not patterns:
        print("[pattern-risk-batch] nessun pattern da testare (nessun argomento e nessun NO_SLOT trovato nel run di riferimento)")
        return 1

    # _latest_per_pattern esplicito -- prima funzionava per coincidenza
    # dell'ordine alfabetico dei file ("_v2_v3" < "_v2_v3_v4"), non per
    # garanzia: stesso bug di classe trovato dal vivo in run_method_repair.py.
    books_by_pattern = {b.pattern_id: b for b in _latest_per_pattern(load_books())}
    expert = build_adapter("expert")
    gemma = GemmaAdapter(model=config.GEMMA_MODEL)
    print(f"[pattern-risk-batch] Expert: {expert.PROVIDER}/{getattr(expert, 'model', '?')}")
    print(f"[pattern-risk-batch] modello sotto test: {gemma.PROVIDER}/{gemma.model}")
    print(f"[pattern-risk-batch] pattern da testare: {patterns}")

    results = []
    for pattern_id in patterns:
        book = books_by_pattern.get(pattern_id)
        if book is None:
            print(f"\n[pattern-risk-batch] {pattern_id}: nessun Book live -- saltato")
            continue
        print(f"\n[pattern-risk-batch] === {pattern_id} ({book.id} v{book.version}) ===")
        result = check_pattern_risk("verification_pattern_risk_batch", book, expert, gemma)
        print(f"[pattern-risk-batch] asse: {result.axis} -- verdetto: {result.verdict} -- {result.detail}")
        results.append(result)

    out_path = config.experiment_dir("verification_pattern_risk_batch") / "pattern_risk_batch.json"
    out_path.write_text(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[pattern-risk-batch] {len(results)} pattern testati, report in {out_path}")
    by_axis: dict[str, int] = {}
    for r in results:
        by_axis[f"{r.axis}:{r.verdict}"] = by_axis.get(f"{r.axis}:{r.verdict}", 0) + 1
    for key, count in sorted(by_axis.items()):
        print(f"  {key}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
