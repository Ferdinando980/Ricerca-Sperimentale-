# Cognitive RPG

Un modello economico può avvicinarsi a un modello frontier su un compito di debugging, se gli dai accesso a conoscenza esterna? E se sì: quella conoscenza deve essere una procedura generale, o basta avergli già mostrato una soluzione simile in passato?

La seconda domanda è quella che conta davvero. Un sistema che sembra "imparare" potrebbe in realtà stare solo recuperando risposte già viste — e la differenza tra le due cose non si vede guardando solo l'accuracy finale, va isolata di proposito. Questo repo è un banco di prova per farlo: un ecosistema di agenti LLM piccoli ed economici che costruiscono una libreria di skill, la verificano con evidenza reale (mai sulla fiducia), e vengono messi a confronto contro un agente che invece riceve semplicemente una soluzione già pronta a un problema simile.

Il vocabolario RPG (Quest, Book, NPC, Librarian) è solo un layer intuitivo sopra meccanismi standard di retrieval, memoria procedurale e model routing — utile per orientarsi nel codice, non centrale alla ricerca in sé.

## Le quattro configurazioni

Ogni task è una funzione Python con un bug reale, verificata con `pytest`: il risultato non è mai un giudizio soggettivo, è un pass/fail eseguibile. Lo stesso task viene affrontato da quattro agenti diversi:

- **A — Expert da solo.** Il modello grande e costoso, nessun aiuto. La baseline "quanto costerebbe farlo bene sempre".
- **B — Small da solo.** Il modello economico, nessun aiuto. La baseline "quanto vale il modello nudo".
- **F — Small + Skill Library.** Riceve, quando pertinente, una skill scritta o generata da precedenti tentativi: una procedura di debugging generale, non legata a un problema specifico.
- **C — Small + Solution Bank ("il Cheater").** Riceve invece una soluzione già corretta a un problema *simile* già visto — non una procedura, un esempio risolto specifico.

C è il pezzo che manca in quasi ogni discussione su "skill library per LLM": se F batte B, è facile concludere che la libreria insegna qualcosa di generalizzabile. Ma se anche C batte B di una quantità simile, quel guadagno potrebbe non avere niente a che fare con l'aver imparato una procedura — basterebbe aver già visto un caso simile. Confrontare F contro C, non solo contro B, è l'unico modo per distinguere le due ipotesi.

Un dettaglio onesto sul Solution Bank: la "soluzione pregressa" che C riceve è la funzione corretta di riferimento già scritta nel catalogo dei bug, non un transcript reale di ciò che Expert ha effettivamente generato — questo codice non salva mai gli output grezzi dei modelli, per non tenere in giro niente che somigli a un chain-of-thought loggato. È un proxy ragionevole (A ottiene tipicamente 95-100% di accuracy, quindi "ciò che produce Expert" e "la soluzione di riferimento" coincidono quasi sempre), ma non è la stessa cosa, e va detto.

## Come si separa "trovato qualcosa" da "il meccanismo funziona"

Ogni task ha uno split — **KNOWN** (l'esempio canonico di un pattern di bug coperto), **VARIANT** (stesso pattern, problema diverso), **NOVEL** (pattern mai coperto, gruppo di controllo permanente: per tre pattern non viene mai scritta né una skill né una soluzione, di proposito). Su F e C, ogni retrieval registra anche una **coverage** — NONE (niente di pertinente trovato), FULL (match esatto), PARTIAL (solo per C: soluzione di un problema diverso della stessa famiglia).

La ragione per tracciare entrambe le cose separatamente: se F-NONE si comporta come B ma F-FULL fa meglio, allora è davvero il contenuto recuperato a spostare l'ago, non la sola presenza del meccanismo di retrieval. Il report per ogni run calcola due numeri per isolare esattamente questo — **Δ Retrieval** (FULL meno NONE, dentro la stessa config: quanto conta trovare qualcosa) e **Δ Architecture** (config-FULL meno B: quanto l'intera architettura supera il modello nudo quando il retrieval funziona).

## Recitazione o derivazione? Un test causale, non solo osservazionale

La parte più interessante emersa finora non è un numero di accuracy, è un metodo. Durante l'indagine sulla skill `floating_point_equality` (che insegna a scegliere un epsilon di tolleranza invece di un confronto esatto) è emerso un sospetto: su un task senza indizi numerici, F produceva sempre lo stesso valore (1e-9). Poteva essere che il modello stesse davvero ragionando sulla scala del problema, o semplicemente ripetendo una costante scritta nella skill.

Osservare la correlazione non basta a distinguerle. Quindi è stato fatto un test causale: manipolare direttamente la costante scritta nella skill (da 1e-9 a 2.5e-6 a 7e-4) e vedere se la risposta del modello cambiava in lockstep. È successo, 12 volte su 12, su due task scollegati tra loro — mentre manipolare una costante di una *diversa* sezione della skill (quella per la valuta) non aveva alcun effetto, 6 volte su 6, e nemmeno viceversa. Conclusione onesta: il modello sceglie correttamente quale regola applicare, ma dentro quella regola sostituisce meccanicamente il valore scritto — non deriva l'epsilon dalla scala del problema. Non è "citare un esempio" in senso vago, è sostituzione letterale di uno slot preciso.

Questo avrebbe potuto chiudere lì la questione, ma riscrivere la skill per chiedere esplicitamente una derivazione (invece di una costante fissa) ha fatto sì che il modello iniziasse davvero a derivare — seguendo correttamente la magnitudine del problema su un range di sette ordini di grandezza, con un solo errore aritmetico minore. Il collo di bottiglia non era una capacità mancante del modello: era il contenuto dell'istruzione. Dopo altri due giri di validazione e una correzione a un'affermazione precedente rivelatasi troppo generosa (un dominio che sembrava generalizzare bene in realtà non passava un controllo indipendente più severo), è emersa una conferma pulita su un dominio genuinamente diverso — cifre significative implicite in un confronto decimale — dove il modello ha prodotto due epsilon *diversi*, ciascuno corretto per la propria struttura decimale, nello stesso test. Un meccanismo di sostituzione meccanica non può produrre due numeri diversi entrambi corretti; solo una derivazione vera può.

Il codice di questo test vive in `experiment/canary.py`, con task sintetici mai visti dall'optimizer né dal generatore di skill (altrimenti la skill verrebbe scritta *per* passare il test, che è l'opposto di misurarlo). La cronologia completa — comprese le due autocorrezioni fatte quando un'affermazione precedente si è rivelata più debole di quanto sembrasse — resta nel changelog della skill e nei recap di ogni esperimento, non ripulita a posteriori. C'è anche una versione leggibile senza scavare nei log: `python -m cognitive_rpg.city.epsilon_lab` genera `logs/epsilon_lab.html`, domanda per domanda, con le risposte reali del modello trascritte a mano da quella sessione — non rigenerate, quelle vere.

## Cosa mostrano i cinque run completi

| run | n | A (Expert) | B (Small) | F (Skill Library) | C (Cheater) | F vs B |
|---|---|---|---|---|---|---|
| experiment0 | 26 | 100.0% | 88.5% | 96.2% | 92.3% | +7.7% |
| experiment1 | 21 | 95.2% | 95.2% | 100.0% | — | +4.8% |
| experiment2 | 26 | 96.2% | 84.6% | 96.2% | 96.2% | +11.5% |
| experiment3 | 4 | 50.0% | 50.0% | 75.0% | 50.0% | +25.0% |
| experiment4 | 39 | 97.4% | 92.3% | 97.4% | 97.4% | +5.1% |

F batte B in tutti e cinque, mai pari o peggio — aggregato su n=116, +7.8 punti percentuali. È un'inversione rispetto a quello che diceva questo README fino a poco tempo fa: il primissimo run (n=6-16, prima che questi cinque esistessero) non mostrava alcun beneficio, ed è rimasto per un po' come unica conclusione riportata qui. Non l'ho cancellato per pulizia — è comunque parte della storia — ma non era più vera e teneva questo documento indietro rispetto ai dati reali già disponibili nei log.

Due limiti veri, non nascosti sotto la tabella:

**Non sono repliche indipendenti pulite.** I cinque run condividono in gran parte lo stesso catalogo di task, e tra un run e l'altro l'Optimizer ha compresso e riverificato le skill esistenti (vedi la sezione Optimizer in ogni `recap.md`). Parte del vantaggio di F potrebbe riflettere la libreria che si affina su questi task specifici, non generalizzazione a task mai visti.

**Il guadagno non è uniforme, meccanismo per meccanismo.** L'esperimento4 (il run più completo, 156/156 quest) mostra C che eguaglia F su accuracy aggregata (97.4% entrambi) ma con un profilo diverso: la componente Δ Retrieval di C è a zero, mai negativa (FULL=100%, NONE=100%), mentre quella di F su questo run specifico è leggermente *negativa* (-3.2%, FULL fa peggio di NONE) — il meccanismo di retrieval di F in questo run trova qualcosa più spesso di quanto aiuti. Il dettaglio del task-per-task, con i fallimenti e il perché, è in `logs/experiment4/recap.md` e nella pagina generata `logs/experiment4/thesis.html` (rilanciabile gratis con `python -m cognitive_rpg.experiment.thesis_doc experiment4`, nessuna chiamata ai modelli).

Sul costo: F paga in media tra +116 e +343 token di input in più rispetto a B per usare una skill già pronta (l'"overhead di retrieval", diverso in ogni run a seconda di quali skill vengono recuperate), mentre costruire una skill nuova (l'Optimizer che comprime e riverifica) costa circa 1000-2000 token una tantum per pattern. Ogni `recap.md` calcola un breakeven per pattern (dopo quanti usi il costo di costruzione si ripaga rispetto a chiamare sempre Expert) e una classificazione economica a tre vie — `ECONOMICALLY_POSITIVE` se conviene sui token, `ACCURACY_POSITIVE` se non conviene sui token ma ha risolto qualcosa che A o B non risolvevano, `NEGATIVE` altrimenti (che non significa "butta via la skill": con questi numeri piccoli può avere valore che le due metriche non catturano). Su experiment4, di dieci pattern coperti solo uno risulta economicamente positivo e uno accuracy-positivo — gli altri otto sono `NEGATIVE`, un dato scomodo che è più onesto mostrare che nascondere.

## Architettura

- **`domain/`** — funzioni Python di riferimento, pattern di bug KNOWN/VARIANT/NOVEL, generatore di task; `verifier.py` verifica ogni risposta oggettivamente via `pytest` in subprocess, mai un LLM-giudice, per evitare la circolarità del verificatore che è anche il verificato.
- **`agents/`** — `worker.py`, l'agente che risolve davvero il bug: costruisce il prompt (con o senza skill/soluzione allegata), chiama il modello, estrae il codice dalla risposta. Qui è finito anche un bug reale trovato in corsa: un cap di 1024 token tagliava a metà le risposte dei modelli con reasoning esteso, facendo sembrare un troncamento un fallimento di capacità — portato a 4096.
- **`librarian/`** — `librarian.py` instrada per sovrapposizione di tag (nessuna chiamata a embedding, routing a costo $0 per design); `optimizer.py` comprime skill costose e le riverifica prima di salvarle come nuova versione, senza mai sovrascrivere l'originale; `archive_duplicates.py` archivia (mai cancella) skill superate; `context_budget.py` impone un tetto reale sul contesto iniettato, basato sulla finestra del modello e sul conteggio vero dei token, mai stimato; `similarity.py` confronta coppie di skill per capire se la libreria sta accumulando duplicati sotto nomi diversi.
- **`cheater/`** — `solution_bank.py`, l'agente C: espone soluzioni pregresse indicizzate per pattern, con lo stesso split KNOWN/VARIANT/NOVEL del generatore di task ma calcolato indipendentemente (la coverage della Skill Library dipende da quali Book esistono, quella del Solution Bank è incondizionata — ogni pattern non escluso ha una soluzione nota, per costruzione del dataset).
- **`adapters/`** — interfaccia comune `ModelAdapter`, implementazioni per Claude, Gemini, OpenAI e un `MockAdapter` a costo zero per sviluppare senza chiamate reali. Provider e modello configurabili per ruolo (Expert/Small) indipendentemente, con rotazione automatica su più chiavi quando una va in quota.
- **`experiment/`** — `quest_runner.py` orchestra un singolo task end-to-end (retrieval, budget di contesto, prompt, chiamata al modello, verifica, log); `experiment_0.py` esegue le quattro configurazioni sullo stesso set di task, con checkpoint (rilanciabile dopo un'interruzione senza rifare ciò che è già stato fatto); `events.py` logga ogni fase in JSONL; `canary.py` i probe causali descritti sopra; `economics.py` calcola la classificazione economica per pattern (breakeven, ECONOMICALLY_POSITIVE/ACCURACY_POSITIVE/NEGATIVE); `recap.py`/`observer_table.py`/`knowledge_map.py`/`thesis_doc.py` generano i report leggibili da un run già completato, a costo zero (solo lettura locale).
- **`city/`** — `report.py` genera un HTML autocontenuto che visualizza l'esperimento come una città (NPC per configurazione, edifici = fasi reali della pipeline, timeline giorno-per-giorno); `epsilon_lab.py` fa lo stesso ma per l'indagine causale su `floating_point_equality` invece che per un run — ogni domanda/risposta nella pagina è una risposta reale trascritta a mano da una chiamata vera, non rigenerata al volo. Tutti i numeri, in entrambi, vengono dai dati reali, niente è inventato per riempire la visualizzazione.
- **`logs/`** — i log grezzi di ogni run (`log.jsonl`, `events.jsonl`) più i report generati (`recap.md`, `thesis.html`, `city.html`, i CSV) — le prove dietro ogni numero citato qui sopra, versionate in questo stesso repo.
- **`settings_wizard.py`** — configurazione interattiva da terminale (provider, modello, chiavi API), scrive in `.env` preservando commenti e ordine.

## Il ponte verso l'uso reale: Aria

L'architettura Book/Librarian/skill_generator/optimizer di questo progetto è stata portata — non collegata via codice, replicata deliberatamente come porting manuale — dentro **Aria**, un'app di organizzazione studio "stile Jarvis" per un utente reale con ADHD: [funny-starship-804504.netlify.app](https://funny-starship-804504.netlify.app) (sito provvisorio).

L'idea: l'uso quotidiano reale di Aria produce dati di comportamento genuini (feedback positivo/negativo, piani di studio seguiti fino in fondo) per la stessa domanda di ricerca, invece di richiedere solo quest sintetiche. È lo stesso ciclo CALL → OUTCOME → distillazione → promozione/retrocessione di una skill, reimplementato in TypeScript con le stesse regole di evidenza (soglia minima di usi, confronto con un baseline "senza skill", mai promossa sulla fiducia).

Una scelta deliberata: i due progetti restano tecnicamente isolati — Aria non importa nulla da qui, e questo repository non sa che Aria esiste. Il mirroring dell'architettura è manuale, guidato da commenti nel codice ("Mirror of...", "port of..."), non da una dipendenza condivisa. `tools/mirror_drift.py` (nella cartella padre di questo repo) confronta la data dell'ultimo commit git di ciascun file Python qui sotto con quella del suo specchio TypeScript in Aria, per segnalare quando un lato si muove senza che l'altro venga aggiornato.

## Uso

Richiede Python 3.11+ e le dipendenze in `requirements.txt` (nella cartella padre di questo repository).

```bash
# prima configurazione: provider, modello, chiavi API
python -m cognitive_rpg.settings_wizard

# esperimento completo su 4 configurazioni (A/B/F/C), modalità mock di default
python -m cognitive_rpg.experiment.experiment_0

# con provider reali (dopo aver configurato .env)
EXPERT_PROVIDER=claude SMALL_PROVIDER=gemini python -m cognitive_rpg.experiment.experiment_0

# rigenerare i report leggibili da un run già completato (gratis, nessuna chiamata)
python -m cognitive_rpg.experiment.recap experiment4
python -m cognitive_rpg.experiment.thesis_doc experiment4
```

Su Windows, gli script equivalenti sono in `tools/*.bat` (nella cartella padre di questo repository) — `tools\run_all.bat` esegue l'intera pipeline in un colpo (preflight, run, report, optimizer) su un `experiment_id` a scelta.

## Stato

Ricerca in corso, non un prodotto. Cinque run reali completi (`experiment0`-`experiment4`, log grezzi in `logs/`), non repliche indipendenti pulite — vedi i limiti dichiarati sopra. I numeri sono riportati con l'incertezza che meritano, non come conclusioni chiuse. La history dei commit (e dei recap dentro `logs/`) mostra bug trovati e corretti in diretta, non ripuliti a posteriori — comprese le volte in cui una conclusione precedente si è rivelata sbagliata o troppo generosa.
