"""Snapshots the live skill library (library/books/) into
library/snapshots/{label}/, so a later run can be pointed at a known, frozen
state instead of whatever the library happens to look like by then.

Why this exists (conversation 2026-08-18): the library is ONE shared folder,
never scoped to an experiment_id -- every experiment_id reads/writes the same
live library.books/. That means a new experiment doesn't start from a clean
baseline: it inherits every accepted optimizer compression and every manual
fix made so far. Comparing "library before vs after the optimizer" only means
something if the "before" state is actually frozen somewhere, not just
whatever experiment0/experiment1 happened to leave behind.

Run: python -m cognitive_rpg.library.snapshot [label]
  label defaults to a UTC timestamp if omitted.

To run a future experiment against a snapshot instead of the live library
(Windows, same shell, before the python command):
  set LIBRARY_DIR_OVERRIDE=<path printed by this script>
  python -m cognitive_rpg.experiment.experiment_0 <experiment_id>
"""

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import config

SNAPSHOTS_DIR = Path(__file__).resolve().parent / "snapshots"


def snapshot(label: str | None = None) -> Path:
    label = label or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = SNAPSHOTS_DIR / label
    if out_dir.exists():
        raise FileExistsError(f"snapshot '{label}' esiste gia': {out_dir}")
    shutil.copytree(config.LIBRARY_DIR, out_dir)
    return out_dir


def list_snapshots() -> list[Path]:
    if not SNAPSHOTS_DIR.exists():
        return []
    return sorted(p for p in SNAPSHOTS_DIR.iterdir() if p.is_dir())


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else None
    out_dir = snapshot(label)
    n_books = len(list(out_dir.glob("*.yaml")))
    print(f"[snapshot] {n_books} book salvati in {out_dir}")
    print(f"[snapshot] per usarla in un run futuro:")
    print(f"  set LIBRARY_DIR_OVERRIDE={out_dir}")
    print(f"  python -m cognitive_rpg.experiment.experiment_0 <experiment_id>")
