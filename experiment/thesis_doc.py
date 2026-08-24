"""Thesis-style methodology + live-results document (conversation
2026-08-18: "documentazione stile tesi con legenda di come leggere tutto e
formule etc, la aggiorni in tempo reale"). The methodology/glossary prose is
static; every number in the "Risultati correnti" section is pulled live from
the same experiment/metrics.py, experiment/economics.py and
experiment/knowledge_map.py functions every other report already uses --
nothing here is a new measurement, only a differently-written presentation
of it, aimed at explaining the metrics rather than just tabulating them.

Run: python -m cognitive_rpg.experiment.thesis_doc <experiment_id>
Writes logs/{experiment_id}/thesis.html. "Real-time" in practice means:
rerun this script (cheap, local-only, no API calls) any time you want the
numbers current, then republish the same file as an Artifact to the same
URL -- there is no live connection to the local filesystem from a published
page, so "live" is "regenerate + redeploy", not a push update.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..domain.task_generator import generate_tasks
from . import economics, metrics
from .events import read_events, read_events_all_experiments
from .experiment_log import read_all
from .knowledge_map import section_rows

CONFIG_META = {
    "A": {"label": "Expert da solo", "short": "Expert", "css": "cfg-a"},
    "B": {"label": "Small da solo", "short": "Small", "css": "cfg-b"},
    "F": {"label": "Small + Skill Library", "short": "Skill", "css": "cfg-f"},
    "C": {"label": "Small + Solution Bank (Cheater)", "short": "Cheater", "css": "cfg-c"},
}


def _pct(x):
    return f"{x:.1%}" if x is not None else "n/d"


def _swatch(cfg):
    return f'<span class="swatch {CONFIG_META[cfg]["css"]}"></span>{cfg}'


def gather(experiment_id: str) -> dict:
    records = read_all(experiment_id)
    events = read_events(experiment_id)
    tasks = generate_tasks(seed=42)
    tasks_by_id = {t.task_id: t for t in tasks}

    done = {(r["task_id"], r["config_name"]) for r in records}
    total = len(tasks) * len(CONFIG_META)

    overall = metrics.overall(records)
    by_split = metrics.by_config_split(records)
    by_coverage = metrics.by_config_coverage(records)
    token_acc = metrics.token_accounting(records)
    amort = metrics.skill_amortization(events, records, build_cost_events=read_events_all_experiments())
    econ = economics.economic_classification(experiment_id) if records else []
    density = economics.library_density()
    sections = section_rows(experiment_id) if records else []

    return {
        "experiment_id": experiment_id,
        "n_tasks": len(tasks),
        "done": len(done),
        "total": total,
        "mixed_provider": metrics.mixed_provider_warnings(records),
        "defect_warnings": metrics.benchmark_defect_warnings(records),
        "finding_warnings": metrics.skill_finding_warnings(records, tasks_by_id),
        "retrieval_waste": metrics.retrieval_waste_analysis(records),
        "records": records,
        "overall": overall,
        "by_split": by_split,
        "by_coverage": by_coverage,
        "token_acc": token_acc,
        "amort": amort,
        "econ": econ,
        "density": density,
        "sections": sections,
        "tasks_by_id": tasks_by_id,
    }


_CSS = """
:root{
  --paper:#F6F7F9; --surface:#FFFFFF; --ink:#171B24; --ink-muted:#4B5163;
  --line:#DEE1E7; --accent:#1D6E63; --accent-ink:#0E4740;
  --cfg-a:#55606E; --cfg-b:#B4791F; --cfg-f:#1D6E63; --cfg-c:#7D5AA6;
  --good:#1D7A46; --bad:#B23B3B;
  --font-display:'Newsreader',Georgia,'Times New Roman',serif;
  --font-body:'IBM Plex Sans',system-ui,-apple-system,sans-serif;
  --font-mono:'IBM Plex Mono','SFMono-Regular',Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#12151B; --surface:#1A1E27; --ink:#E7E9EE; --ink-muted:#9CA3B4;
    --line:#2A2F3B; --accent:#4FB3A3; --accent-ink:#8FD8CB;
    --cfg-a:#8891A0; --cfg-b:#D9A34E; --cfg-f:#4FB3A3; --cfg-c:#A98BD1;
    --good:#4CAF7D; --bad:#E07070;
  }
}
:root[data-theme="dark"]{
  --paper:#12151B; --surface:#1A1E27; --ink:#E7E9EE; --ink-muted:#9CA3B4;
  --line:#2A2F3B; --accent:#4FB3A3; --accent-ink:#8FD8CB;
  --cfg-a:#8891A0; --cfg-b:#D9A34E; --cfg-f:#4FB3A3; --cfg-c:#A98BD1;
  --good:#4CAF7D; --bad:#E07070;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:var(--font-body); font-size:16px; line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
.shell{display:grid; grid-template-columns:240px minmax(0,1fr); gap:0; max-width:1180px; margin:0 auto;}
nav.toc{
  position:sticky; top:0; align-self:start; height:100vh; overflow-y:auto;
  padding:2.5rem 1.25rem 2rem 1.5rem; border-right:1px solid var(--line);
}
nav.toc .eyebrow{
  font-family:var(--font-mono); font-size:.72rem; letter-spacing:.08em;
  text-transform:uppercase; color:var(--ink-muted); margin:0 0 1rem;
}
nav.toc ol{list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:.15rem;}
nav.toc a{
  display:block; padding:.4rem .6rem; border-radius:4px; text-decoration:none;
  color:var(--ink-muted); font-size:.88rem; border-left:2px solid transparent;
}
nav.toc a:hover{color:var(--ink); background:color-mix(in srgb, var(--accent) 8%, transparent);}
nav.toc .live-badge{
  margin-top:1.5rem; padding:.6rem .7rem; border:1px solid var(--line); border-radius:6px;
  font-family:var(--font-mono); font-size:.72rem; color:var(--ink-muted); line-height:1.5;
}
nav.toc .live-badge .dot{
  display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--good);
  margin-right:.4em; box-shadow:0 0 0 3px color-mix(in srgb, var(--good) 25%, transparent);
}
main{padding:2.5rem 3rem 6rem; min-width:0;}
.title-block{margin-bottom:3rem;}
.title-block .eyebrow{
  font-family:var(--font-mono); font-size:.75rem; letter-spacing:.09em;
  text-transform:uppercase; color:var(--accent-ink); margin:0 0 .8rem;
}
h1{
  font-family:var(--font-display); font-weight:600; font-size:2.6rem;
  line-height:1.15; margin:0 0 .6rem; text-wrap:balance;
}
.subtitle{
  font-family:var(--font-display); font-style:italic; font-size:1.15rem;
  color:var(--ink-muted); max-width:52ch; margin:0; text-wrap:balance;
}
section{max-width:68ch; margin:0 0 3.2rem;}
section.wide{max-width:none;}
h2{
  font-family:var(--font-display); font-weight:600; font-size:1.55rem;
  margin:0 0 .3rem; text-wrap:balance; display:flex; align-items:baseline; gap:.6rem;
}
h2 .num{font-family:var(--font-mono); font-size:.85rem; color:var(--ink-muted); font-weight:400;}
h3{font-family:var(--font-display); font-weight:600; font-size:1.15rem; margin:1.6rem 0 .5rem;}
p{margin:0 0 1rem;}
.lede{color:var(--ink-muted); font-size:.95rem; margin-bottom:1.6rem;}
strong{font-weight:600;}
code, .mono{font-family:var(--font-mono); font-size:.86em;}
code{
  background:color-mix(in srgb, var(--ink) 6%, transparent); padding:.1em .35em;
  border-radius:3px;
}
.formula{
  font-family:var(--font-mono); font-size:.92rem; background:var(--surface);
  border:1px solid var(--line); border-left:3px solid var(--accent);
  padding:.85rem 1.1rem; border-radius:4px; margin:.7rem 0 1.1rem;
  overflow-x:auto; white-space:pre;
}
dl.glossary{margin:0;}
dl.glossary dt{
  font-family:var(--font-mono); font-weight:600; font-size:.95rem;
  color:var(--ink); margin-top:1.4rem; padding-top:1.4rem; border-top:1px solid var(--line);
}
dl.glossary dt:first-child{margin-top:0; padding-top:0; border-top:none;}
dl.glossary dd{margin:.4rem 0 0; color:var(--ink-muted);}
.table-wrap{overflow-x:auto; border:1px solid var(--line); border-radius:6px; margin:0 0 1.5rem;}
table{border-collapse:collapse; width:100%; font-size:.9rem;}
th, td{
  text-align:left; padding:.55rem .8rem; border-bottom:1px solid var(--line);
  white-space:nowrap;
}
thead th{
  font-family:var(--font-mono); font-size:.72rem; letter-spacing:.04em;
  text-transform:uppercase; color:var(--ink-muted); background:var(--surface);
  border-bottom:1px solid var(--line);
}
tbody tr:last-child td{border-bottom:none;}
td.num, th.num{font-variant-numeric:tabular-nums; font-family:var(--font-mono); text-align:right;}
.swatch{display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:.45em; vertical-align:middle;}
.cfg-a{background:var(--cfg-a);} .cfg-b{background:var(--cfg-b);}
.cfg-f{background:var(--cfg-f);} .cfg-c{background:var(--cfg-c);}
.pass{color:var(--good); font-weight:600;} .fail{color:var(--bad); font-weight:600;}
.bar-track{background:color-mix(in srgb, var(--ink) 8%, transparent); border-radius:3px; height:6px; overflow:hidden; min-width:64px;}
.bar-fill{height:100%; background:var(--accent); border-radius:3px;}
.stat-row{display:flex; align-items:center; gap:.6rem;}
.grid-cards{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.9rem; margin:0 0 1.6rem;}
.card{
  background:var(--surface); border:1px solid var(--line); border-radius:8px;
  padding:1rem 1.1rem;
}
.card .k{font-family:var(--font-mono); font-size:.7rem; letter-spacing:.05em; text-transform:uppercase; color:var(--ink-muted); margin:0 0 .35rem;}
.card .v{font-family:var(--font-display); font-size:1.7rem; font-weight:600; font-variant-numeric:tabular-nums;}
.note{
  font-size:.88rem; color:var(--ink-muted); background:var(--surface);
  border:1px solid var(--line); border-radius:6px; padding:.8rem 1rem; margin:.8rem 0 0;
}
.warn{
  font-size:.88rem; color:var(--ink); background:color-mix(in srgb, var(--bad) 10%, var(--surface));
  border:1px solid var(--bad); border-radius:6px; padding:.8rem 1rem; margin:.8rem 0 0;
}
.warn ul{margin:.4rem 0 0; padding-left:1.2rem;}
.footer{
  max-width:68ch; margin-top:4rem; padding-top:1.5rem; border-top:1px solid var(--line);
  font-size:.82rem; color:var(--ink-muted);
}
@media (max-width:860px){
  .shell{grid-template-columns:1fr;}
  nav.toc{position:static; height:auto; border-right:none; border-bottom:1px solid var(--line);}
  main{padding:2rem 1.25rem 4rem;}
  h1{font-size:2rem;}
}
"""

_FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,500;0,600;1,500&'
    'family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">'
)


def _toc():
    items = [
        ("intro", "1. Domanda di ricerca"),
        ("design", "2. Disegno sperimentale"),
        ("glossario", "3. Glossario e formule"),
        ("leggere", "4. Dove trovare cosa"),
        ("risultati", "5. Risultati correnti"),
        ("limiti", "6. Limiti e metodo"),
    ]
    rows = "".join(f'<li><a href="#{i}">{t}</a></li>' for i, t in items)
    return f'<nav class="toc"><p class="eyebrow">Indice</p><ol>{rows}</ol></nav>'


def build_html(experiment_id: str) -> str:
    d = gather(experiment_id)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    generated_note = f'<span class="dot"></span>Ultimo aggiornamento<br>{now}<br>experiment_id: <code>{experiment_id}</code>'

    L = []
    L.append(f"<title>Memoria vs Competenza</title>{_FONT_LINK}<style>{_CSS}</style>")
    L.append('<div class="shell">')
    L.append(_toc().replace("</ol>", f'</ol><div class="live-badge">{generated_note}</div>'))
    L.append('<main>')

    # ---- title block ----
    L.append('<div class="title-block">')
    L.append('<p class="eyebrow">Cognitive RPG &middot; note di metodologia</p>')
    L.append('<h1>Memoria vs Competenza</h1>')
    L.append(
        '<p class="subtitle">Quanto della performance di un modello economico assistito '
        'deriva da una capacita’ generalizzabile, e quanto dall’aver semplicemente '
        'gia’ visto la risposta?</p>'
    )
    L.append('</div>')

    # ---- 1. intro ----
    L.append('<section id="intro">')
    L.append('<h2><span class="num">&sect;1</span>Domanda di ricerca</h2>')
    L.append(
        '<p>Un modello linguistico piccolo ed economico (<strong>Small</strong>) puo’ '
        'avvicinarsi a un modello grande e costoso (<strong>Expert</strong>) su un compito di '
        'debugging, se gli si da’ accesso a conoscenza esterna? E se si’, quella conoscenza '
        'deve essere generalizzabile — una <em>procedura</em> — o basta una '
        '<em>soluzione specifica</em> gia’ vista in precedenza?</p>'
    )
    L.append(
        '<p>Il secondo caso e’ il punto centrale: un sistema che sembra "imparare" '
        'potrebbe in realta’ star solo recuperando risposte memorizzate. Questo documento '
        'confronta quattro configurazioni sperimentali costruite apposta per separare le due '
        'ipotesi, e riporta i risultati correnti mano a mano che l’esperimento avanza.</p>'
    )
    L.append('</section>')

    # ---- 2. design ----
    L.append('<section id="design">')
    L.append('<h2><span class="num">&sect;2</span>Disegno sperimentale</h2>')
    L.append(
        '<p>Ogni task e’ una funzione Python con un bug reale, verificata con test '
        'automatici (pytest) — il risultato non e’ mai un giudizio soggettivo, e’ un '
        'pass/fail eseguibile. Lo stesso task viene affrontato da quattro configurazioni:</p>'
    )
    L.append('<div class="grid-cards">')
    for cfg, meta in CONFIG_META.items():
        L.append(
            f'<div class="card"><p class="k"><span class="swatch {meta["css"]}"></span>{cfg}</p>'
            f'<p class="v" style="font-size:1.1rem">{meta["label"]}</p></div>'
        )
    L.append('</div>')
    L.append(
        '<p><strong>A</strong> ed <strong>B</strong> sono le due baseline pure (nessun aiuto '
        'esterno). <strong>F</strong> riceve, quando pertinente, una skill scritta a mano o '
        'generata (Skill Library) — una procedura di debugging generale, non legata a un '
        'problema specifico. <strong>C</strong> riceve invece, quando disponibile, una '
        '<em>soluzione</em> gia’ corretta a un problema pregresso (Solution Bank) — non '
        'una procedura, un esempio risolto specifico.</p>'
    )
    L.append('<h3>Split KNOWN / VARIANT / NOVEL</h3>')
    L.append(
        '<p>Ogni pattern di bug ha un esempio canonico ("known_example") e almeno una '
        'variante ("variant", stesso pattern, problema diverso). Un task e’ <strong>KNOWN</strong> '
        'se e’ l’esempio canonico stesso di un pattern coperto, <strong>VARIANT</strong> se e’ '
        'un problema diverso dello stesso pattern coperto, <strong>NOVEL</strong> se il pattern non '
        'e’ coperto affatto. Alcuni pattern sono <em>permanentemente</em> NOVEL per design: sono '
        'il gruppo di controllo, nessuna skill/soluzione viene mai costruita per loro.</p>'
    )
    L.append('<h3>Coverage NONE / PARTIAL / FULL</h3>')
    L.append(
        '<p>Per F e C, ogni retrieval produce una coverage: <strong>NONE</strong> (niente di '
        'pertinente trovato — F/C degradano a comportarsi come B), <strong>FULL</strong> '
        '(match esatto/completo — per F un book copre tutti i tag del task, per C il task '
        'e’ lo stesso identico problema di cui esiste soluzione), <strong>PARTIAL</strong> '
        '(match parziale — per C, la soluzione disponibile e’ di un problema diverso ma '
        'della stessa famiglia).</p>'
    )
    L.append('</section>')

    # ---- 3. glossario ----
    L.append('<section id="glossario">')
    L.append('<h2><span class="num">&sect;3</span>Glossario e formule</h2>')
    L.append(
        '<p class="lede">Ogni metrica usata nei report (<code>recap.md</code>, '
        '<code>knowledge_map.md</code>) e in questa pagina, con la formula esatta.</p>'
    )
    L.append('<dl class="glossary">')

    def gterm(name, formula, note):
        f = f'<div class="formula">{formula}</div>' if formula else ""
        return f'<dt>{name}</dt>{f}<dd>{note}</dd>'

    L.append(gterm(
        "accuracy", "accuracy = quest_passate / quest_totali",
        "Per una singola config, o per (config, split), o per (config, coverage) -- sempre la stessa formula, cambia solo il gruppo su cui si conta."
    ))
    L.append(gterm(
        "tok/task", "tok_per_task = token_totali / n_task",
        "Token medi per quest, indipendentemente dal risultato."
    ))
    L.append(gterm(
        "tok/successo", "tok_per_successo = token_totali / quest_passate",
        "Non lo stesso di tok/task: un config con qualche fallimento sta comunque spendendo quei token senza un risultato utile -- confronto piu' onesto quando le accuracy non sono identiche tra config."
    ))
    L.append(gterm(
        "Δ F vs B / Δ C vs B / Δ C vs F",
        "delta = accuracy(config_1) − accuracy(config_2)",
        "Differenza diretta di accuracy tra due config sull'intero dataset. Δ C vs F e' la domanda centrale del Cheater Agent: soluzione specifica contro skill generalizzata."
    ))
    L.append(gterm(
        "Δ Retrieval",
        "delta_retrieval = accuracy(coverage=FULL) − accuracy(coverage=NONE)   [dentro lo stesso config, F o C]",
        "Isola l'effetto del retrieval stesso: se e' vicino a zero, avere il meccanismo non aiuta quando non trova nulla -- atteso. Se e' grande e positivo, trovare qualcosa di pertinente conta davvero."
    ))
    L.append(gterm(
        "Δ Architecture",
        "delta_architecture = accuracy(config-FULL) − accuracy(B)",
        "Quanto l'intera architettura (non solo il retrieval) supera il modello nudo, guardando solo ai casi in cui il retrieval ha trovato qualcosa."
    ))
    L.append(gterm(
        "build_cost (ammortamento skill)",
        "build_cost = token spesi dall'Optimizer per comprimere/riverificare quello skill (ogni tentativo, accettato o no)",
        "Costo una tantum per pattern, non per uso."
    ))
    L.append(gterm(
        "breakeven",
        "saving = tok_medi(A) − tok_medi(F)  sui task di quel pattern\nbreakeven = build_cost / saving   (se saving > 0, altrimenti mai)",
        "Dopo quanti usi il costo di costruzione dello skill si ripaga rispetto a chiamare sempre Expert."
    ))
    L.append(gterm(
        "classificazione economica",
        "economic_value = HIGH  se saving > 0  e  breakeven <= 20 usi\naccuracy_value = HIGH  se F ha risolto un task che A o B avevano fallito\n\nlabel = ECONOMICALLY_POSITIVE  se economic_value = HIGH\n        ACCURACY_POSITIVE      se economic_value = LOW e accuracy_value = HIGH\n        NEGATIVE               se entrambi LOW",
        "NEGATIVE non significa “elimina questo skill” -- puo' avere valore strategico non catturato da queste due sole metriche, specialmente con cosi' pochi dati."
    ))
    L.append(gterm(
        "densita’ della libreria",
        "densita = contenuti_distinti / file_su_disco\n(contenuti_distinti = cluster di file giudicati DUPLICATE dal Similarity Checker)",
        "Il numero di skill non e' la metrica giusta -- una libreria con 100 duplicati e' peggiore di una con 20 skill davvero distinte."
    ))
    L.append('</dl>')
    L.append('</section>')

    # ---- 4. leggere ----
    L.append('<section id="leggere">')
    L.append('<h2><span class="num">&sect;4</span>Dove trovare cosa</h2>')
    L.append(
        '<p>Tutto in <code>logs/{experiment_id}/</code>. <code>recap.md</code> e’ il '
        'riassunto testuale completo (9 sezioni: avanzamento, confronto A/B/F/C, retrieval vs '
        'architecture, token accounting, ammortamento skill, fallimenti, uso skill, optimizer, '
        'mappa sezioni). <code>knowledge_map.md</code> e’ il dettaglio per sezione/pattern di '
        'bug. <code>observer_table.csv</code>/<code>quest_scores.csv</code> sono i dati grezzi '
        'per analisi esterne. <code>city.html</code> e’ la mappa visuale. Questa pagina '
        '(<code>thesis.html</code>) e’ generata da <code>experiment/thesis_doc.py</code>, '
        'rilanciabile in qualunque momento senza costo (nessuna chiamata ai modelli, solo '
        'lettura locale).</p>'
    )
    L.append('</section>')

    # ---- 5. risultati (LIVE) ----
    L.append('<section id="risultati" class="wide">')
    L.append('<h2><span class="num">&sect;5</span>Risultati correnti</h2>')
    L.append(
        f'<p class="lede">Rigenerato dal vivo da <code>{experiment_id}</code>: '
        f'{d["done"]}/{d["total"]} quest completate ({d["n_tasks"]} task &times; '
        f'{len(CONFIG_META)} config).</p>'
    )

    if d["defect_warnings"]:
        items = "".join(f"<li><code>{tid}</code>: {note}</li>" for tid, note in d["defect_warnings"])
        L.append(
            '<div class="warn"><strong>&#9888; Difetto noto nel benchmark stesso</strong> '
            f'(non nello skill/config in esame) -- i risultati su questi task non '
            f'significano quello che sembrano:<ul>{items}</ul></div>'
        )

    if d["finding_warnings"]:
        items = "".join(f"<li><code>{p}</code>: {note}</li>" for p, note in d["finding_warnings"])
        L.append(
            '<div class="warn"><strong>&#128300; Meccanismo dello skill dimostrato '
            'causalmente</strong> (non solo osservato per correlazione) -- da tenere '
            f'presente leggendo i numeri di F su questo pattern:<ul>{items}</ul></div>'
        )

    if d["mixed_provider"]:
        items = "".join(f"<li>{w.replace('**', '')}</li>" for w in d["mixed_provider"])
        L.append(
            '<div class="warn"><strong>&#9888; Provider/modello misto dentro questo run</strong> '
            '-- questi config hanno usato piu\' di una combinazione provider/modello '
            '(probabile switch a meta\' run): confronti tra config diversi restano validi, '
            f'ma se citi questi numeri in modo formale tienilo presente.<ul>{items}</ul></div>'
        )

    w = d["retrieval_waste"]
    if w["n_injected"] > 0:
        waste_pct = w["n_waste"] / w["n_injected"]
        helped = ", ".join(sorted(w["helped_patterns"])) or "(nessuno)"
        L.append(
            '<div class="warn"><strong>&#128184; Analisi controfattuale costo di retrieval</strong> '
            f'(F vs B stesso task, zero chiamate nuove) -- su {w["n_injected"]} quest con skill '
            f'iniettata, <strong>{w["n_waste"]} ({waste_pct:.1%})</strong> hanno visto B passare '
            f'comunque senza aiuto (overhead pagato senza beneficio misurato, {w["wasted_tokens"]} '
            f'token totali); {w["n_helped"]} mostrano un beneficio reale; {w["n_hurt"]} mostrano lo '
            f'skill peggiorare l\'esito. Pattern con beneficio misurato in questo run: {helped}.</div>'
        )

    if not d["records"]:
        L.append('<p class="note">Nessuna quest completata ancora per questo experiment_id.</p>')
    else:
        # summary cards
        L.append('<div class="grid-cards">')
        for cfg, meta in CONFIG_META.items():
            b = d["overall"].get(cfg)
            if not b or not b["n"]:
                continue
            acc = b["passed"] / b["n"]
            L.append(
                f'<div class="card"><p class="k"><span class="swatch {meta["css"]}"></span>'
                f'{cfg} &mdash; {meta["short"]}</p><p class="v">{_pct(acc)}</p>'
                f'<p class="note" style="margin-top:.5rem">n={b["n"]}</p></div>'
            )
        L.append('</div>')

        # accuracy by split
        L.append('<h3>Accuracy per config &times; split</h3>')
        L.append('<div class="table-wrap"><table><thead><tr>'
                  '<th>config</th><th>split</th><th class="num">n</th><th class="num">accuracy</th>'
                  '<th>&nbsp;</th></tr></thead><tbody>')
        for (cfg, split), b in sorted(d["by_split"].items()):
            acc = b["passed"] / b["n"] if b["n"] else 0.0
            width = max(2, round(acc * 100))
            L.append(
                f'<tr><td>{_swatch(cfg)}</td><td>{split}</td><td class="num">{b["n"]}</td>'
                f'<td class="num">{_pct(acc)}</td>'
                f'<td><div class="bar-track" style="width:90px"><div class="bar-fill" '
                f'style="width:{width}%"></div></div></td></tr>'
            )
        L.append('</tbody></table></div>')

        # retrieval vs architecture
        b_ov = d["overall"].get("B")
        b_acc = b_ov["passed"] / b_ov["n"] if b_ov and b_ov["n"] else None
        for retrieval_cfg in ("F", "C"):
            rows = {c: b for (cfg, c), b in d["by_coverage"].items() if cfg == retrieval_cfg}
            if not rows:
                continue
            L.append(f'<h3>{_swatch(retrieval_cfg)} {CONFIG_META[retrieval_cfg]["label"]} &mdash; per coverage</h3>')
            L.append('<div class="table-wrap"><table><thead><tr><th>coverage</th>'
                      '<th class="num">n</th><th class="num">accuracy</th></tr></thead><tbody>')
            for cov in ("NONE", "PARTIAL", "FULL"):
                b = rows.get(cov)
                if not b:
                    continue
                acc = b["passed"] / b["n"] if b["n"] else 0.0
                L.append(f'<tr><td>{cov}</td><td class="num">{b["n"]}</td><td class="num">{_pct(acc)}</td></tr>')
            L.append('</tbody></table></div>')
            none_b, full_b = rows.get("NONE"), rows.get("FULL")
            notes = []
            if none_b and full_b and none_b["n"] and full_b["n"]:
                dr = full_b["passed"] / full_b["n"] - none_b["passed"] / none_b["n"]
                notes.append(f"Δ Retrieval (FULL − NONE) = {dr:+.1%}")
            if full_b and full_b["n"] and b_acc is not None:
                da = full_b["passed"] / full_b["n"] - b_acc
                notes.append(f"Δ Architecture ({retrieval_cfg}-FULL − B) = {da:+.1%}")
            if notes:
                L.append(f'<p class="note">{" &nbsp;|&nbsp; ".join(notes)}</p>')

        # token accounting
        L.append('<h3>Token accounting</h3>')
        L.append('<div class="table-wrap"><table><thead><tr><th>config</th>'
                  '<th class="num">input</th><th class="num">output</th><th class="num">reasoning</th>'
                  '<th class="num">totale</th><th class="num">tok/task</th><th class="num">tok/successo</th>'
                  '</tr></thead><tbody>')
        for cfg in CONFIG_META:
            b = d["token_acc"].get(cfg)
            if not b or not b["n"]:
                continue
            total_tok = b["input"] + b["output"] + b["reasoning"]
            cfg_records = [r for r in d["records"] if r["config_name"] == cfg]
            n_passed = sum(1 for r in cfg_records if r["passed"])
            tok_succ = total_tok / n_passed if n_passed else float("inf")
            L.append(
                f'<tr><td>{_swatch(cfg)}</td><td class="num">{b["input"]}</td>'
                f'<td class="num">{b["output"]}</td><td class="num">{b["reasoning"]}</td>'
                f'<td class="num">{total_tok}</td><td class="num">{total_tok/b["n"]:.0f}</td>'
                f'<td class="num">{tok_succ:.0f}</td></tr>'
            )
        L.append('</tbody></table></div>')

        # economic classification
        if d["econ"]:
            L.append('<h3>Classificazione economica per pattern</h3>')
            L.append('<div class="table-wrap"><table><thead><tr><th>pattern</th>'
                      '<th>accuracy_value</th><th>economic_value</th><th>classificazione</th>'
                      '</tr></thead><tbody>')
            for r in d["econ"]:
                L.append(
                    f'<tr><td><code>{r["pattern"]}</code></td><td>{r["accuracy_value"]}</td>'
                    f'<td>{r["economic_value"]}</td><td>{r["label"]}</td></tr>'
                )
            L.append('</tbody></table></div>')

        # failures
        failures = [r for r in d["records"] if not r["passed"]]
        L.append('<h3>Quest fallite</h3>')
        if not failures:
            L.append('<p class="note">Nessun fallimento finora.</p>')
        else:
            L.append('<div class="table-wrap"><table><thead><tr><th>config</th><th>split</th>'
                      '<th>task</th></tr></thead><tbody>')
            for r in sorted(failures, key=lambda r: (r["config_name"], r["task_id"])):
                L.append(f'<tr><td>{_swatch(r["config_name"])}</td><td>{r["split"]}</td>'
                          f'<td><code>{r["task_id"]}</code></td></tr>')
            L.append('</tbody></table></div>')

    L.append('</section>')

    # ---- 6. limiti ----
    L.append('<section id="limiti">')
    L.append('<h2><span class="num">&sect;6</span>Limiti e metodo</h2>')
    L.append(
        '<p><strong>Campione piccolo</strong>: 1-2 task per (pattern, split) &mdash; una sola '
        'run per cella. Un singolo fallimento non basta per dire se e’ un problema '
        'sistematico o rumore del modello; serve ripetere lo stesso task piu’ volte per '
        'distinguerli.</p>'
    )
    L.append(
        '<p><strong>Solution Bank (C) usa il ground truth, non l’output reale '
        'dell’Expert</strong>: la "soluzione pregressa" del Cheater e’ il '
        '<code>correct_source</code> gia’ scritto in <code>bug_catalog.py</code>, non un '
        'transcript reale di quello che Expert ha effettivamente generato (mai persistito, '
        'per design, per non salvare output grezzo dei modelli). Proxy ragionevole -- A '
        'ottiene tipicamente il 95-100% di accuracy -- ma non identico.</p>'
    )
    L.append(
        '<p><strong>Costi a $0.00</strong> se il prezzo del provider non e’ configurato in '
        '<code>.env</code> &mdash; i confronti sui token restano validi, quelli in dollari no, '
        'finche’ non e’ impostato.</p>'
    )
    L.append('</section>')

    L.append(
        f'<div class="footer">Cognitive RPG &middot; generato da '
        f'<code>python -m cognitive_rpg.experiment.thesis_doc {experiment_id}</code> &middot; '
        f'{now}</div>'
    )

    L.append('</main></div>')
    return "\n".join(L)


def write(experiment_id: str) -> Path:
    html = build_html(experiment_id)
    out_path = config.experiment_dir(experiment_id) / "thesis.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    experiment_id = sys.argv[1] if len(sys.argv) > 1 else config.get_current_experiment_id()
    path = write(experiment_id)
    print(f"[thesis_doc] scritto {path}")
