"""Human-readable recap for one library_benchmark.py run -- reads only
logs/{experiment_id}/verification_benchmark.json (the structured per-pattern
outcomes) and, if present, that experiment's events.jsonl for extra ablation
detail. Nothing here is a new measurement, it's aggregation of real data
already produced by library_benchmark.py, in the same spirit as
experiment/recap.py.

Sections:
  1. Summary counts by status.
  2. The 2 patterns with real, measured retrieval benefit today
     (floating_point_equality, wrong_string_case_comparison) -- called out
     first regardless of status, since they're what actually matters for
     today's real routing.
  3. Known-case cross-validation -- did the automated pipeline agree with
     the 4 already hand-verified conclusions it must reproduce before being
     trusted (see validate_slot_identifier_milestone.py)? A disagreement
     here means the WHOLE run's remaining conclusions are suspect, not just
     that one pattern's -- flagged loudly, not buried in the table.
  4. Repaired skills -- which new Book versions were written, where.
  5. Unresolved cases as analysis material, not just a count (explicit user
     direction, 2026-09-17): for each HIGH_RISK_UNRESOLVED pattern, why it
     stayed unresolved (tracking didn't drop enough after rewrite? holdout
     broke? no valid A-probe to use as holdout at all?) -- these are the
     interesting failures, worth understanding, not discarding.
  6. Full per-pattern table.
  7. Real cost, if the experiment's events.jsonl has token counts.
  8. Honest disclosure of what this run does NOT cover: patterns with a
     slot found but no B/C probe generated (GENERATION_FAILED), the 8
     LOW_VALUE_RETRIEVAL_PATTERNS being tested despite never being reached
     by real retrieval today, and the fact that a single run per pattern
     (no repeats) can show a real ratio moving with sampling noise, same
     methodology caveat every recap in this project repeats on purpose.

Run: python -m cognitive_rpg.verification.recap <experiment_id>
Writes logs/{experiment_id}/verification_recap.md"""

import json
import sys
from pathlib import Path

from .. import config
from .library_benchmark import KNOWN_CASES, REAL_IMPACT_PATTERNS
from ..experiment.events import read_events

STATUS_LABELS = {
    "NO_SLOT": "nessuno slot identificato (nessun letterale da sostituire meccanicamente)",
    "LOW_RISK": "slot trovato, tracking basso (rischio non materializzato)",
    "HIGH_RISK_REPAIRED": "slot trovato, tracking alto, riparato e riverificato con successo",
    "HIGH_RISK_UNRESOLVED": "slot trovato, tracking alto, NESSUNA riparazione sicura trovata",
    "GENERATION_FAILED": "slot trovato ma nessun probe generato -- non misurabile",
}


def _load_outcomes(experiment_id: str) -> list[dict]:
    path = config.experiment_dir(experiment_id) / "verification_benchmark.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} non esiste -- eseguire prima library_benchmark.py per {experiment_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def _section_summary(outcomes: list[dict]) -> str:
    lines = ["## 1. Riepilogo\n"]
    by_status: dict[str, int] = {}
    for o in outcomes:
        by_status[o["status"]] = by_status.get(o["status"], 0) + 1
    lines.append(f"{len(outcomes)} pattern testati.\n")
    for status, label in STATUS_LABELS.items():
        count = by_status.get(status, 0)
        if count:
            lines.append(f"- **{status}** ({count}): {label}")
    return "\n".join(lines)


def _section_real_impact(outcomes: list[dict]) -> str:
    lines = ["\n## 2. I 2 pattern con beneficio reale misurato oggi\n"]
    lines.append(
        "Su 13 pattern nella libreria, solo questi 2 sono mai stati recuperati in una quest reale con un "
        "beneficio comportamentale dimostrato (librarian.py, retrieval_waste_analysis su 75 quest reali). "
        "Gli altri 8 sono in LOW_VALUE_RETRIEVAL_PATTERNS e route() li salta sempre -- il loro risultato qui "
        "sotto e' comunque reale, ma riguarda una skill che oggi non viene mai iniettata in pratica.\n"
    )
    for o in outcomes:
        if o["pattern_id"] in REAL_IMPACT_PATTERNS:
            ratio = f"{o['tracking_ratio']:.0%}" if o.get("tracking_ratio") is not None else "n/d"
            lines.append(f"- **{o['pattern_id']}**: {o['status']} (tracking {ratio}) -- {o['detail']}")
    return "\n".join(lines)


def _section_known_cases(outcomes: list[dict]) -> str:
    lines = ["\n## 3. Validazione incrociata sui 4 casi noti\n"]
    by_pattern = {o["pattern_id"]: o for o in outcomes}
    all_ok = True
    for pattern_id, expected in KNOWN_CASES.items():
        o = by_pattern.get(pattern_id)
        if o is None:
            lines.append(f"- **{pattern_id}**: NON TESTATO in questo run -- impossibile validare")
            all_ok = False
            continue
        # Tutti e 4 i casi noti hanno uno slot candidato nell'audit manuale
        # 2026-08-18 (anche i 3 "LOW" -- il rischio non si e' materializzato,
        # ma uno slot fu trovato). NO_SLOT e' quindi SEMPRE un disaccordo
        # qui, non solo un HIGH/LOW invertito -- distinto esplicitamente,
        # altrimenti si maschera il tipo di disaccordo trovato dal vivo
        # 2026-09-17 su wrong_accumulator_init (nessuno slot trovato sul
        # testo ATTUALE, compresso 3 volte dal 2026-08-18 -- l'esempio
        # concreto originale e' diventato un accenno vago "0 vs empty",
        # plausibile deriva del testo, non provato come bug del motore).
        if o["status"] == "NO_SLOT":
            all_ok = False
            lines.append(f"- **{pattern_id}** [DISACCORDO -- nessuno slot trovato]: atteso -- {expected}; "
                         f"il testo attuale potrebbe essere cambiato dall'audit del 2026-08-18 (vedi generation_method/version del Book)")
            continue
        observed_high = o["status"] in ("HIGH_RISK_REPAIRED", "HIGH_RISK_UNRESOLVED")
        expected_high = "HIGH" in expected
        agree = observed_high == expected_high
        all_ok = all_ok and agree
        mark = "OK" if agree else "DISACCORDO"
        lines.append(f"- **{pattern_id}** [{mark}]: atteso -- {expected}; osservato -- {o['status']} ({o['detail']})")
    if not all_ok:
        lines.append(
            "\n**ATTENZIONE**: almeno un caso noto non e' stato riprodotto. Le conclusioni sui pattern MAI "
            "controllati a mano in questo stesso run vanno trattate con sospetto finche' il disaccordo non e' "
            "capito -- vedi validate_slot_identifier_milestone.py."
        )
    return "\n".join(lines)


def _section_repaired(outcomes: list[dict]) -> str:
    repaired = [o for o in outcomes if o["status"] == "HIGH_RISK_REPAIRED"]
    lines = ["\n## 4. Skill riparate\n"]
    if not repaired:
        lines.append("Nessuna riparazione accettata in questo run.")
        return "\n".join(lines)
    for o in repaired:
        # tracking_after_repair puo' essere None per design (skill_repair.py):
        # quando il letterale manipolabile e' del tutto assente dal testo
        # riscritto, l'assenza stessa e' l'evidenza accettata, nessuna
        # ri-ablazione viene eseguita per non misurare rumore su uno swap
        # che non si applica piu'.
        after = f"{o['tracking_after_repair']:.0%}" if o.get("tracking_after_repair") is not None else "letterale rimosso, nessuna ri-ablazione applicabile"
        before = f"{o['tracking_ratio']:.0%}" if o.get("tracking_ratio") is not None else "n/d"
        lines.append(
            f"- **{o['pattern_id']}** ({o['book_id']} -> {o['repaired_book_path']}): tracking "
            f"{before} -> {after}. {o['detail']}"
        )
    return "\n".join(lines)


def _section_unresolved(outcomes: list[dict]) -> str:
    unresolved = [o for o in outcomes if o["status"] == "HIGH_RISK_UNRESOLVED"]
    lines = ["\n## 5. Casi non risolti -- materiale di analisi, non solo un numero\n"]
    if not unresolved:
        lines.append("Nessun caso ad alto rischio e' rimasto senza una riparazione sicura in questo run.")
        return "\n".join(lines)
    lines.append(
        "Ogni riga qui e' un fallimento reale della riparazione automatica, non solo un conteggio -- capire "
        "PERCHE' non ha funzionato e' esplicitamente parte dello scopo di questo benchmark (2026-09-17).\n"
    )
    for o in unresolved:
        lines.append(f"### {o['pattern_id']} ({o['book_id']})")
        lines.append(f"- Slot identificato: `{o['slot_name']}` = `{o['original_value']}`")
        lines.append(f"- Tracking originale: {o['tracking_ratio']:.0%}" if o.get("tracking_ratio") is not None else "- Tracking originale: n/d")
        if o.get("tracking_after_repair") is not None:
            lines.append(f"- Tracking dopo il tentativo di riscrittura: {o['tracking_after_repair']:.0%}")
            drop = o["tracking_ratio"] - o["tracking_after_repair"]
            lines.append(f"- Calo ottenuto: {drop:.0%} (soglia richiesta per l'accettazione: 25%)")
        lines.append(f"- Motivo: {o['detail']}")
        lines.append("")
    return "\n".join(lines)


def _section_table(outcomes: list[dict]) -> str:
    lines = ["\n## 6. Tabella completa\n"]
    lines.append("| Pattern | Book | Status | Slot | Tracking | Dopo riparazione |")
    lines.append("|---|---|---|---|---|---|")
    for o in sorted(outcomes, key=lambda x: x["pattern_id"]):
        tracking = f"{o['tracking_ratio']:.0%}" if o.get("tracking_ratio") is not None else "--"
        after = f"{o['tracking_after_repair']:.0%}" if o.get("tracking_after_repair") is not None else "--"
        slot = o.get("slot_name") or "--"
        low_value = " (low-value)" if o.get("low_value_retrieval") else ""
        lines.append(f"| {o['pattern_id']}{low_value} | {o['book_id']} v{o['book_version']} | {o['status']} | {slot} | {tracking} | {after} |")
    return "\n".join(lines)


def _section_cost(experiment_id: str) -> str:
    lines = ["\n## 7. Costo reale (solo chiamate al modello sotto test, vedi limite sotto)\n"]
    events = [e for e in read_events(experiment_id) if e["event_type"] in ("ABLATION_BASELINE_CALL", "ABLATION_VARIANT_CALL")]
    priced = [e for e in events if "cost_usd" in e.get("data", {})]
    if not priced:
        lines.append(
            "Nessun dato di costo per-chiamata in questo run (eventi scritti prima che substitution_ablation.py "
            "registrasse provider/token/cost_usd, 2026-09-17) -- non disponibile, non zero."
        )
        return "\n".join(lines)
    total_cost = sum(e["data"]["cost_usd"] for e in priced)
    total_in = sum(e["data"].get("input_tokens", 0) for e in priced)
    total_out = sum(e["data"].get("output_tokens", 0) for e in priced)
    lines.append(f"{len(priced)} chiamate al modello sotto test: ${total_cost:.4f}, {total_in} token input, {total_out} token output.")
    lines.append(
        "\n**Limite noto, non nascosto**: questo copre solo le chiamate al modello sotto test dentro "
        "substitution_ablation.py. Il costo delle chiamate Expert (identify_slot, generazione probe, giudice "
        "di estrazione dentro make_extractor, riscrittura in skill_repair.py) non e' ancora loggato per-chiamata "
        "-- e' un costo reale, non contabilizzato qui, non un costo assente."
    )
    return "\n".join(lines)


def _section_caveats() -> str:
    return (
        "\n## 8. Cosa questo run NON copre\n\n"
        "- Un run per pattern, nessuna ripetizione: un singolo tracking ratio puo' muoversi per rumore di "
        "campionamento, non e' un effetto sistematico dimostrato con n=1.\n"
        "- I pattern in LOW_VALUE_RETRIEVAL_PATTERNS sono testati per esercitare la pipeline, ma non sono mai "
        "raggiunti dal Librarian reale oggi -- un loro esito HIGH_RISK non e' un problema in produzione finche' "
        "quella politica resta com'e'.\n"
        "- GENERATION_FAILED significa che il generatore di probe non ha prodotto nulla di usabile per quel "
        "pattern in questo run -- non e' evidenza che il pattern sia sicuro, solo che non e' stato misurato.\n"
        "- L'audit delle direttive statiche nei prompt dell'app (fuori dalla libreria Book) e' una modalita' "
        "separata (static_audit.py), non incluso qui.\n"
    )


def main() -> int:
    experiment_id = sys.argv[1] if len(sys.argv) > 1 else "verification_benchmark"
    outcomes = _load_outcomes(experiment_id)
    sections = [
        _section_summary(outcomes),
        _section_real_impact(outcomes),
        _section_known_cases(outcomes),
        _section_repaired(outcomes),
        _section_unresolved(outcomes),
        _section_table(outcomes),
        _section_cost(experiment_id),
        _section_caveats(),
    ]
    report = f"# Recap verifica sostituzione meccanica -- {experiment_id}\n\n" + "\n".join(sections) + "\n"
    out_path = config.experiment_dir(experiment_id) / "verification_recap.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"[recap] scritto {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
