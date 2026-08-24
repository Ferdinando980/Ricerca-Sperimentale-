"""Generates the Cognitive City report: a single self-contained HTML file, written
to logs/{experiment_id}_city.html, that visualizes an Experiment Engine run.

Every number in the report comes from experiment_log.jsonl / {id}_events.jsonl --
nothing is simulated. The "buildings" are a fixed legend mapped onto real pipeline
stages (see EVENT_BUILDING below); the "day timeline" is the real chronological
order quests actually ran in, with real cumulative accuracy/cost per NPC (config).
Concepts with no backing subsystem yet (Books appearing, Master/Apprentice, XP,
Discovery Event) are deliberately NOT represented -- see project memory for why.

Run: python -m cognitive_rpg.city.report <experiment_id>
Also called automatically from experiment_0.main() after each run.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from .. import config
from ..experiment.experiment_log import read_all
from ..experiment.events import read_events

EVENT_BUILDING = {
    "QUEST_CREATED": ("home", "\U0001f3e0", "Casa"),
    "NPC_ASSIGNED": ("home", "\U0001f3e0", "Casa"),
    "RETRIEVAL_STARTED": ("library", "\U0001f4da", "Biblioteca"),
    "RETRIEVAL_RESULT": ("library", "\U0001f4da", "Biblioteca"),
    "PROMPT_BUILT": ("shop", "\U0001f3ea", "Negozio"),
    "MODEL_CALL_STARTED": ("shop", "\U0001f3ea", "Negozio"),
    "MODEL_CALL_FINISHED": ("shop", "\U0001f3ea", "Negozio"),
    "VERIFICATION": ("hospital", "\U0001f3e5", "Ospedale"),
    "QUEST_COMPLETED": ("home", "\U0001f3e0", "Casa"),
}

ROLE_LABELS = {"worker": "Apprentice", "librarian": "Retriever", "checker": "Verifier", "npc": "Quest"}
# Which events carry authoritative (non-duplicated) real token counts per role --
# PROMPT_BUILT/MODEL_CALL_STARTED are informational and would double-count the worker.
TOKEN_SOURCE_EVENTS = {"MODEL_CALL_FINISHED", "RETRIEVAL_RESULT", "VERIFICATION"}


def _quest_order(records: list[dict], events: list[dict]) -> list[str]:
    """Real chronological order tasks were first encountered in this experiment --
    from QUEST_CREATED timestamps when the event log exists, otherwise falls back
    to first-seen order in the plain log (older runs predate events.py)."""
    quest_created = [e for e in events if e["event_type"] == "QUEST_CREATED"]
    if quest_created:
        first_seen: dict[str, str] = {}
        for e in quest_created:
            tid = e["task_id"]
            if tid not in first_seen or e["timestamp"] < first_seen[tid]:
                first_seen[tid] = e["timestamp"]
        return sorted(first_seen, key=lambda tid: first_seen[tid])

    seen: list[str] = []
    for r in records:
        if r["task_id"] not in seen:
            seen.append(r["task_id"])
    return seen


def _latest_record_by(records: list[dict], task_id: str, config_name: str) -> dict | None:
    matches = [r for r in records if r["task_id"] == task_id and r["config_name"] == config_name]
    return matches[-1] if matches else None


def _npc_summary(cfg: str, records: list[dict]) -> dict:
    cfg_records = [r for r in records if r["config_name"] == cfg]
    n = len(cfg_records)
    passed = sum(1 for r in cfg_records if r["passed"])
    models = [r.get("model", "?") for r in cfg_records]
    providers = [r.get("provider", "?") for r in cfg_records]
    return {
        "config": cfg,
        "model": max(set(models), key=models.count) if models else "?",
        "provider": max(set(providers), key=providers.count) if providers else "?",
        "n": n,
        "accuracy": (passed / n) if n else 0.0,
        "total_cost_usd": sum(r.get("cost_usd", 0.0) for r in cfg_records),
        "total_input_tokens": sum(r.get("input_tokens", 0) for r in cfg_records),
        "total_output_tokens": sum(r.get("output_tokens", 0) for r in cfg_records),
        "total_retries": sum(r.get("retries", 0) for r in cfg_records),
        "total_paused_seconds": sum(r.get("paused_seconds", 0.0) for r in cfg_records),
        "uses_librarian": any(r.get("coverage", "N/A") != "N/A" for r in cfg_records),
    }


def _build_timeline(quest_order: list[str], configs: list[str], records: list[dict]) -> dict:
    timeline = {}
    for cfg in configs:
        days = []
        passed_count = 0
        cum_cost = 0.0
        for i, task_id in enumerate(quest_order):
            record = _latest_record_by(records, task_id, cfg)
            if record is None:
                continue
            passed_count += int(record["passed"])
            cum_cost += record.get("cost_usd", 0.0)
            days.append({
                "day": i,
                "task_id": task_id,
                "split": record["split"],
                "is_novel": record["split"] == "NOVEL",
                "passed": record["passed"],
                "coverage": record.get("coverage", "N/A"),
                "cost_usd": record.get("cost_usd", 0.0),
                "cumulative_accuracy": passed_count / (len(days) + 1),
                "cumulative_cost_usd": cum_cost,
            })
        timeline[cfg] = days
    return timeline


def _build_quest_paths(quest_order: list[str], configs: list[str], events: list[dict]) -> dict:
    by_task_cfg: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in events:
        by_task_cfg[(e["task_id"], e["config_name"])].append(e)
    for key in by_task_cfg:
        by_task_cfg[key].sort(key=lambda e: e["timestamp"])

    paths = {}
    for task_id in quest_order:
        paths[task_id] = {}
        for cfg in configs:
            stage_events = by_task_cfg.get((task_id, cfg), [])
            paths[task_id][cfg] = [
                {
                    "event_type": e["event_type"],
                    "building": EVENT_BUILDING.get(e["event_type"], ("?", "❓", e["event_type"]))[0],
                    "icon": EVENT_BUILDING.get(e["event_type"], ("?", "❓", e["event_type"]))[1],
                    "label": EVENT_BUILDING.get(e["event_type"], ("?", "❓", e["event_type"]))[2],
                    "timestamp": e["timestamp"],
                    "data": e["data"],
                }
                for e in stage_events
            ]
    return paths


def _build_quest_costs(quest_order: list[str], configs: list[str], events: list[dict]) -> dict:
    """Reconstructs, per quest and per NPC, the real token cost broken down by
    role (Retriever/Apprentice/Verifier) -- answers "who's using all those
    tokens" directly from the event chain instead of by inference."""
    by_task_cfg: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in events:
        by_task_cfg[(e["task_id"], e["config_name"])].append(e)

    costs = {}
    for task_id in quest_order:
        costs[task_id] = {}
        for cfg in configs:
            role_totals: dict[str, dict] = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0})
            for e in by_task_cfg.get((task_id, cfg), []):
                if e["event_type"] not in TOKEN_SOURCE_EVENTS:
                    continue
                role = e.get("npc_id", "?").split(":")[-1]
                role_totals[role]["input_tokens"] += e["data"].get("input_tokens", 0) or 0
                role_totals[role]["output_tokens"] += e["data"].get("output_tokens", 0) or 0
            rows = [
                {
                    "role": ROLE_LABELS.get(role, role),
                    "input_tokens": tok["input_tokens"],
                    "output_tokens": tok["output_tokens"],
                    "total": tok["input_tokens"] + tok["output_tokens"],
                }
                for role, tok in role_totals.items()
            ]
            costs[task_id][cfg] = {
                "rows": rows,
                "total": sum(r["total"] for r in rows),
            }
    return costs


def _build_summary_table(records: list[dict]) -> list[dict]:
    buckets: dict[tuple[str, str], dict] = defaultdict(lambda: {"n": 0, "passed": 0, "cost": 0.0, "latency": 0.0})
    for r in records:
        key = (r["config_name"], r["split"])
        b = buckets[key]
        b["n"] += 1
        b["passed"] += int(r["passed"])
        b["cost"] += r.get("cost_usd", 0.0)
        b["latency"] += r.get("latency_ms", 0.0)
    rows = []
    for (cfg, split), b in sorted(buckets.items()):
        rows.append({
            "config": cfg,
            "split": split,
            "n": b["n"],
            "accuracy": b["passed"] / b["n"] if b["n"] else 0.0,
            "total_cost_usd": b["cost"],
            "avg_latency_ms": b["latency"] / b["n"] if b["n"] else 0.0,
        })
    return rows


def generate(experiment_id: str) -> Path:
    records = read_all(experiment_id)
    if not records:
        raise ValueError(f"no log records found for experiment_id={experiment_id!r}")
    events = read_events(experiment_id)

    configs = sorted({r["config_name"] for r in records})
    quest_order = _quest_order(records, events)

    data = {
        "experiment_id": experiment_id,
        "generated_from": {
            "log_records": len(records),
            "events": len(events),
            "has_event_detail": len(events) > 0,
            "architecture_version": events[0].get("architecture_version") if events else None,
            "generation": events[0].get("generation") if events else None,
        },
        "configs": configs,
        "npcs": {cfg: _npc_summary(cfg, records) for cfg in configs},
        "summary_table": _build_summary_table(records),
        "timeline": _build_timeline(quest_order, configs, records),
        "quest_order": quest_order,
        "quest_paths": _build_quest_paths(quest_order, configs, events),
        "quest_costs": _build_quest_costs(quest_order, configs, events),
    }

    html = _TEMPLATE.replace("__CITY_DATA__", json.dumps(data).replace("</", "<\\/"))
    out_path = config.experiment_dir(experiment_id) / "city.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


_TEMPLATE = r"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>Cognitive City</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap" rel="stylesheet">
<style>
  :root {
    /* JRPG dialog-box palette: deep navy world, parchment text, gold for what matters */
    --bg: #0c1524; --bg-tile-a: #101d31; --bg-tile-b: #0e1a2c;
    --panel: #16243a; --panel-edge: #4f9fd6; --panel-shadow: #060a12;
    --ink: #f2ead2; --muted: #8fa4bf;
    --line: #2b4160; --accent: #e8c15a; --bad: #ef6f63; --good: #6fd19e; --novel: #e8c15a;
    --a: #6fa8dc; --b: #c893e8; --f: #6fd19e; --c: #ef9f5f;
    --path-color: #7a5a3a;
    --font-pixel: "Press Start 2P", ui-monospace, monospace;
    --font-retro: "VT323", ui-monospace, monospace;
    --font-data: ui-monospace, "SF Mono", Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body { margin:0; background:
      repeating-linear-gradient(45deg, var(--bg-tile-a) 0 16px, var(--bg-tile-b) 16px 32px);
    color:var(--ink); font-family: var(--font-retro); font-size:18px; }
  header { padding:22px 24px 18px; border-bottom:4px solid var(--panel-edge);
    background:linear-gradient(180deg, #142238, #0c1524); }
  h1 { margin:0 0 8px; font-family:var(--font-pixel); font-size:19px; letter-spacing:1px;
    color:var(--accent); text-shadow:2px 2px 0 var(--panel-shadow); text-wrap:balance; }
  .sub { color:var(--muted); font-size:16px; }
  main { padding:22px 24px 40px; display:flex; flex-direction:column; gap:22px; max-width:1200px; margin:0 auto; }
  section { background:var(--panel); padding:16px 18px; position:relative;
    border:2px solid var(--panel-edge);
    box-shadow: inset 0 0 0 2px var(--panel-shadow), 0 4px 0 var(--panel-shadow), 0 4px 14px rgba(0,0,0,.35); }
  h2 { margin:0 0 14px; font-family:var(--font-pixel); font-size:11px; text-transform:uppercase;
    letter-spacing:.06em; color:var(--accent); line-height:1.6; text-wrap:balance; }
  table { border-collapse:collapse; width:100%; font-family:var(--font-data); font-size:13px;
    font-variant-numeric:tabular-nums; }
  th,td { text-align:left; padding:5px 12px 5px 0; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:normal; text-transform:uppercase; font-size:10px; letter-spacing:.04em; }
  .npc-row { display:flex; gap:14px; flex-wrap:wrap; }
  .npc-card { border:2px solid var(--line); padding:10px 14px; min-width:190px;
    background:var(--bg); font-family:var(--font-data); font-size:12.5px; line-height:1.7;
    box-shadow: inset 0 0 0 1px var(--panel-shadow); }
  .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px;
    box-shadow:0 0 0 1px rgba(0,0,0,.4); }
  .legend { display:flex; gap:18px; flex-wrap:wrap; color:var(--muted); margin-bottom:10px; font-size:15px; }
  select, input[type=range] { font-family:var(--font-retro); font-size:16px; color:var(--ink);
    background:var(--bg); border:2px solid var(--line); padding:3px 6px; }
  .path { display:flex; align-items:center; gap:6px; margin:6px 0; flex-wrap:wrap; font-size:15px; }
  .path .badge { font-size:22px; }
  .path .cfg-label { width:70px; font-weight:bold; }
  .arrow { color:var(--muted); }
  .stagebox { border:1px solid var(--line); border-radius:3px; padding:2px 6px; font-size:12px; cursor:default; background:var(--bg); }
  .pass { color:var(--good); } .fail { color:var(--bad); } .novel-tag { color:var(--novel); }

  /* -- world map: tile floor, dirt paths, buildings with signposts and shadows -- */
  .town { position:relative; height:520px; margin-bottom:10px; overflow:hidden;
    background:
      repeating-linear-gradient(90deg, rgba(255,255,255,.02) 0 2px, transparent 2px 32px),
      repeating-linear-gradient(0deg, rgba(255,255,255,.02) 0 2px, transparent 2px 32px),
      repeating-linear-gradient(135deg, #16321f 0 32px, #12291a 32px 64px);
    border:2px solid var(--panel-edge); box-shadow: inset 0 0 0 2px var(--panel-shadow), inset 0 0 24px rgba(0,0,0,.45); }
  .town svg.roads { position:absolute; inset:0; width:100%; height:100%; }
  .town .plot { position:absolute; transform:translate(-50%,-50%); text-align:center; width:90px; pointer-events:none; }
  .town .plot .shadow-oval { width:34px; height:10px; margin:0 auto; border-radius:50%;
    background:rgba(0,0,0,.4); filter:blur(1px); }
  .town .plot span.icon { display:block; font-size:36px; line-height:1; margin-top:-30px;
    filter:drop-shadow(2px 3px 0 rgba(0,0,0,.4)); image-rendering:pixelated; }
  .town .plot .plot-label { display:inline-block; margin-top:2px; font-family:var(--font-pixel); font-size:8px;
    color:var(--ink); background:var(--panel-shadow); border:1px solid var(--panel-edge);
    padding:3px 6px; letter-spacing:.02em; }
  .town .plot { pointer-events:auto; cursor:help; }
  .town .plot .explain { position:absolute; left:50%; bottom:100%; transform:translate(-50%,-8px) scale(.92);
    width:180px; background:var(--ink); color:#1c1b18; border:2px solid var(--panel-shadow);
    padding:8px 10px; font-family:var(--font-data); font-size:11.5px; line-height:1.5; text-align:left;
    box-shadow:0 4px 0 rgba(0,0,0,.3); opacity:0; pointer-events:none; transition:opacity .15s, transform .15s;
    z-index:10; }
  .town .plot .explain:after { content:""; position:absolute; left:50%; top:100%; transform:translateX(-50%);
    border:7px solid transparent; border-top-color:var(--ink); }
  .town .plot:hover .explain { opacity:1; transform:translate(-50%,-8px) scale(1); }

  .walker { position:absolute; width:1px; height:1px;
    transition:left 1.8s steps(12), top 1.8s steps(12); z-index:6; }
  .walker .shadow-oval { position:absolute; left:0; top:-3px; transform:translate(-50%,-50%);
    width:20px; height:7px; border-radius:50%; background:rgba(0,0,0,.45); filter:blur(.5px); }
  .walker .sprite { position:absolute; left:0; top:0; transform:translate(-50%,-100%); font-size:22px;
    display:inline-block; image-rendering:pixelated; }
  .walker.walking .sprite { animation: walk-bob .62s steps(2) infinite; }
  .walker .chip { position:absolute; left:0; top:-19px; transform:translate(-50%,-100%); font-family:var(--font-pixel);
    font-size:7px; padding:3px 5px; color:#0c1524; white-space:nowrap; border:1px solid var(--panel-shadow);
    box-shadow:1px 1px 0 var(--panel-shadow); }
  .walker .balloon { position:absolute; left:0; bottom:26px; transform:translate(-50%,0); min-width:150px; max-width:205px;
    background:var(--ink); color:#1c1b18; border:2px solid var(--panel-shadow); padding:7px 9px;
    font-family:var(--font-data); font-size:11.5px; line-height:1.55; box-shadow:0 4px 0 rgba(0,0,0,.3);
    opacity:0; pointer-events:none; transition:opacity .3s; text-align:left; z-index:9; cursor:pointer; }
  .walker .balloon:after { content:""; position:absolute; left:50%; bottom:-8px; transform:translateX(-50%);
    border:8px solid transparent; border-top-color:var(--ink); }
  .walker.talking .balloon { opacity:1; pointer-events:auto; }
  .walker .balloon-summary b { color:var(--f); }
  .walker .balloon-more { display:block; margin-top:4px; font-size:9.5px; color:#6b675e; text-decoration:underline dotted; }
  .walker .balloon-detail { display:none; margin-top:5px; padding-top:5px; border-top:1px dashed #c9c2ac; font-size:10px; }
  .walker .balloon.expanded .balloon-detail { display:block; }
  .walker .balloon.expanded .balloon-more { display:none; }
  .walker .learning-badge { position:absolute; left:14px; bottom:20px; transform:translate(0,0) scale(.8);
    font-family:var(--font-pixel); font-size:8px; color:#1c1b18; background:var(--accent);
    border:2px solid var(--panel-shadow); padding:5px 8px; white-space:nowrap; opacity:0;
    box-shadow:0 3px 0 rgba(0,0,0,.3); transition:opacity .2s, transform .2s; z-index:11; }
  .walker.learning .learning-badge { opacity:1; transform:translate(0,-6px) scale(1); animation:learn-pulse 1s ease-in-out infinite; }
  @keyframes learn-pulse { 0%,100%{ transform:translate(0,-6px) scale(1);} 50%{ transform:translate(0,-10px) scale(1.06);} }
  @keyframes walk-bob { 0%,100%{ transform:translate(-50%,-100%) translateY(0);} 50%{ transform:translate(-50%,-100%) translateY(-6px);} }

  .town-controls { display:flex; align-items:center; gap:12px; margin-bottom:10px; flex-wrap:wrap; }
  .town-controls button { font-family:var(--font-pixel); font-size:10px; padding:9px 14px; border:2px solid var(--panel-edge);
    background:var(--bg); color:var(--accent); cursor:pointer; box-shadow:0 3px 0 var(--panel-shadow); }
  .town-controls button:hover { background:var(--panel-edge); color:#0c1524; }
  .town-controls button:active { box-shadow:0 1px 0 var(--panel-shadow); transform:translateY(2px); }
  .town-legend { display:flex; gap:16px; flex-wrap:wrap; color:var(--muted); font-size:14px; }
  details.log-detail { margin-top:6px; }
  details.log-detail summary { cursor:pointer; color:var(--muted); font-size:14px; }
  svg.chart { width:100%; height:140px; }
  .day-info { margin-top:8px; color:var(--muted); font-size:15px; }
  .day-info b { color:var(--ink); }
  .missing { color:var(--muted); font-style:italic; }
</style>
</head>
<body>
<header>
  <h1>&#9876;&#65039; Cognitive City</h1>
  <div class="sub" id="hdr-sub"></div>
</header>
<main>
  <section id="sec-npcs">
    <h2>NPC</h2>
    <div class="npc-row" id="npc-row"></div>
  </section>

  <section id="sec-summary">
    <h2>Experiment Mode -- confronto configurazioni</h2>
    <table id="summary-table"></table>
  </section>

  <section id="sec-map">
    <h2>Mappa (ogni edificio = uno stage reale della pipeline)</h2>
    <div class="town-legend">
      <span>&#127968; Casa -- quest creata / risultato salvato</span>
      <span>&#128218; Biblioteca -- Librarian (solo NPC con retrieval)</span>
      <span>&#127754; Negozio -- Worker: genera la soluzione</span>
      <span>&#127973; Ospedale -- Verifier: pytest reale</span>
    </div>
  </section>

  <section id="sec-timeline">
    <h2>Timeline (ogni giorno = una quest reale, in ordine cronologico reale)</h2>
    <div id="timeline-missing" class="missing" style="display:none">
      Nessun timestamp per-quest disponibile per questo run (log precedente all'event tracking) -- ordine mostrato = ordine nel file di log.
    </div>
    <svg class="chart" id="chart-accuracy" viewBox="0 0 1000 140" preserveAspectRatio="none"></svg>
    <div class="legend" id="chart-accuracy-legend"></div>
    <svg class="chart" id="chart-cost" viewBox="0 0 1000 140" preserveAspectRatio="none"></svg>
    <div class="legend" id="chart-cost-legend">saldo Banca cumulativo ($)</div>
    <input type="range" id="day-slider" min="0" max="0" value="0" style="width:100%">
    <div class="day-info" id="day-info"></div>
  </section>

  <section id="sec-walker">
    <h2>Percorso quest (dati reali per-stage)</h2>
    <div class="town-controls">
      <select id="quest-select"></select>
      <button id="replay-btn">&#8635; Rivivi il percorso</button>
    </div>
    <div class="town" id="town"></div>
    <details class="log-detail">
      <summary>Registro testuale dello stesso percorso (per stage, dati grezzi)</summary>
      <div id="quest-paths"></div>
    </details>
    <h2 style="margin-top:18px">Costo per ruolo -- chi sta usando i token</h2>
    <div id="quest-costs"></div>
  </section>
</main>

<script>
const DATA = __CITY_DATA__;
const CFG_COLOR = {A: "var(--a)", B: "var(--b)", F: "var(--f)", C: "var(--c)"};

document.getElementById("hdr-sub").textContent =
  `experiment_id=${DATA.experiment_id} -- ${DATA.generated_from.log_records} quest loggate, ` +
  `${DATA.generated_from.events} eventi per-stage` +
  (DATA.generated_from.has_event_detail ? "" : " (nessun dettaglio per-stage per questo run)") +
  (DATA.generated_from.architecture_version ? ` -- architecture_version=${DATA.generated_from.architecture_version}, generation=${DATA.generated_from.generation}` : "");

const npcRow = document.getElementById("npc-row");
for (const cfg of DATA.configs) {
  const n = DATA.npcs[cfg];
  const div = document.createElement("div");
  div.className = "npc-card";
  div.innerHTML = `<span class="dot" style="background:${CFG_COLOR[cfg]||'#888'}"></span><b>NPC-${cfg}</b><br>
    ${n.provider} / ${n.model}<br>
    accuracy: ${(n.accuracy*100).toFixed(1)}% (n=${n.n})<br>
    costo tot: $${n.total_cost_usd.toFixed(4)}<br>
    token in/out: ${n.total_input_tokens}/${n.total_output_tokens}<br>
    retry: ${n.total_retries} (pausa ${n.total_paused_seconds.toFixed(0)}s)<br>
    librarian: ${n.uses_librarian ? "si" : "no"}`;
  npcRow.appendChild(div);
}

const table = document.getElementById("summary-table");
table.innerHTML = "<tr><th>config</th><th>split</th><th>n</th><th>accuracy</th><th>costo tot</th><th>latenza media</th></tr>" +
  DATA.summary_table.map(r =>
    `<tr><td>${r.config}</td><td>${r.split}</td><td>${r.n}</td>` +
    `<td>${(r.accuracy*100).toFixed(1)}%</td><td>$${r.total_cost_usd.toFixed(4)}</td>` +
    `<td>${r.avg_latency_ms.toFixed(0)}ms</td></tr>`
  ).join("");

document.getElementById("timeline-missing").style.display = DATA.generated_from.has_event_detail ? "none" : "block";

function drawChart(svgId, series, valueKey, legendId, fmt) {
  const svg = document.getElementById(svgId);
  const allVals = DATA.configs.flatMap(cfg => (DATA.timeline[cfg]||[]).map(d => d[valueKey]));
  const maxV = Math.max(0.0001, ...allVals);
  svg.innerHTML = "";
  const legend = document.getElementById(legendId);
  if (legend && legendId === "chart-accuracy-legend") legend.innerHTML = "";
  for (const cfg of DATA.configs) {
    const days = DATA.timeline[cfg] || [];
    if (!days.length) continue;
    const n = days.length;
    const pts = days.map((d,i) => {
      const x = n > 1 ? (i/(n-1))*1000 : 0;
      const y = 140 - (d[valueKey]/maxV)*130 - 5;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const poly = document.createElementNS("http://www.w3.org/2000/svg","polyline");
    poly.setAttribute("points", pts);
    poly.setAttribute("fill", "none");
    poly.setAttribute("stroke", CFG_COLOR[cfg] || "#888");
    poly.setAttribute("stroke-width", "2");
    svg.appendChild(poly);
    // mark NOVEL encounters
    days.forEach((d,i) => {
      if (!d.is_novel) return;
      const x = n > 1 ? (i/(n-1))*1000 : 0;
      const y = 140 - (d[valueKey]/maxV)*130 - 5;
      const c = document.createElementNS("http://www.w3.org/2000/svg","circle");
      c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", 3);
      c.setAttribute("fill", "var(--novel)");
      svg.appendChild(c);
    });
    if (legend && legendId === "chart-accuracy-legend") {
      const span = document.createElement("span");
      span.innerHTML = `<span class="dot" style="background:${CFG_COLOR[cfg]}"></span>NPC-${cfg}`;
      legend.appendChild(span);
    }
  }
  if (legend && legendId === "chart-accuracy-legend") {
    const span = document.createElement("span");
    span.innerHTML = `<span class="dot" style="background:var(--novel)"></span>incontro NOVEL (nessun Book copre il pattern)`;
    legend.appendChild(span);
  }
}
drawChart("chart-accuracy", DATA.timeline, "cumulative_accuracy", "chart-accuracy-legend");
drawChart("chart-cost", DATA.timeline, "cumulative_cost_usd", "chart-cost-legend");

const slider = document.getElementById("day-slider");
const maxDay = Math.max(0, ...DATA.configs.map(cfg => (DATA.timeline[cfg]||[]).length - 1));
slider.max = maxDay;
slider.value = maxDay;
const dayInfo = document.getElementById("day-info");
function renderDay() {
  const i = parseInt(slider.value, 10);
  const lines = DATA.configs.map(cfg => {
    const d = (DATA.timeline[cfg]||[])[i];
    if (!d) return "";
    const mark = d.passed ? '<span class="pass">PASS</span>' : '<span class="fail">FAIL</span>';
    const novel = d.is_novel ? ' <span class="novel-tag">[NOVEL]</span>' : '';
    return `NPC-${cfg}: ${d.task_id} (${d.split})${novel} -- ${mark}, coverage=${d.coverage}, ` +
      `accuracy cum.=${(d.cumulative_accuracy*100).toFixed(1)}%, banca=$${d.cumulative_cost_usd.toFixed(4)}`;
  }).filter(Boolean);
  dayInfo.innerHTML = `<b>Giorno ${i}</b><br>` + lines.join("<br>");
}
slider.addEventListener("input", renderDay);
renderDay();

// -- Town map: buildings at fixed spots, "omini" that really walk the real
// per-stage event sequence from quest_paths (same data as the text log below,
// just rendered spatially). Nothing here is simulated: a walker only moves
// between buildings that a real event chain actually visited, in that order.
const PLOTS = {
  home:     { x: 50, y: 38, icon: "\u{1F3E0}", label: "Casa",
    desc: "Qui nasce ogni richiesta (quest creata) e arriva il risultato finale: passato o fallito, per davvero, non simulato." },
  library:  { x: 17, y: 74, icon: "\u{1F4DA}", label: "Biblioteca",
    desc: "Solo chi ha un Librarian o un Cheater passa di qui: recupera uno skill scritto a mano o una soluzione passata, prima di provare a rispondere." },
  shop:     { x: 50, y: 74, icon: "\u{1F3EA}", label: "Negozio",
    desc: "Il modello genera davvero la correzione al codice, con o senza l'aiuto raccolto in Biblioteca." },
  hospital: { x: 83, y: 74, icon: "\u{1F3E5}", label: "Ospedale",
    desc: "I test automatici (pytest) verificano se la correzione funziona per davvero -- nessun giudizio umano o soggettivo." },
};
const townEl = document.getElementById("town");
function renderTown() {
  townEl.innerHTML = "";
  // Dirt roads home->each building, drawn as an SVG line in a 0-100 x 0-100
  // viewBox with preserveAspectRatio="none" -- coordinates map 1:1 to the
  // PLOTS %s regardless of the container's actual (non-square) pixel aspect
  // ratio. A rotated CSS div computed the angle/length from raw % deltas as
  // if width% and height% were the same unit, which they aren't once the box
  // isn't square -- the line pointed at the wrong spot (found 2026-08-19).
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("class", "roads");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.setAttribute("preserveAspectRatio", "none");
  for (const key of ["library","shop","hospital"]) {
    const a = PLOTS.home, b = PLOTS[key];
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    line.setAttribute("stroke", "var(--path-color)");
    line.setAttribute("stroke-width", "1.1");
    line.setAttribute("stroke-linecap", "round");
    line.setAttribute("stroke-dasharray", "2.2 1.6");
    line.setAttribute("vector-effect", "non-scaling-stroke");
    line.setAttribute("opacity", "0.85");
    svg.appendChild(line);
  }
  townEl.appendChild(svg);
  for (const key in PLOTS) {
    const p = PLOTS[key];
    const div = document.createElement("div");
    div.className = "plot";
    div.style.left = p.x + "%";
    div.style.top = p.y + "%";
    div.innerHTML = `<span class="icon">${p.icon}</span><span class="plot-label">${p.label}</span>` +
      `<span class="explain">${p.desc}</span>`;
    townEl.appendChild(div);
  }
}
renderTown();

const WALKER_SPRITE = "\u{1F6B6}"; // pedestrian; tinted per-config via CSS filter/hue on the chip color
// Small fixed per-config offset (in %) so 2-4 walkers standing at the same
// building form a readable little cluster instead of stacking exactly on
// top of each other. Does not affect which building data says they're at.
// Small tight jitter -- walkers stay visibly AT their real building, just not
// stacked exactly on top of each other. Overlap between simultaneous
// balloons is solved separately below (a fixed vertical lane per config),
// not by scattering the walkers themselves further apart.
const CFG_JITTER = { A: {dx:-7, dy:-4}, B: {dx:7, dy:-4}, C: {dx:-7, dy:5}, F: {dx:7, dy:5} };
const CFG_LANE = { A: 0, B: 1, C: 2, F: 3 };
function jitteredPos(cfg, pos) {
  const j = CFG_JITTER[cfg] || {dx:0, dy:0};
  const x = Math.max(12, Math.min(88, pos.x + j.dx));
  const y = Math.max(10, Math.min(90, pos.y + j.dy));
  return { x, y };
}
// One short, human-readable Italian sentence per stop -- the balloon's
// default view. The full raw per-event data (same as the text log below the
// map) is still there, just tucked behind a click instead of dumped by
// default, since 2-4 balloons open at once with raw key=value pairs was
// unreadable.
function summarizeStop(stop, cfg) {
  const byType = {};
  for (const e of stop.events) byType[e.event_type] = e.data || {};
  if (stop.building === "home") {
    if (byType.QUEST_COMPLETED) {
      return byType.QUEST_COMPLETED.passed ? "Missione riuscita!" : "Missione fallita.";
    }
    return "Riceve l'incarico.";
  }
  if (stop.building === "library") {
    const d = byType.RETRIEVAL_RESULT || {};
    const cov = d.coverage;
    const n = (d.skill_ids || []).length;
    if (cov === "FULL") return `Trova esattamente quello che serve (${n} skill).`;
    if (cov === "PARTIAL") return `Trova qualcosa di simile, non identico (${n}).`;
    if (cov === "NONE") return "Non trova nulla di utile.";
    return "Cerca in biblioteca.";
  }
  if (stop.building === "shop") {
    const d = byType.MODEL_CALL_FINISHED || byType.PROMPT_BUILT || {};
    const tok = (d.input_tokens || 0) + (d.output_tokens || 0);
    return tok ? `Scrive una soluzione (~${tok} token).` : "Scrive una soluzione.";
  }
  if (stop.building === "hospital") {
    const d = byType.VERIFICATION || {};
    if (d.tests_total != null) return `Test: ${d.tests_passed}/${d.tests_total} superati.`;
    return "I test verificano il lavoro.";
  }
  return `${stop.events.length} evento/i.`;
}
function rawDetailHtml(stop) {
  return stop.events.map(e => {
    const d = Object.entries(e.data || {})
      .filter(([k,v]) => v !== null && v !== undefined && !(Array.isArray(v) && v.length===0))
      .map(([k,v]) => `${k}=${Array.isArray(v)?v.join(","):v}`).join(", ");
    return d ? `<div>${e.event_type}: ${d}</div>` : `<div>${e.event_type}</div>`;
  }).join("");
}
let walkTimers = [];
function stopWalk() {
  walkTimers.forEach(clearTimeout);
  walkTimers = [];
  townEl.querySelectorAll(".walker").forEach(w => w.remove());
}
async function playQuestWalk(tid) {
  stopWalk();
  const paths = DATA.quest_paths[tid] || {};
  const anyData = DATA.configs.some(cfg => (paths[cfg]||[]).length);
  if (!anyData) return;

  DATA.configs.forEach((cfg, cfgIdx) => {
    const steps = paths[cfg] || [];
    if (!steps.length) return;
    // Collapse consecutive stage events at the same building into one stop,
    // merging their real event data for the speech-balloon.
    const stops = [];
    for (const s of steps) {
      const last = stops[stops.length - 1];
      if (last && last.building === s.building) {
        last.events.push(s);
      } else {
        stops.push({ building: s.building, icon: s.icon, label: s.label, events: [s] });
      }
    }
    const el = document.createElement("div");
    el.className = "walker";
    const color = CFG_COLOR[cfg] || "#888";
    const start = jitteredPos(cfg, PLOTS[stops[0].building] || PLOTS.home);
    el.style.left = start.x + "%";
    el.style.top = start.y + "%";
    el.innerHTML = `<span class="shadow-oval"></span><span class="sprite">${WALKER_SPRITE}</span>` +
      `<span class="chip" style="background:${color}">NPC-${cfg}</span>` +
      `<span class="balloon"><span class="balloon-summary"></span>` +
      `<span class="balloon-more">&#128172; dettagli</span>` +
      `<span class="balloon-detail"></span></span>` +
      `<span class="learning-badge">&#128161; Sto imparando!</span>`;
    townEl.appendChild(el);
    const balloon = el.querySelector(".balloon");
    // Fixed vertical lane per config, so when 2+ NPCs share a building their
    // balloons stack instead of overlapping -- independent of the (small,
    // now purely cosmetic) walker jitter above.
    balloon.style.bottom = (26 + (CFG_LANE[cfg] ?? 0) * 44) + "px";
    const summaryEl = el.querySelector(".balloon-summary");
    const detailEl = el.querySelector(".balloon-detail");
    balloon.addEventListener("click", () => balloon.classList.toggle("expanded"));

    let t = cfgIdx * 400; // stagger so overlapping NPCs are easy to follow one at a time
    stops.forEach((stop, i) => {
      const pos = jitteredPos(cfg, PLOTS[stop.building] || PLOTS.home);
      walkTimers.push(setTimeout(() => {
        el.classList.add("walking");
        el.classList.remove("talking", "learning");
        balloon.classList.remove("expanded");
        el.style.left = pos.x + "%";
        el.style.top = pos.y + "%";
      }, t));
      t += 1900; // matches the .walker CSS transition duration -- keep in sync if that changes
      walkTimers.push(setTimeout(() => {
        el.classList.remove("walking");
        el.classList.toggle("learning", stop.building === "library");
        el.classList.toggle("talking", stop.building !== "library");
        summaryEl.innerHTML = `<b>${stop.icon} NPC-${cfg}</b> ${summarizeStop(stop, cfg)}`;
        detailEl.innerHTML = rawDetailHtml(stop);
      }, t));
      t += 1700; // pause at the building so the speech balloon is readable before moving on
    });
  });
}
document.getElementById("replay-btn").addEventListener("click", () => {
  if (questSelectReady) playQuestWalk(questSelect.value);
});
let questSelectReady = false;

const questSelect = document.getElementById("quest-select");
questSelect.innerHTML = DATA.quest_order.map(tid => `<option value="${tid}">${tid}</option>`).join("");
const questPathsDiv = document.getElementById("quest-paths");
function renderQuestPaths() {
  const tid = questSelect.value;
  const paths = DATA.quest_paths[tid] || {};
  questPathsDiv.innerHTML = DATA.configs.map(cfg => {
    const steps = paths[cfg] || [];
    if (!steps.length) return `<div class="path"><span class="cfg-label">NPC-${cfg}</span><span class="missing">nessun dettaglio per-stage</span></div>`;
    const stepsHtml = steps.map((s,i) => {
      const detail = Object.entries(s.data).filter(([k,v]) => v !== null && v !== undefined && !(Array.isArray(v) && v.length===0))
        .map(([k,v]) => `${k}=${Array.isArray(v)?v.join(","):v}`).join(", ");
      const box = `<span class="stagebox" title="${s.event_type} @ ${s.timestamp}\n${detail}">${s.icon} ${s.label}</span>`;
      return i === 0 ? box : `<span class="arrow">&#8594;</span>${box}`;
    }).join("");
    return `<div class="path"><span class="cfg-label">NPC-${cfg}</span>${stepsHtml}</div>`;
  }).join("");
}
const questCostsDiv = document.getElementById("quest-costs");
function renderQuestCosts() {
  const tid = questSelect.value;
  const costs = DATA.quest_costs[tid] || {};
  questCostsDiv.innerHTML = DATA.configs.map(cfg => {
    const c = costs[cfg];
    if (!c || !c.rows.length) return `<div style="margin-bottom:10px"><b>NPC-${cfg}</b> -- <span class="missing">nessun dato di costo per-ruolo</span></div>`;
    const rows = c.rows.map(r => `<tr><td>${r.role}</td><td>${r.input_tokens}</td><td>${r.output_tokens}</td><td>${r.total}</td></tr>`).join("");
    return `<div style="margin-bottom:14px"><b>NPC-${cfg}</b>
      <table><tr><th>ruolo</th><th>input</th><th>output</th><th>totale</th></tr>${rows}
      <tr style="font-weight:bold"><td>TOTALE</td><td></td><td></td><td>${c.total}</td></tr></table></div>`;
  }).join("");
}
questSelect.addEventListener("change", () => {
  renderQuestPaths(); renderQuestCosts(); playQuestWalk(questSelect.value);
});
if (DATA.quest_order.length) {
  renderQuestPaths(); renderQuestCosts();
  questSelectReady = true;
  playQuestWalk(questSelect.value);
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m cognitive_rpg.city.report <experiment_id>", file=sys.stderr)
        sys.exit(1)
    path = generate(sys.argv[1])
    print(f"[city] scritto {path}")
