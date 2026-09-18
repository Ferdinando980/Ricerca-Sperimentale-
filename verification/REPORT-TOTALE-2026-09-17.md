# Report totale — motore di verifica della sostituzione meccanica (2026-09-17)

Sessione unica, continua. Ogni numero qui dentro è tracciabile a un file, un log o un run reale — niente è riassunto a memoria. Segue lo stesso standard di onestà di `THESIS.md`: risultati positivi e negativi hanno lo stesso peso, un fallimento capito vale quanto un successo.

## 0. Perché questa sessione esiste

Punto di partenza: il 2026-09-16 era stato costruito un primo motore (`substitution_ablation.py` + `skill_repair.py`) per rilevare quando un modello economico (Gemma) copia meccanicamente un valore letterale scritto in una skill invece di derivarlo dal caso reale — validato solo su `floating_point_equality`. Oggi l'obiettivo era: (1) generalizzarlo a tutta la libreria, (2) capire se regge su skill che non hanno un valore numerico ma un metodo fisso, come quelle che esisteranno davvero in Aria, e (3) quando trova un rischio, provare a ripararlo davvero, non solo segnalarlo.

## 1. Cosa esisteva prima di oggi vs cosa esiste ora

| | Prima (16/09) | Ora (17/09) |
|---|---|---|
| Assi di rilevamento | 1 (valore letterale, manuale) | 3 (valore letterale generico, regola generalizzabile su scenari contrastanti, metodo condizionato con trappola verificata da pytest) |
| Scelta dell'asse | Manuale, per skill nota | Automatica (`pattern_risk.py` prova prima l'asse numerico, poi quello a metodo) |
| Copertura testata | 1 pattern su 13 | 10 pattern su 13 (3 non hanno nessuno slot/metodo isolabile) |
| Riparazione | Solo per valore letterale | Anche per metodo condizionato (`method_repair.py`), con holdout sul task reale del catalogo invece di un probe generato |

## 2. I 6 bug reali trovati e corretti nel motore stesso

Nessuno di questi era nelle skill — tutti nel codice di verifica scritto oggi/ieri, trovati eseguendo il motore su dati reali, non per ispezione.

1. **Token cap troppo basso per un modello reasoning** (`slot_identifier.py`, giudice di estrazione): `max_tokens=64` troncava la risposta JSON a metà (`'{"matched'` o stringa vuota) — stesso tipo di bug già documentato altrove nel progetto per `gemini-3.7-flash`. Alzato a 1024.
2. **Il giudice troncava i numeri in notazione scientifica** ("3.3e-4" → "3.3"), facendo fallire il confronto esatto e sottostimando il tracking a 0/12 sul primissimo run reale di libreria. Risolto facendo scegliere al giudice l'**indice** del candidato invece di ritrascriverlo — il valore restituito è sempre esatto per costruzione, non una ritrascrizione del modello.
3. **Selezione della versione sbagliata di una skill**: 3 pattern (`index_out_of_range_boundary`, `off_by_one`, `wrong_comparison_operator`) hanno sia una versione vecchia che una nuova live contemporaneamente in `library/books/`. Diversi script prendevano la prima per ordine alfabetico dei file invece della più recente ("_v2_v3.yaml" ordina prima di "_v2_v3_v4.yaml" perché `.` < `_`) — hanno analizzato `wrong_comparison_operator` v3 invece di v4 senza nessun errore visibile. Corretto riusando `_latest_per_pattern` del Librarian reale in tutti gli script.
4. **Holdout mai usato**: il vero task KNOWN del catalogo (`domain/task_generator.py`, hand-verificato dalla prima sessione del progetto) non veniva mai usato come test di non-regressione — solo un probe di categoria A generato al volo, che a volte falliva a generarsi. Questo aveva bloccato la riparazione di `floating_point_equality` in mattinata (`HIGH_RISK_UNRESOLVED`). Estratto in `holdout.py`, reso la fonte preferita sia per il motore numerico che per quello a metodo.
5. **Crash su Unicode in console Windows**: il testo originale di `wrong_comparison_operator` contiene la freccia "↔" — un `print()` normale va in `UnicodeEncodeError` su cp1252, DOPO che il risultato vero era già stato calcolato. Corretto su tutti gli entry point (`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`).
6. **Denominatore incoerente nel confronto prima/dopo riparazione**: `method_repair.py` confrontava "meccanici / scenari totali" mentre il verdetto HIGH_RISK/LOW_RISK di `method_trap.py` usa "meccanici / (meccanici + evitati)" — gli scenari INCONCLUSIVE diluivano il rapporto in un calcolo ma non nell'altro, con lo stesso identico dato potendo apparire "33%" in un posto e "100%" nell'altro. Unificato su un solo calcolo (`_conclusive_ratio`), riusato ovunque.

## 3. Risultato per pattern (13 totali)

| Pattern | Asse | Rischio confermato | Riparazione |
|---|---|---|---|
| `floating_point_equality` | numerico | **HIGH** (50%, coerente col finding storico) | **ACCETTATA** — v6, letterale rimosso, sostituito da procedura a livelli (dichiarato → convenzione nota → epsilon di macchina, mai un numero inventato) |
| `wrong_string_case_comparison` | metodo | **HIGH** (1/3–3/3 su run diversi) | **ACCETTATA** — v3, 100%→33% |
| `wrong_comparison_operator` | metodo | **HIGH** (3/3, robusto su più run) | **ACCETTATA** — v5, 100%→33%, con prompt di riparazione a scomposizione (vedi §4) |
| `integer_division_truncation` | metodo | **HIGH** (confermato su campione di 5) | **RIFIUTATA due volte** — 67%→67% poi 100%→100%, nessun miglioramento nemmeno con la scomposizione (vedi §4) |
| `mutable_default_argument` | numerico | LOW (33%) | non tentata (sotto soglia) |
| `off_by_one` | metodo | LOW (0/3 meccanici, 2 evitati) | non tentata |
| `key_error_missing_dict_check` | instabile | **3 esiti diversi su 3 run separati** (NO_SLOT / LOW 17% / regola che generalizza correttamente) | non tentata — vedi limite in §5 |
| `index_out_of_range_boundary` | nessuno | non misurabile (nessuno slot né metodo isolabile) | — |
| `inverted_boolean_logic` | nessuno | non misurabile | — |
| `wrong_accumulator_init` | nessuno | non misurabile oggi (testo compresso 3 volte dal 16/08, l'esempio originale è diventato un accenno vago) | — |

Nota: 8 di questi 13 pattern (`LOW_VALUE_RETRIEVAL_PATTERNS` in `librarian/librarian.py`) sono comunque saltati sempre da `route()` nella produzione reale oggi, per evidenza misurata su 75 quest reali — solo `floating_point_equality` e `wrong_string_case_comparison` sono davvero recuperati con beneficio dimostrato. Le riparazioni di questi due sono quindi le uniche con effetto immediato sul comportamento reale del sistema; le altre due sono comunque valide come validazione del meccanismo.

**Conseguenza reale, non solo un dato di ricerca**: le 3 skill riparate e accettate sono ora automaticamente le versioni LIVE della libreria (versione più alta = quella che il Librarian recupera). Non sono file da rivedere — sono già in produzione per qualunque run futuro.

## 4. Il ragionamento dietro ai fallimenti (richiesto esplicitamente, non solo il numero)

Le prime riparazioni tentate ("verifica esplicitamente se la condizione vale prima di applicare il metodo") hanno funzionato su `wrong_string_case_comparison` ma **non** su `integer_division_truncation` e `wrong_comparison_operator` — stesso schema di istruzione, esiti opposti. La causa non era la skill: era che la richiesta di "verificare" restava un **giudizio astratto**, e chiederlo con più insistenza non dà a un modello piccolo una capacità di giudizio che non ha.

Corretto scomponendo la condizione in un **segnale osservabile concreto + una mappatura diretta + un fallback esplicito** (lo stesso schema che aveva già funzionato per `floating_point_equality`: dichiarato → convenzione nota → default prudente). Risultato:
- **`wrong_comparison_operator`**: ha funzionato. Il segnale (parole come "at least"/"up to" nel testo/docstring, mappate direttamente a `>=`/`<=`) è lessicale — cercabile per pattern-matching testuale, non richiede capire il codice.
- **`integer_division_truncation`**: non ha funzionato, nemmeno con un segnale altrettanto concreto ("il risultato finisce dentro `[...]`/`range()` → `//`; finisce in un `return` combinato aritmeticamente → `/`"). Il caso critico (`calculate_median`) richiede **tracciare il valore fino al `return` e capire lo scopo della funzione** (è una mediana → serve una media per liste pari) — un salto di ragionamento più profondo del semplice pattern-matching testuale, e Gemma non lo fa in modo affidabile nemmeno quando gli viene detto esplicitamente di guardare l'uso downstream.

Conclusione onesta: non ogni fallimento di sostituzione meccanica si scompone allo stesso modo. Quando il segnale distintivo è **lessicale/superficiale**, decomporre il giudizio in una regola di pattern-matching funziona. Quando il segnale richiede **tracciare il flusso del valore e inferire lo scopo della funzione**, il limite non è nella scrittura della skill — è una capacità che questo modello specifico non ha, indipendentemente da come gli viene chiesto di usarla. Questo è di per sé un risultato di ricerca, non solo un fallimento di ingegneria del prompt.

## 5. Limiti dichiarati, non nascosti

- **Instabilità dell'identificazione**: `identify_slot`/`extract_rule`/`extract_method` non sono deterministici — lo stesso identico testo di `key_error_missing_dict_check` ha prodotto 3 conclusioni diverse in 3 run separati. Non ancora corretto: la soluzione proposta (votazione a maggioranza su più chiamate indipendenti, stesso principio già usato altrove nel progetto per non fidarsi di un campione solo) resta da implementare.
- **Costo non tracciato per intero**: solo le chiamate al modello sotto test (Gemma) dentro `substitution_ablation.py` hanno costo/token registrati per-evento. Le chiamate Expert (identificazione, generazione scenari, giudizio, riscrittura) non sono ancora loggate per-chiamata — un costo reale, non contabilizzato, non assente.
- **n piccolo ovunque**: 3-5 scenari per pattern, un run per condizione. Un singolo tracking ratio può muoversi per rumore campionario; le conclusioni qualitative (HIGH vs LOW) sono più solide dei numeri esatti.
- **`wrong_accumulator_init`/`index_out_of_range_boundary`/`inverted_boolean_logic`**: "non misurabile" non equivale a "sicuro" — nessuno dei due assi si applica, punto. Andrebbero eventualmente affrontati con un terzo tipo di test, non ancora progettato.
- **Modalità audit statico** (`static_audit.py`, direttive fisse nel codice dell'app, non nella libreria Book): costruita e testabile, ma non ancora eseguita per davvero in questa sessione.

## 6. Lato Aria (`Jarvis/`) — Workstream B, punti 1 e 2 spediti, punto 3 in coda

- **Punto 1 — verifica comportamentale reale**: `skillOptimizer.ts` ora esegue un vero test comportamentale (stesso scenario reale, canonica vs variante, giudicato contro il criterio di riuscita dichiarato dalla skill) prima di accettare una variante runtime — non solo un giudizio testuale auto-riferito. Scoperto e corretto nello stesso passaggio: `testEvidencePassed` veniva già passato come `false` letterale a un gate che comunque lo ignorava (`requiresTestEvidence: false` per il namespace `application`) — ora conta per davvero. `tsc`, `oxlint` e un nuovo test in `archivist-evaluation.test.mjs` passano.
- **Punto 2 — rischio di sostituzione per skill `method`**: nuovo `skillSubstitutionRisk.ts`, porting concettuale di `slot_identifier.py`, integrato (informativo, non un gate) nello stesso passaggio dell'optimizer. Limite dichiarato esplicitamente nel codice: qui non esiste un oracolo pytest come in `cognitive_rpg` — lo scenario e il "valore atteso" sono auto-dichiarati dallo stesso modello che li genera, un segnale più debole della controparte Python.
- **Punto 3 — estendere l'automazione alle skill personali**: messo in coda esplicitamente dall'utente ("una cosa alla volta"). Non iniziato.
- **Scoperta collaterale, non risolta**: `pages/Ricerca.tsx` descrive in un commento dettagliato una funzione di confronto cieco umano (`pairedComparisons`/`researchComparison`) che **non ha alcuna implementazione funzionante nel codice committato attuale** — solo il commento e i tipi/store esistono, zero punti di chiamata reali. Non toccato oggi, segnalato qui perché il piano originale di Workstream B faceva riferimento a quel meccanismo come "già costruito."

## 7. File toccati oggi

Nuovi in `cognitive_rpg/verification/`: `slot_identifier.py` (riscritto), `library_benchmark.py`, `rule_generalization.py`, `method_trap.py`, `method_repair.py`, `pattern_risk.py`, `holdout.py`, `recap.py`, `static_audit.py`, più gli script `run_*.py`/`validate_*.py` corrispondenti.

Nuove versioni di skill salvate in `cognitive_rpg/library/books/`: `book_floating_point_equality_v4_v5_v6.yaml`, `book_wrong_string_case_comparison_v2_v3.yaml`, `book_wrong_comparison_operator_v2_v3_v4_v5.yaml`.

Modificati in `Jarvis/src/lib/`: `skillOptimizer.ts`, `skillOptimizerRun.ts`, `archivists/optimizerPolicy.ts`; nuovo `skillSubstitutionRisk.ts`; test aggiornato in `Jarvis/tests/archivist-evaluation.test.mjs`.

Grafo del codice (`graphify update .`) rigenerato dopo le modifiche.

## 8. Prossimi passi possibili, non decisi

- Votazione a maggioranza per stabilizzare `identify_slot`/`extract_rule`/`extract_method`.
- Tracciamento del costo reale anche per le chiamate Expert.
- Eseguire `static_audit.py` per davvero sulle direttive fisse dell'app.
- Un terzo asse di test per i pattern "non misurabili" (strutturali puri, né valore né metodo condizionato).
- Workstream B punto 3 (Aria, skill personali) — in coda.
- Un run reale di `experiment_0` con le 3 skill riparate live, per confermare che il miglioramento si vede anche nella pipeline A/B/F/C completa, non solo nel test isolato.
