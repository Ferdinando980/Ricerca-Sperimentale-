"""Audit mode (see the plan, Workstream A point 7) -- same slot-identification
engine as library_benchmark.py, applied to a small, FIXED set of static
instruction strings already written into the app's own code (not the Book
library, which grows and is covered by library_benchmark.py instead). Run on
request, not as a continuous pipeline: these constants change rarely, and
scanning them costs a handful of Expert calls, not a sweep worth automating
into every run.

Registered here are the 5 fixed system-prompt constants that shape every
model call in this codebase:
  - agents.worker.SYSTEM_PROMPT -- every Worker completion, any task.
  - librarian.optimizer._COMPRESSION_SYSTEM_PROMPT /
    _CONTENT_PRESERVATION_SYSTEM_PROMPT -- every compression/re-verification.
  - librarian.similarity._SIMILARITY_SYSTEM_PROMPT -- every duplicate/near-
    duplicate judgment.
  - librarian.skill_generator._GENERATION_SYSTEM_PROMPT -- every new Book
    written for a coverage gap.

Deliberately read-only / report-only, unlike library_benchmark.py's
repair_skill step: these are Python source constants, not versioned Book
YAML files -- there is no safe automated "save a new version alongside the
original" for a string literal in application code the way there is for a
Book. A slot found here is a finding for a human to act on by editing the
source, not something this script rewrites itself.

Full ablation (not just identify_slot) is only attempted for a target where
a slot IS actually found -- direct reading of all 5 constants before writing
this module found no illustrative numeric/literal example in any of them
(they are all pure format/procedure meta-instructions, unlike a Book's
procedure_text which by design often includes a worked example) — so NO_SLOT
across the board is the expected, honestly-reported outcome, not evidence
the audit didn't run. If a future edit to one of these constants adds a
concrete example, rerun this to check it.

Run: python -m cognitive_rpg.verification.static_audit
Writes logs/static_audit/static_audit_report.json (fixed experiment_id --
this is a standing audit target, not a per-run experiment)."""

import json
import sys
from dataclasses import asdict, dataclass

from .. import config
from ..adapters.factory import build_adapter
from ..agents.worker import SYSTEM_PROMPT
from ..librarian.optimizer import _COMPRESSION_SYSTEM_PROMPT
from ..librarian.similarity import _SIMILARITY_SYSTEM_PROMPT
from ..librarian.skill_generator import _GENERATION_SYSTEM_PROMPT
from . import slot_identifier
from .stabilizer import _CONTENT_PRESERVATION_SYSTEM_PROMPT

_EXPERIMENT_ID = "static_audit"

TARGETS = {
    "worker.SYSTEM_PROMPT": SYSTEM_PROMPT,
    "optimizer._COMPRESSION_SYSTEM_PROMPT": _COMPRESSION_SYSTEM_PROMPT,
    "optimizer._CONTENT_PRESERVATION_SYSTEM_PROMPT": _CONTENT_PRESERVATION_SYSTEM_PROMPT,
    "similarity._SIMILARITY_SYSTEM_PROMPT": _SIMILARITY_SYSTEM_PROMPT,
    "skill_generator._GENERATION_SYSTEM_PROMPT": _GENERATION_SYSTEM_PROMPT,
}


@dataclass
class StaticAuditFinding:
    target: str
    has_slot: bool
    slot_name: str | None = None
    original_value: str | None = None
    alt_values: list[str] | None = None
    note: str = ""


def run_audit() -> list[StaticAuditFinding]:
    expert = build_adapter("expert")
    print(f"[static-audit] Expert (identificazione): {expert.PROVIDER}/{getattr(expert, 'model', '?')}")
    findings: list[StaticAuditFinding] = []
    for name, text in TARGETS.items():
        print(f"\n[static-audit] === {name} ===")
        slot = slot_identifier.identify_slot(text, name, expert)
        if slot is None:
            findings.append(StaticAuditFinding(
                target=name, has_slot=False,
                note="nessun letterale sostituibile identificato (atteso per un'istruzione di formato/procedura, "
                     "non un esempio con valori concreti)",
            ))
            print(f"[static-audit] {name}: nessuno slot identificato")
        else:
            findings.append(StaticAuditFinding(
                target=name, has_slot=True, slot_name=slot.slot_name,
                original_value=slot.original_value, alt_values=slot.alt_values,
                note="SLOT TROVATO -- questa e' una costante nel codice dell'app, non un Book: nessuna riparazione "
                     "automatica verra' tentata. Un umano deve valutare se riscrivere questa stringa a mano; vedere "
                     "gli alt_values per un'idea di quale letterale manipolare per verificare il rischio con "
                     "substitution_ablation.py se si vuole procedere.",
            ))
            print(f"[static-audit] {name}: SLOT TROVATO -- {slot.slot_name!r} = {slot.original_value!r} "
                  f"(alternative suggerite: {slot.alt_values}) -- richiede revisione umana, non riparazione automatica")
    return findings


def main() -> int:
    # Vedi run_method_repair.py: console Windows in cp1252, testo generato
    # puo' contenere Unicode reale -- niente UnicodeEncodeError a meta' run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    findings = run_audit()
    out_path = config.experiment_dir(_EXPERIMENT_ID) / "static_audit_report.json"
    out_path.write_text(json.dumps([asdict(f) for f in findings], indent=2, ensure_ascii=False), encoding="utf-8")
    n_slots = sum(1 for f in findings if f.has_slot)
    print(f"\n[static-audit] {len(findings)} costanti controllate, {n_slots} con uno slot identificato.")
    print(f"[static-audit] report scritto in {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
