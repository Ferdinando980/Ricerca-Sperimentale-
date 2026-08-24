"""Human-readable recap for one experiment. Reads only what's already on disk
-- log.jsonl (one row per finished quest), events.jsonl (one row per pipeline
step, including the Librarian's optimizer runs) -- and the fixed task list
from task_generator.py. Nothing here is a new measurement, it's aggregation
of real data already produced by experiment_0.py / quest_runner.py / the
optimizer, in the same spirit as observer_table.py and city/report.py. Safe
to regenerate at any point, including mid-run.

Sections, in order:
  1. Progress: how many of the (task x A/B/F/C) quests are done, which are not.
  2. The A/B/F/C comparison itself: accuracy/cost/latency per split and overall.
  3. Retrieval vs Architecture (added 2026-08-18): F/C accuracy split by
     coverage (NONE/PARTIAL/FULL) -- isolates whether retrieval itself moves
     accuracy (FULL vs NONE within the same config) from whether the
     retrieval-augmented architecture beats the plain Small baseline
     (FULL vs B).
  4. Token accounting: real input/output/reasoning tokens per config, the
     tokens/successful-task metric (not just tokens/task -- a config with a
     lower raw average can still be less efficient once its failures are
     accounted for), Librarian retrieval overhead, and Optimizer spend.
  5. Skill amortization: per bug-pattern, the one-time cost of building/
     compressing that skill (Optimizer) against the recurring per-use saving
     of F over A on tasks that pattern covers -- i.e. how many uses before the
     Librarian's upfront cost pays for itself against always calling Expert.
  6. Failures, with a specific flag for the case that matters most for judging
     whether the Librarian's skills generalize: two configs failing on
     DIFFERENT tasks of the SAME bug pattern (see the floating_point_equality
     case worked out in conversation on 2026-08-18) vs the same task (which
     just means that task is hard for everyone, no generalization question).
  7. Librarian skill usage: which skills were retrieved, how often, and the
     pass rate of the quests that used them.
  8. Optimizer runs: which skills got compressed, accepted or rejected.
  9. Knowledge Map (Phase 1 of the library evolution plan, 2026-08-18):
     section-level coverage/usage/build-cost, condensed -- full detail in
     knowledge_map.md. Read-only, changes no retrieval/generation behavior.
  A methodology note repeated every time on purpose: with one run per
     (task, config) a single failure is not enough to call something a
     systematic effect -- distinguishing that from model stochasticity needs
     repeated runs of the same task.

Run: python -m cognitive_rpg.experiment.recap <experiment_id>
Writes logs/{experiment_id}/recap.md
"""

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..domain.task_generator import generate_tasks
from . import metrics
from .events import read_events, read_events_all_experiments
from .experiment_log import read_all
from .knowledge_map import section_rows

CONFIGS = ["A", "B", "F", "C"]
CONFIG_LABELS = {
    "A": "A -- Expert da solo",
    "B": "B -- Small da solo",
    "F": "F -- Small + Librarian",
    "C": "C -- Small + Cheater (soluzione pregressa)",
}


def _progress(tasks, records):
    done = {(r["task_id"], r["config_name"]) for r in records}
    total = len(tasks) * len(CONFIGS)
    missing = [
        (t.task_id, cfg, t.split)
        for t in tasks
        for cfg in CONFIGS
        if (t.task_id, cfg) not in done
    ]
    return len(done), total, missing


def _optimizer_cost(events):
    input_tot = output_tot = 0
    n_compress = n_reverify = 0
    for e in events:
        if e["event_type"] == "SKILL_COMPRESSION_FINISHED":
            input_tot += e["data"].get("input_tokens", 0)
            output_tot += e["data"].get("output_tokens", 0)
            n_compress += 1
        elif e["event_type"] == "SKILL_REVERIFICATION":
            input_tot += e["data"].get("input_tokens", 0)
            output_tot += e["data"].get("output_tokens", 0)
            n_reverify += 1
    return {"input": input_tot, "output": output_tot, "n_compress": n_compress, "n_reverify": n_reverify}


def _cross_config_pattern_notes(records, tasks_by_id):
    by_pattern = defaultdict(lambda: defaultdict(list))
    for r in records:
        by_pattern[metrics.pattern_of(r["task_id"], tasks_by_id)][r["config_name"]].append(r)

    notes = []
    for pattern, by_cfg in sorted(by_pattern.items()):
        failing = {cfg: sorted({r["task_id"] for r in rs if not r["passed"]}) for cfg, rs in by_cfg.items()}
        failing = {cfg: tids for cfg, tids in failing.items() if tids}
        if len(failing) < 2:
            continue
        task_sets = list(failing.values())
        same_task = all(set(task_sets[0]) == set(ts) for ts in task_sets)
        notes.append((pattern, failing, same_task))
    return notes


def _optimizer_runs(events):
    runs = []
    for e in events:
        if e["event_type"] in ("SKILL_ACCEPTED", "SKILL_REJECTED"):
            runs.append({
                "skill_id": e["data"]["skill_id"],
                "accepted": e["event_type"] == "SKILL_ACCEPTED",
                "original_passed": e["data"].get("original_passed"),
                "compressed_passed": e["data"].get("compressed_passed"),
            })
    return runs


def build_recap(experiment_id: str) -> str:
    records = read_all(experiment_id)
    events = read_events(experiment_id)
    tasks = generate_tasks(seed=42)
    tasks_by_id = {t.task_id: t for t in tasks}

    L = []
    L.append(f"# Recap -- {experiment_id}")
    L.append(f"_Generato: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    L.append("")

    if not records:
        L.append("Nessuna quest ancora completata per questo experiment_id.")
        return "\n".join(L) + "\n"

    defect_warnings = metrics.benchmark_defect_warnings(records)
    if defect_warnings:
        L.append(
            "> ⚠️ **Difetto noto nel benchmark stesso (non nello skill/config in "
            "esame)** -- i risultati su questi task non significano quello che "
            "sembrano:"
        )
        for tid, note in defect_warnings:
            L.append(f"> - `{tid}`: {note}")
        L.append("")

    finding_warnings = metrics.skill_finding_warnings(records, tasks_by_id)
    if finding_warnings:
        L.append(
            "> 🔬 **Meccanismo dello skill dimostrato causalmente (non solo "
            "osservato per correlazione)** -- da tenere presente leggendo i "
            "numeri di F su questo pattern:"
        )
        for pattern, note in finding_warnings:
            L.append(f"> - `{pattern}`: {note}")
        L.append("")

    mixed_provider = metrics.mixed_provider_warnings(records)
    if mixed_provider:
        L.append(
            "> ⚠️ **Provider/modello misto dentro questo run** -- questi config hanno "
            "usato piu' di una combinazione provider/modello (probabile switch a meta' "
            "run, es. AI Studio -> Vertex AI): confronti tra config diversi restano "
            "validi, ma se citi questi numeri in modo formale tienilo presente."
        )
        L.extend(mixed_provider)
        L.append("")

    waste = metrics.retrieval_waste_analysis(records)
    if waste["n_injected"] > 0:
        waste_pct = waste["n_waste"] / waste["n_injected"]
        L.append(
            "> 💸 **Analisi controfattuale costo di retrieval** (F vs B stesso task, "
            "stesso experiment_id -- zero chiamate nuove): su "
            f"{waste['n_injected']} quest con skill iniettata, **{waste['n_waste']} "
            f"({waste_pct:.1%})** hanno visto B passare comunque senza alcun aiuto -- "
            "overhead di token pagato senza beneficio misurato su quella quest "
            f"specifica ({waste['wasted_tokens']} token totali). "
            f"{waste['n_helped']} quest mostrano un beneficio reale (B falliva, F ha "
            f"passato), {waste['n_hurt']} mostrano lo skill peggiorare l'esito "
            "(spesso il sintomo di un difetto nel benchmark, non dello skill -- "
            "controlla sopra). Pattern con almeno un beneficio misurato in questo "
            f"run: {', '.join(sorted(waste['helped_patterns'])) or '(nessuno)'}."
        )
        L.append("")

    # 1. progress -----------------------------------------------------
    done_n, total_n, missing = _progress(tasks, records)
    L.append("## 1. Stato di avanzamento")
    L.append(f"- {done_n}/{total_n} quest completate ({len(tasks)} task x {len(CONFIGS)} config: A/B/F)")
    if missing:
        by_cfg_missing = defaultdict(list)
        for tid, cfg, split in missing:
            by_cfg_missing[cfg].append(f"{tid} [{split}]")
        L.append(f"- **{len(missing)} quest ancora da fare:**")
        for cfg in CONFIGS:
            if by_cfg_missing[cfg]:
                L.append(f"  - **{cfg}** ({CONFIG_LABELS[cfg]}): {len(by_cfg_missing[cfg])} mancanti")
                for item in by_cfg_missing[cfg]:
                    L.append(f"    - {item}")
        L.append("  (rilancia `tools\\start.bat` per far avanzare -- riprende da solo dal checkpoint)")
    else:
        L.append("- Run completo per questo seed, nessuna quest mancante.")
    L.append("")

    # 2. A/B/F comparison ----------------------------------------------
    L.append("## 2. Confronto A / B / F")
    L.append("A = Expert da solo, B = Small da solo, F = Small + skill dalla Libreria.")
    L.append("")
    by_cs = metrics.by_config_split(records)
    L.append("| config | split | n | accuracy | costo tot | latenza media (ms) |")
    L.append("|---|---|---|---|---|---|")
    for (cfg, split), b in sorted(by_cs.items()):
        acc = b["passed"] / b["n"] if b["n"] else 0.0
        lat = b["latency"] / b["n"] if b["n"] else 0.0
        L.append(f"| {cfg} | {split} | {b['n']} | {acc:.1%} | ${b['cost']:.4f} | {lat:.0f} |")
    L.append("")

    overall = metrics.overall(records)
    L.append("**Totali per config:**")
    for cfg in CONFIGS:
        b = overall.get(cfg)
        if not b:
            continue
        acc = b["passed"] / b["n"] if b["n"] else 0.0
        lat = b["latency"] / b["n"] if b["n"] else 0.0
        L.append(f"- {CONFIG_LABELS[cfg]}: accuracy {acc:.1%}, costo totale ${b['cost']:.4f}, "
                  f"latenza media {lat:.0f}ms, n={b['n']}")
    if overall.get("A") and overall.get("B"):
        delta_ab = overall["B"]["passed"] / overall["B"]["n"] - overall["A"]["passed"] / overall["A"]["n"]
        L.append(f"- B vs A (Small senza aiuto vs Expert): {delta_ab:+.1%} accuracy")
    if overall.get("B") and overall.get("F"):
        delta_bf = overall["F"]["passed"] / overall["F"]["n"] - overall["B"]["passed"] / overall["B"]["n"]
        L.append(f"- F vs B (effetto della Libreria sul modello Small): {delta_bf:+.1%} accuracy")
    if overall.get("A") and overall.get("F"):
        delta_af = overall["F"]["passed"] / overall["F"]["n"] - overall["A"]["passed"] / overall["A"]["n"]
        L.append(f"- F vs A (quanto F si avvicina all'Expert): {delta_af:+.1%} accuracy")
    if overall.get("B") and overall.get("C"):
        delta_cb = overall["C"]["passed"] / overall["C"]["n"] - overall["B"]["passed"] / overall["B"]["n"]
        L.append(f"- C vs B (l'accesso a una soluzione pregressa aiuta rispetto a niente?): {delta_cb:+.1%} accuracy")
    if overall.get("F") and overall.get("C"):
        delta_cf = overall["C"]["passed"] / overall["C"]["n"] - overall["F"]["passed"] / overall["F"]["n"]
        L.append(f"- C vs F (soluzione specifica vs skill generalizzata -- la domanda centrale del Cheater Agent): {delta_cf:+.1%} accuracy")
    L.append("")

    # 3. retrieval vs architecture -----------------------------------------
    L.append("## 3. Retrieval vs Architecture (coverage NONE/PARTIAL/FULL)")
    L.append(
        "Separa \"il meccanismo di retrieval esiste\" da \"il retrieval ha "
        "trovato qualcosa di pertinente\" -- per F (Skill Library) e C "
        "(Solution Bank), ogni quest ha gia' un `coverage` salvato "
        "(NONE=niente trovato, PARTIAL=match parziale/imperfetto, "
        "FULL=match esatto/completo). Se **F-NONE ~= B** e **F-FULL > B**, "
        "e' il retrieval a spostare l'accuracy, non la sola presenza del "
        "meccanismo."
    )
    L.append("")
    cov = metrics.by_config_coverage(records)
    b_acc = overall["B"]["passed"] / overall["B"]["n"] if overall.get("B") and overall["B"]["n"] else None
    delta_retrieval_by_cfg = {}
    for retrieval_cfg in ("F", "C"):
        rows = {c: b for (cfg, c), b in cov.items() if cfg == retrieval_cfg}
        if not rows:
            continue
        L.append(f"**{CONFIG_LABELS.get(retrieval_cfg, retrieval_cfg)}:**")
        L.append("| coverage | n | accuracy |")
        L.append("|---|---|---|")
        for coverage_val in ("NONE", "PARTIAL", "FULL"):
            b = rows.get(coverage_val)
            if not b:
                continue
            acc = b["passed"] / b["n"] if b["n"] else 0.0
            L.append(f"| {coverage_val} | {b['n']} | {acc:.1%} |")
        none_b, full_b = rows.get("NONE"), rows.get("FULL")
        if none_b and full_b and none_b["n"] and full_b["n"]:
            delta_retrieval = full_b["passed"] / full_b["n"] - none_b["passed"] / none_b["n"]
            delta_retrieval_by_cfg[retrieval_cfg] = (delta_retrieval, none_b["n"], full_b["n"])
            L.append(f"- Δ Retrieval (FULL − NONE, dentro {retrieval_cfg} stesso): {delta_retrieval:+.1%}")
        if full_b and full_b["n"] and b_acc is not None:
            delta_architecture = full_b["passed"] / full_b["n"] - b_acc
            L.append(f"- Δ Architecture ({retrieval_cfg}-FULL − B): {delta_architecture:+.1%}")
        L.append("")
    L.append(
        "Il dettaglio per split (KNOWN/VARIANT/NOVEL) di ogni config e' gia' "
        "nella tabella della sezione 2 sopra -- known_example ~ FULL/EXACT, "
        "variant ~ PARTIAL/SEEN per definizione di come route()/lookup() "
        "funzionano, quindi le due viste si leggono insieme."
    )
    if "F" in delta_retrieval_by_cfg and "C" in delta_retrieval_by_cfg:
        f_delta, f_none_n, f_full_n = delta_retrieval_by_cfg["F"]
        c_delta, c_none_n, c_full_n = delta_retrieval_by_cfg["C"]
        if (f_delta > 0) != (c_delta > 0) and f_delta != 0 and c_delta != 0:
            L.append("")
            L.append(
                f"- ⚠️ **Δ Retrieval di segno opposto tra F ({f_delta:+.1%}, n={f_none_n}+{f_full_n}) "
                f"e C ({c_delta:+.1%}, n={c_none_n}+{c_full_n})** -- con questi n puo' essere rumore, "
                "ma se si ripete su run future vale la pena chiedersi se il Librarian sta recuperando "
                "skill anche quando non aiutano (over-triggering) piu' spesso del Cheater."
            )
    L.append("")

    # 4. token accounting ------------------------------------------------
    L.append("## 4. Token accounting")
    L.append(
        "Token reali per config -- separato da costo_usd perche' quello e' $0 finche' "
        "GEMINI_INPUT_PER_MTOK/OUTPUT_PER_MTOK non sono impostati in .env. \"reasoning\" "
        "sono i token di pensiero di Gemini (fatturati, ma mai inclusi in \"output\")."
    )
    L.append("")
    tok = metrics.token_accounting(records)
    L.append("| config | n | input | output | reasoning | totale | tok/task | tok/successo | accuracy |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for cfg in CONFIGS:
        b = tok.get(cfg)
        if not b or not b["n"]:
            continue
        total = b["input"] + b["output"] + b["reasoning"]
        cfg_records = [r for r in records if r["config_name"] == cfg]
        n_passed = sum(1 for r in cfg_records if r["passed"])
        acc = n_passed / len(cfg_records)
        tok_success = total / n_passed if n_passed else float("inf")
        L.append(
            f"| {cfg} | {b['n']} | {b['input']} | {b['output']} | {b['reasoning']} | "
            f"{total} | {total/b['n']:.0f} | {tok_success:.0f} | {acc:.1%} |"
        )
    L.append(
        "- \"tok/successo\" = token totali / task risolti (non /n) -- un config con qualche "
        "fallimento sta comunque spendendo quei token senza ottenere un risultato utile, "
        "quindi e' un confronto piu' onesto di tok/task quando le accuracy non sono identiche."
    )
    L.append("")
    overhead = metrics.librarian_overhead(records)
    if overhead:
        L.append(
            f"- Overhead della Libreria (F vs B, stesso task): +{sum(overhead)/len(overhead):.0f} "
            f"token di input in media (min {min(overhead)}, max {max(overhead)}) -- il costo di "
            f"*usare* uno skill gia' pronto."
        )
    opt_cost = _optimizer_cost(events)
    if opt_cost["n_compress"]:
        opt_total = opt_cost["input"] + opt_cost["output"]
        L.append(
            f"- Costo dell'Optimizer in questa run (costo di *costruire* la conoscenza, non di "
            f"usarla): {opt_cost['n_compress']} compressioni + {opt_cost['n_reverify']} riverifiche = "
            f"{opt_total} token totali ({opt_total/opt_cost['n_compress']:.0f}/skill in media). "
            f"E' un costo una tantum per skill, non per uso -- si ammortizza sulle usi future, "
            f"a differenza dell'overhead della Libreria sopra che si paga ad ogni retrieval."
        )
    L.append("")

    # 4. skill amortization -----------------------------------------------
    L.append("## 5. Ammortamento delle skill (costruzione vs uso)")
    L.append(
        "Per pattern di bug: costo una tantum per costruire/comprimere quella skill "
        "(Optimizer, qualunque tentativo, accettato o no) contro il risparmio medio per "
        "uso di F rispetto ad A sui task che quella skill copre. \"breakeven\" = dopo "
        "quanti usi il costo di costruzione si ripaga rispetto a chiamare sempre Expert. "
        "**Attenzione**: 2 task per pattern in questa run -- direzione indicativa, non "
        "un numero da citare come definitivo."
    )
    L.append("")
    amort = metrics.skill_amortization(events, records, build_cost_events=read_events_all_experiments())
    if not amort:
        L.append("- Nessun dato (serve almeno un retrieval F + una compressione per lo stesso pattern).")
    else:
        L.append("| pattern | costo costruzione | n task | A tok/task | F tok/task | risparmio/uso | breakeven |")
        L.append("|---|---|---|---|---|---|---|")
        for row in amort:
            be = f"{row['breakeven']:.1f} usi" if row["breakeven"] is not None else "mai (F costa piu' di A qui)"
            L.append(
                f"| `{row['pattern']}` | {row['build_cost']} | {row['n_tasks']} | {row['a_avg']:.0f} | "
                f"{row['f_avg']:.0f} | {row['saving']:+.0f} | {be} |"
            )
    L.append("")

    # 5. failures --------------------------------------------------------
    L.append("## 6. Quest fallite")
    failures = [r for r in records if not r["passed"]]
    if not failures:
        L.append("- Nessun fallimento finora.")
    else:
        for r in sorted(failures, key=lambda r: (r["config_name"], r["task_id"])):
            L.append(f"- **{r['config_name']}** [{r['split']}] `{r['task_id']}`")

        notes = _cross_config_pattern_notes(records, tasks_by_id)
        if notes:
            L.append("")
            L.append("**Pattern di bug con fallimenti in piu' di un config:**")
            for pattern, failing, same_task in notes:
                cfg_desc = ", ".join(f"{cfg} su {', '.join(tids)}" for cfg, tids in failing.items())
                if same_task:
                    L.append(f"- `{pattern}`: {cfg_desc} -- stesso task, probabilmente e' il task "
                              f"in se' ad essere difficile per tutti (non e' una domanda sulla Libreria).")
                else:
                    L.append(f"- `{pattern}`: {cfg_desc} -- **task diversi della stessa famiglia di bug** "
                              f"falliscono su config diversi. Da controllare quest per quest in "
                              f"`observer_table.csv` (colonna `retrieved_tokens`) se lo skill recuperato "
                              f"e' lo stesso e se l'ha aiutato o confuso.")
    L.append("")

    # 4. skill usage -------------------------------------------------
    L.append("## 7. Uso degli skill (Librarian)")
    usage = metrics.skill_usage(events, records)
    if not usage:
        L.append("- Nessun retrieval registrato (nessuna quest F ha ancora recuperato uno skill).")
    else:
        L.append("| skill | usi | token medi | quest passate su quest usate |")
        L.append("|---|---|---|---|")
        for skill_id, u in sorted(usage.items()):
            L.append(f"| `{skill_id}` | {u['n']} | {u['avg_tokens']:.0f} | {u['passed']}/{u['n']} |")
    L.append("")

    # 5. optimizer ----------------------------------------------------
    L.append("## 8. Optimizer (compressione skill)")
    opt_runs = _optimizer_runs(events)
    if not opt_runs:
        L.append("- Non ancora lanciato per questo experiment_id (`tools\\optimizer.bat`).")
    else:
        for run in opt_runs:
            status = "ACCETTATA" if run["accepted"] else "RESPINTA"
            L.append(f"- `{run['skill_id']}`: {status} "
                      f"(compresso {run['compressed_passed']} passate vs originale {run['original_passed']} passate, "
                      f"stesso set di task riverificati)")
    L.append("")

    # 8. knowledge map (sections) --------------------------------------
    L.append("## 9. Mappa delle sezioni")
    L.append(
        "Vista condensata -- il dettaglio (crescita della libreria nel tempo, "
        "file su disco vs skill \"attuali\") e' in `knowledge_map.md` "
        "(`tools\\knowledge_map.bat`)."
    )
    L.append("")
    rows = section_rows(experiment_id)
    L.append("| sezione | pattern | coverage | book | usi | costo costruzione |")
    L.append("|---|---|---|---|---|---|")
    for r in rows:
        L.append(
            f"| `{r['section_id']}` | {', '.join(r['patterns'])} | {r['coverage']} | "
            f"{r['n_books']} | {r['n_uses']} | {r['build_cost']} |"
        )
    L.append("")

    # 6. methodology note ---------------------------------------------
    L.append("## Nota metodologica")
    L.append("Ogni cella (task, config) ha una sola run. Un singolo fallimento non basta per dire "
              "se e' un problema sistematico dello skill o una variazione casuale del modello -- "
              "serve ripetere lo stesso task piu' volte per distinguerli.")
    if overall and all(b["cost"] == 0.0 for b in overall.values()):
        L.append("Tutti i costi risultano $0.00: probabile prezzo non configurato per il provider "
                  "in uso (vedi `GEMINI_INPUT_PER_MTOK`/`GEMINI_OUTPUT_PER_MTOK` in `.env`), non un "
                  "run gratuito per davvero -- non affidarti a questo numero per ora.")

    return "\n".join(L) + "\n"


def write_recap(experiment_id: str) -> Path:
    text = build_recap(experiment_id)
    out_path = config.experiment_dir(experiment_id) / "recap.md"
    out_path.write_text(text, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    experiment_id = sys.argv[1] if len(sys.argv) > 1 else config.get_current_experiment_id()
    path = write_recap(experiment_id)
    print(f"[recap] scritto {path}")
