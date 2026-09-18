# TODO — da riprendere nella prossima sessione

Lasciato in sospeso il 2026-09-18 su richiesta esplicita ("non fare i test,
lascia il resto da fare nel to-do") dopo il rollout sistematico del
template di prompt (vedi `template-instructions.md`). In ordine di priorità.

**Nuova direttiva (2026-09-18, punto 9 del template) da applicare qui:**
non serve dimostrare che le nuove formulazioni siano strettamente
migliori — la promozione (tenerle come versione live, fidarsene quanto
prima) richiede solo evidenza che NON producano regressioni rilevanti sui
casi reali già noti. Un pareggio è un risultato accettabile, non un
motivo per tornare indietro.

## 1. Verificare l'assenza di regressioni nelle prompt toccate dal rollout

Il rollout sistematico (campo `"reasoning"` scritto per primo, delimitatori
```) è stato applicato a:
- `verification/slot_identifier.py` (identify/extract/classify/match)
- `verification/method_trap.py` (extract_method)
- `verification/rule_generalization.py` (extract_rule, e il giudice a due
  righe GENERALIZES/DOES_NOT_GENERALIZE, con ordine delle righe invertito)
- `verification/stabilizer.py` (check_content_preserved,
  check_concreteness_preserved, survives_adversarial_check)
- `librarian/similarity.py` (classify_pair, ordine invertito)

Solo le prompt di `detective.py` sono state ri-testate su dati reali dopo
la modifica. Per le altre: ri-passarle sui casi reali già noti da questa
sessione (es. i 4 casi di identificazione slot/regola/metodo con storia
di instabilità) e confermare che il risultato non sia peggiorato — non
serve dimostrare un miglioramento, basta l'assenza di regressione.

## 2. Verificare check_content_preserved / check_concreteness_preserved contro i risultati storici di optimizer.py

Stessa logica del punto 1, applicata specificamente qui perché queste due
funzioni avevano una protezione esplicita più stretta ("tenute byte per
byte identiche per non destabilizzare la pipeline matura di
optimizer.py"), rimossa oggi su richiesta esplicita dell'utente. Ripassarle
sui casi storici di compressione già accettati/rifiutati da `optimizer.py`
e confermare che il verdetto non sia cambiato (non che sia migliorato).

## 3. Caratterizzazione statistica più solida del nuovo livello di floating_point_equality (v7)

Il quarto livello aggiunto (tolleranza derivata dalla precisione
implicita nei decimali) ha risolto il fallimento catastrofico di
`temperature_reached__variant` (era 0/8), ma con variabilità reale tra
run diversi (visto 4/5, poi 2/8, poi 5/5 in run successivi con lo stesso
identico setup). Serve un campione più ampio (N maggiore, magari più
ripetizioni aggregate) per sapere quanto è davvero affidabile, non solo
"molto meglio di prima".

## 4. Validazione statisticamente solida dell'effetto netto del Detective

Il Detective (ora corretto per usare solo Gemma, non Expert) funziona
meccanicamente bene, ma il suo effetto reale sull'accuratezza è stato
misurato solo su 2 task reali del catalogo (entrambi dello stesso
pattern, `floating_point_equality`) con N=8 ripetizioni — non abbastanza
per una conclusione solida. Serve più ampiezza prima di considerare di
collegarlo alla pipeline reale (`quest_runner.py` ha già l'opzione
`use_detective`/config "FD", pronta ma non attivata di default).

## 5. skill_conflict.py resta senza esposizione reale

0 task su 39 nel catalogo attuale generano mai un package con 2+ skill
insieme, quindi `skill_conflict.py` non può essere validato su scala con
il catalogo così com'è. Da decidere: costruire task che deliberatamente
richiamano 2 skill insieme, oppure accettare che resti validato solo sui
3 casi costruiti a mano.

## Nota per il porting su Aria

Il porting del sistema di verifica/riparazione su Aria resta condizionato
dal lato Python "pulito" (come già deciso). I punti 1-2 sopra sono ora il
vero blocco concreto, non più il gap di `floating_point_equality` (quello
è risolto, anche se non perfettamente).
