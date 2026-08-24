# Cognitive RPG

Un ecosistema persistente di agenti LLM piccoli ed economici che imparano procedure, costruiscono memoria, si verificano a vicenda, scoprono da soli i propri limiti di competenza e trasferiscono conoscenza da una "generazione" di agenti alla successiva — con l'obiettivo di misurare quanta parte delle prestazioni di un modello frontier ("Expert") si possa recuperare con un ecosistema di modelli più piccoli, a quale costo, e come questo si comporti su scala.

Il vocabolario RPG (Quest, Book, NPC, XP, Level) non è estetica: è un layer intuitivo sopra meccanismi standard — routing/retrieval di skill (il "Librarian"), memoria procedurale in stile Voyager ("Books"), model routing cost-aware, verifica multi-agente, distillazione teacher→student tra generazioni.

## Domanda di ricerca

Quanto di una capacità "Expert" si recupera con una libreria di conoscenza condivisa e modelli piccoli, invece che con un modello grande da solo? E quella libreria aiuta davvero, o è solo overhead?

Non è retorico: i primi risultati reali (sotto) hanno già mostrato un caso in cui la libreria **non** ha misurabilmente aiutato — riportato così com'è, non nascosto.

## Architettura

- **`domain/`** — dominio di verifica: funzioni Python di riferimento, pattern di bug noti/varianti/inediti (`KNOWN`/`VARIANT`/`NOVEL`), task generator.
- **`librarian/`** — `librarian.py` instrada per sovrapposizione di tag (nessuna chiamata a embedding, costo di routing $0 per design); `optimizer.py` comprime skill costose e le riverifica prima di salvarle come nuova versione (non sovrascrive mai l'originale); `archive_duplicates.py` archivia (mai cancella) skill superate; `context_budget.py` impone un tetto reale sul contesto iniettato, basato sulla finestra del modello e sul token count vero, non stimato.
- **`adapters/`** — `ModelAdapter` come interfaccia comune; implementazioni per Claude, Gemini, OpenAI e un `MockAdapter` a costo zero per lo sviluppo senza chiamate reali. Provider e modello sono configurabili per ruolo (Expert/Small) indipendentemente, con rotazione automatica su più chiavi quando una va in quota.
- **`experiment/`** — motore che esegue le configurazioni sperimentali (Expert da solo, Small da solo, Small+Librarian, ...) sullo stesso set di task, logga ogni fase in JSONL (`events.py`) e verifica ogni risposta oggettivamente via `pytest` in subprocess (mai un LLM-giudice, per evitare la circolarità del "verificatore che è anche il verificato").
- **`city/`** — un report HTML autocontenuto (`report.py`), rigenerato dopo ogni run, che visualizza l'esperimento come una città: NPC per configurazione, una mappa statica con edifici = fasi reali della pipeline, una timeline giorno-per-giorno con grafici SVG disegnati a mano, un "path walker" per quest. Tutti i numeri vengono dai log reali — niente è inventato per riempire la visualizzazione.
- **`settings_wizard.py`** — configurazione interattiva da terminale (provider, modello, chiavi API), scrive in `.env` preservando commenti e ordine.

## Cosa è stato trovato finora (onestamente, non filtrato)

- **Un bug di troncamento mascherato da risultato di ricerca**: il primo run completo mostrava l'Expert al 50% contro il 95%+ di Small — sembrava "il modello piccolo batte il grande". In realtà ogni fallimento dell'Expert era a 1019-1020/1024 token di output: un modello con reasoning stava esaurendo un budget di token pensato per un modello senza reasoning, troncando la risposta a metà. Non un gap di capacità — un artefatto di configurazione.
- **Nessun beneficio misurabile dalla libreria di skill in questo primo run** (n=6-16 per cella, un solo run, nessuna ripetizione): Small+Librarian e Small da solo hanno ottenuto la stessa accuratezza; le celle con copertura completa della libreria sono andate leggermente *peggio* di quelle senza, pagando ~2.4x i token in input in cambio di nulla. Riportato come limite di questo run, non come conclusione definitiva.
- **Un bug di logica reale nel motore stesso**: `run_quest` costruiva i record di log ma non li salvava mai (mancava una `.append()`) — trovato eseguendo la pipeline end-to-end prima di dichiararla pronta, non per ispezione del codice.

## Il ponte verso l'uso reale: Aria

L'architettura Book/Librarian/skill_generator/optimizer di questo progetto è stata portata — non collegata via codice, replicata deliberatamente come porting manuale, vedi sotto — dentro **Aria**, un'app di organizzazione studio "stile Jarvis" per un utente reale con ADHD: [funny-starship-804504.netlify.app](https://funny-starship-804504.netlify.app) (sito provvisorio).

L'idea: l'uso quotidiano reale di Aria produce dati di comportamento genuini (feedback positivo/negativo, piani di studio seguiti fino in fondo) per la stessa domanda di ricerca, invece di richiedere solo quest sintetiche. È lo stesso ciclo CALL → OUTCOME → distillazione → promozione/retrocessione di una skill, reimplementato in TypeScript con le stesse regole di evidenza (soglia minima di usi, confronto con un baseline "senza skill", mai promossa sulla fiducia).

**Una scelta deliberata**: i due progetti restano tecnicamente isolati — Aria non importa nulla da qui, e questo repository non sa che Aria esiste. Il mirroring dell'architettura è manuale, guidato da commenti nel codice ("Mirror of...", "port of..."), non da una dipendenza condivisa. `tools/mirror_drift.py` (in questo repo) confronta la data dell'ultimo commit di ciascun file Python qui sotto con quella del suo specchio TypeScript in Aria, per segnalare quando un lato si muove senza che l'altro venga aggiornato — un problema che altrimenti dipenderebbe solo dal ricordarsene.

## Uso

Richiede Python 3.11+ e le dipendenze in `requirements.txt` (alla radice del repository che contiene questa cartella).

```bash
# prima configurazione: provider, modello, chiavi API
python -m cognitive_rpg.settings_wizard

# esperimento completo (modalità mock di default, nessuna chiamata reale)
python -m cognitive_rpg.experiment.experiment_0

# con provider reali (dopo aver configurato .env)
EXPERT_PROVIDER=claude SMALL_PROVIDER=gemini python -m cognitive_rpg.experiment.experiment_0
```

Su Windows, gli script equivalenti sono in `tools/*.bat` (nella cartella padre di questo repository).

## Stato

Ricerca in corso, non un prodotto. Un solo run reale completo di Experiment 0 finora (n piccolo, nessuna ripetizione) — i risultati sopra sono riportati con l'incertezza che meritano, non come conclusioni. Vedi i commit e la history per lo sviluppo incrementale (bug trovati e corretti in diretta, non nascosti a posteriori).
