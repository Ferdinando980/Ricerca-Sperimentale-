# Template per prompt di giudizio/classificazione (cognitive_rpg)

Checklist e template riutilizzabile per scrivere una NUOVA prompt di
giudizio/classificazione a schema fisso in questo progetto (non per
generazione aperta: riscritture di skill, soluzione di task — quelle
lasciano il ragionamento del modello dinamico, di proposito).

Distillato il 2026-09-18 da bug reali trovati dal vivo in `verification/detective.py`
più tre guide esterne di prompting condivise dall'utente (PM Proofreading,
un articolo Medium di Harinarayanan S G, un articolo LinkedIn di Hani Simo),
incrociate con quello che il progetto già faceva.

## Il template

```
Role: [ruolo stretto e specifico del giudice, es. "you are a skeptical second reviewer"]

Task:
[l'unica domanda/classificazione da fare — una sola cosa, non composita]

Context (delimitato, mai solo un'etichetta in prosa):
```
{contenuto reale su cui giudicare}
```

Constraints:
- Usa SOLO quanto scritto nel context, mai conoscenza generale del dominio
- [eventuali altri vincoli specifici del compito]

Do not:
- Non inferire, assumere, o indovinare
- Non [altro comportamento specifico da evitare, trovato con un bug reale se possibile]

Output (JSON, "reasoning" SEMPRE come primo campo):
{"reasoning": "una o due frasi, scritte per prime", "risposta": ..., "evidenza_verbatim": "..." | null}
```

## I 9 principi (con il bug reale che li ha motivati)

1. **Citazione verbatim richiesta, poi verificata meccanicamente — non basta chiederla.**
   Una citazione VERA non è la stessa cosa di una citazione PERTINENTE (bug
   reale: Gemma ha citato una riga di codice come "prova" di una convenzione
   di dominio che non menziona affatto). Servono due controlli separati:
   (a) la citazione è davvero una sottostringa del testo originale (verifica
   a costo zero), (b) un giudizio SEPARATO conferma che risponde davvero
   alla domanda specifica.

2. **Scomponi, ma mostra ogni elemento fratello insieme, mai in isolamento.**
   Generare N cose simili una alla volta, ognuna cieca alle altre, le fa
   collassare in quasi-duplicati (bug reale: due casi hanno ricevuto la
   stessa identica domanda perché nessuna delle due chiamate poteva vedere
   la formulazione dell'altra).

3. **Un caso "dimostra un'assenza" non si può rispondere con evidenza positiva — non provarci.**
   Un caso di fallback ("nessuno degli altri si applica") non ha un
   marcatore positivo da citare. Restituisci `null` invece di una domanda
   e risolvilo per ESCLUSIONE (tutti gli altri casi esclusi con un vero NO).

4. **Ogni elemento generato (una domanda, una regola) ha bisogno di un controllo meccanico di forma, separato dal contenuto.**
   Una domanda sì/no generata può essere mal formata (aperta, ibrida con
   "se nessuno, lascia vuoto") anche quando il ragionamento sottostante è
   corretto. Verifica la FORMA meccanicamente (inizia con un verbo
   ausiliare, finisce con "?", niente "if none") prima di provare a
   rispondere.

5. **Delimitatori strutturali attorno al contenuto incorporato, non solo un'etichetta in prosa.**
   "Task:\n\n{contenuto}" è un confine debole per un modello piccolo.
   Avvolgi il contenuto incorporato in un vero delimitatore (\`\`\` o <<< >>>).

6. **thinking_budget=0 per giudizi stretti, ma abbinato a un campo "reasoning" visibile e obbligatorio, scritto per primo.**
   Disattivare il ragionamento interno di un modello capace di ragionare
   risolve un vero bug di troncamento per classificazioni a schema fisso,
   ma un giudizio dato a zero deliberazione può restare superficiale. Non
   riattivare il ragionamento nascosto (reintroduce il rischio di
   troncamento) — richiedi un campo "reasoning" PRIMA della risposta nello
   schema JSON. Alza max_tokens di conseguenza.

7. **Il contributo del modello grande va nella scrittura del prompt, mai in una chiamata dal vivo a runtime, per qualsiasi meccanismo pensato per un modello piccolo.**
   Se un componente "di aiuto" ha bisogno del modello frontiera ad ogni
   esecuzione della pipeline del modello piccolo, è diventata di nascosto
   una dipendenza dal modello frontiera, vanificando lo scopo di un sistema
   a modello piccolo (correzione reale dell'utente: il Detective chiamava
   Expert dal vivo — corretto per usare solo Small, dato che il metodo
   generico stesso, scritto una volta nel prompt, è già "come lo farebbe
   il modello grande").

8. **Ogni controllo automatico di qualità/valore va reso ri-eseguibile, mai una fotografia una tantum.**
   Una lista di esclusione mantenuta a mano e calcolata una volta diventa
   obsoleta nel momento in cui la cosa che giudicava cambia (bug reale:
   `LOW_VALUE_RETRIEVAL_PATTERNS`, calcolata il 19/08, governava ancora due
   pattern riparati il 18/09 sulla base della loro evidenza VECCHIA).
   Qualsiasi lista statica derivata da una misura ha bisogno di una
   funzione gemella che la ricalcoli su dati freschi a comando.

9. **Testa liberamente le nuove tecniche; non promuoverle senza evidenza.**
   Una tecnica supportata dalla letteratura è una buona ragione per creare
   e testare una variante, ma non per sostituire automaticamente un prompt
   già validato. La promozione richiede evidenza empirica sul task reale:
   la correzione di un fallimento osservato, oppure un miglioramento
   riproducibile rispetto al baseline. Non serve che sia strettamente
   migliore su ogni caso testato — basta che non produca regressioni
   rilevanti, perché potrebbe comunque aiutare in casi non ancora visti.
   Non evitare una tecnica solo perché non abbiamo ancora un bug che la
   giustifichi; evitare invece di SOSTITUIRE ciò che è già validato senza
   aver prima verificato che la nuova versione non peggiori nulla.

## Dove si applica

Solo a prompt di GIUDIZIO/CLASSIFICAZIONE a schema fisso (una domanda
sì/no, un'estrazione meccanica, un confronto). Non alle chiamate
GENERATIVE (riscrittura di una skill, risoluzione di un task, generazione
di scenari) — lì il ragionamento dinamico è voluto, non un difetto da
correggere.
