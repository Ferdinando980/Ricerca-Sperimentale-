# Recap -- experiment0
_Generato: 2026-08-19 22:06 UTC_

> ⚠️ **Difetto noto nel benchmark stesso (non nello skill/config in esame)** -- i risultati su questi task non significano quello che sembrano:
> - `floating_point_equality__temperature_reached__variant`: A/B's recorded PASS on this task does not mean they derived a correct tolerance: both write `any(r >= target for r in readings)` (no epsilon at all), which is wrong vs. the true correct_source (fails a reading just under target within tolerance -- verified 2026-08-19). bug_catalog.py's own test suite for this task never covers that case, so this has passed as correct in every run that includes it. See experiment/canary.py for the investigation.

> 🔬 **Meccanismo dello skill dimostrato causalmente (non solo osservato per correlazione)** -- da tenere presente leggendo i numeri di F su questo pattern:
> - `floating_point_equality`: F's epsilon on a no-hint task is NOT derived from the task's scale -- causally demonstrated (not just observed), 2026-08-19: manipulating the skill's tier-c fallback constant (1e-9 -> 2.5e-6 -> 7e-4) changed F's answer in lockstep, 12/12 runs across 2 unrelated no-hint tasks, while manipulating the unrelated tier-b (currency) constant changed nothing (0 leakage, 6/6 runs) -- and the reverse check also held: changing tier-c did not touch F's tier-b (currency) answer either, 3/3 runs. F correctly selects which tier applies, but performs no scale-sensitive reasoning within tier-c -- it substitutes that tier's literal constant verbatim. This is not 'reciting an example' in the loose sense (no semantic choice between multiple examples in the text) -- it is mechanical substitution of a single designated slot. See experiment/canary.py and the skill's own YAML changelog for the full ablation. Any accuracy number for F on this pattern's no-hint cases should be read with this in mind, not as evidence of context-sensitive reasoning.
REFINEMENT 2026-08-19 (staged probing + rule-substitution test): the finding above is about faithfully following THIS skill's literal-constant instruction, not a capability ceiling. Asking F, outside the skill text, to (1) name the property that should determine epsilon and (2) compute epsilon given that property's value handed to it directly -- F still answered the skill's literal 1e-9 both times, ignoring the given value entirely: it does not spontaneously invent a grounding strategy the skill didn't authorize. But rewriting tier-c ITSELF to require deriving epsilon from a stated magnitude (instead of a literal constant) made F actually perform the derivation -- correctly tracking magnitude across a ~1e7 range in two replications (200-300 units -> ~1e-4; 0.001-0.005 units -> exactly 5e-9), with one minor arithmetic slip in the first case (used 1e-4 instead of the correct 2.5e-4). Net picture: F reliably APPLIES whatever rule tier-c states -- literal substitution if told to substitute, genuine (if not perfectly precise) scale-derivation if told to derive -- but does not initiate derivation on its own when the operative rule is a literal constant. The bottleneck is instruction content, not model capability.
VALIDATION 2026-08-19 (delegated-arithmetic tier-c, not yet live): the one arithmetic slip in the refinement above (1e-4 instead of 2.5e-4) is a known LLM weakness -- silent token-by-token arithmetic, not unreliable scale-tracking -- so a tier-c wording was tested that asks F to extract the stated magnitude into a variable and write epsilon as an INTERPRETER-EVALUATED EXPRESSION (e.g. `epsilon = 1e-6 * typical_magnitude`) instead of hand-computing and hardcoding the final number. Validated on 7 runs across 5 tasks: the two original magnitude domains (200-300 units, 0.001-0.005 units) now produce a correct expression with no arithmetic to get wrong; a THIRD domain never used to write the rule (400-600 kg shipment weights) generalized correctly on first try (typical_magnitude=500, epsilon=1e-6*500); both genuinely no-magnitude tasks (sensor_readings_agree x2, same_destination x1) still correctly fell back to the untouched literal 1e-9 default, not a hallucinated expression -- selectivity between 'derive' and 'no basis to derive, use the safe default' held 5/5; and the currency tier-b task was unaffected (still 0.01, 1/1). Not yet adopted as the live procedure_text -- this is a validated research result, deployment is a separate, deliberate decision (consistent with two failed rewrite attempts earlier in this same investigation). Also note the cost tradeoff this rule trades into: reasoning through a derivation costs more tokens per call than blind literal substitution, moving F's per-task cost toward (not to) Expert's -- see the token-accounting figures elsewhere in this report.
CORRECTION 2026-08-19 (the 'third domain' claim above, overclaimed): 'F generalizes to shipment_weight_match' was graded against 1e-6 * stated_magnitude -- the same formula the same investigator wrote into the rule, same session. That checks rule-application fidelity, not whether 1e-6*magnitude is an objectively correct real-world tolerance. Applying the canary check that already invalidated 3 of 4 CATEGORY_C domains: does unaided Expert independently converge near the same answer? No -- 3/3 reps, Expert produces `math.isclose(weight_a, weight_b)` (rel_tol=1e-9 default, essentially machine-precision equality), nothing near 1e-6*magnitude, no real engagement with the stated range. shipment_weight_match does NOT pass canary validation -- it joins the underdetermined bucket, not the validated-answer bucket. The same caveat applies retroactively to the two original magnitude domains (instrument, sensor) that built the rule -- never independently canary-checked either. What survives: F reliably applies an explicit formula to unseen data (mechanically verifiable, Category-A-like). What does not survive: any claim that 1e-6*magnitude is a validated convention -- it is as author-arbitrary as any other constant flagged in this investigation.
RESOLUTION 2026-08-19 (a genuine second CATEGORY_C domain, found and confirmed with F, the sharpest positive result in this chapter): unlike shipment_weight_match, significant-figures-implied precision (low decimal-asymmetry, small nonzero numeric distance -- e.g. 13.7 vs 13.68) WAS independently validated -- unaided Expert converges on `round(x,1)==round(y,1)` 11/12 times across 3 deliberately non-textbook pairs (ruling out memorization of a stock physics example: novel pairs converged MORE consistently than the original 7.2/7.21, 92% vs 75% -- the opposite of what memorization predicts). F was then tested with two decimal structures at once (1v2 decimals -> expected eps 0.05; 2v3 decimals -> expected eps 0.005) crossed with skill condition: baseline (sig-figs not in tier-b) fell to tier-c's 1e-9 (3/3) or misfired to currency's 0.01 by loose semantic association with 'dial' (2/3 on the 2v3 task, a THIRD failure type this chapter hadn't catalogued -- generalization via surface word similarity, not blind substitution and not correct derivation) -- neither correct; a research variant adding sig-figs as a second tier-b convention got 6/6 correct, AND -- decisively -- produced DIFFERENT epsilon values per task (0.05 vs 0.005), each correctly scaled to that task's own decimal structure, with the reasoning written out. A single memorized-constant substitution mechanism cannot produce two different, each-independently-correct numbers -- this is the first clean resolution of recitation-vs-derivation in this chapter on a domain confirmed not to be a lucky-scale coincidence (unlike currency's 0.01, which was never tested against a case requiring a different magnitude). Not adopted as live procedure_text -- same deliberate-deployment-decision principle as the delegated-arithmetic result above. FOLLOW-UP (same day): the 2v3-decimal structure used in the F test had never itself been independently checked on A (every prior A-validation used 1v2 decimals) -- lower risk than shipment_weight_match since the formula (0.5*10^-d) was already validated, extending it to a new d is not a fresh guess -- but closed anyway: 4/4 exact on a fresh 2v3 pair, independent of the F test's own task. See experiment/canary.py FOLLOW-UPS 1-5 for the full elimination of confounds that preceded this.

> ⚠️ **Provider/modello misto dentro questo run** -- questi config hanno usato piu' di una combinazione provider/modello (probabile switch a meta' run, es. AI Studio -> Vertex AI): confronti tra config diversi restano validi, ma se citi questi numeri in modo formale tienilo presente.
- **A**: gemini/gemini-3.6-flash, gemini_vertex/gemini-3.7-flash
- **B**: gemini/gemini-3.5-flash-lite, gemini_vertex/gemini-3.1-flash-lite
- **F**: gemini/gemini-3.5-flash-lite, gemini_vertex/gemini-3.1-flash-lite
- **C**: gemini/gemini-3.1-flash-lite, gemini_vertex/gemini-3.1-flash-lite

> 💸 **Analisi controfattuale costo di retrieval** (F vs B stesso task, stesso experiment_id -- zero chiamate nuove): su 20 quest con skill iniettata, **16 (80.0%)** hanno visto B passare comunque senza alcun aiuto -- overhead di token pagato senza beneficio misurato su quella quest specifica (4580 token totali). 3 quest mostrano un beneficio reale (B falliva, F ha passato), 1 mostrano lo skill peggiorare l'esito (spesso il sintomo di un difetto nel benchmark, non dello skill -- controlla sopra). Pattern con almeno un beneficio misurato in questo run: floating_point_equality, wrong_string_case_comparison.

## 1. Stato di avanzamento
- 104/156 quest completate (39 task x 4 config: A/B/F)
- **52 quest ancora da fare:**
  - **A** (A -- Expert da solo): 13 mancanti
    - wrong_accumulator_init__sum_scores_by_player__variant2 [VARIANT]
    - wrong_return_in_loop__count_word_frequency__variant3 [NOVEL]
    - wrong_comparison_operator__binary_search__variant2 [VARIANT]
    - integer_division_truncation__sum_digits__variant2 [VARIANT]
    - inverted_boolean_logic__is_valid_username__variant2 [VARIANT]
    - off_by_one__run_length_encode__variant2 [VARIANT]
    - index_out_of_range_boundary__merge_intervals__variant2 [VARIANT]
    - wrong_comparison_operator__is_valid_password__variant2 [VARIANT]
    - wrong_return_in_loop__sum_scores_by_player__variant3 [NOVEL]
    - off_by_one__merge_intervals__variant2 [VARIANT]
    - wrong_string_case_comparison__count_vowels__variant2 [VARIANT]
    - wrong_accumulator_init__count_word_frequency__variant2 [VARIANT]
    - wrong_string_case_comparison__is_palindrome__variant2 [VARIANT]
  - **B** (B -- Small da solo): 13 mancanti
    - wrong_accumulator_init__sum_scores_by_player__variant2 [VARIANT]
    - wrong_return_in_loop__count_word_frequency__variant3 [NOVEL]
    - wrong_comparison_operator__binary_search__variant2 [VARIANT]
    - integer_division_truncation__sum_digits__variant2 [VARIANT]
    - inverted_boolean_logic__is_valid_username__variant2 [VARIANT]
    - off_by_one__run_length_encode__variant2 [VARIANT]
    - index_out_of_range_boundary__merge_intervals__variant2 [VARIANT]
    - wrong_comparison_operator__is_valid_password__variant2 [VARIANT]
    - wrong_return_in_loop__sum_scores_by_player__variant3 [NOVEL]
    - off_by_one__merge_intervals__variant2 [VARIANT]
    - wrong_string_case_comparison__count_vowels__variant2 [VARIANT]
    - wrong_accumulator_init__count_word_frequency__variant2 [VARIANT]
    - wrong_string_case_comparison__is_palindrome__variant2 [VARIANT]
  - **F** (F -- Small + Librarian): 13 mancanti
    - wrong_accumulator_init__sum_scores_by_player__variant2 [VARIANT]
    - wrong_return_in_loop__count_word_frequency__variant3 [NOVEL]
    - wrong_comparison_operator__binary_search__variant2 [VARIANT]
    - integer_division_truncation__sum_digits__variant2 [VARIANT]
    - inverted_boolean_logic__is_valid_username__variant2 [VARIANT]
    - off_by_one__run_length_encode__variant2 [VARIANT]
    - index_out_of_range_boundary__merge_intervals__variant2 [VARIANT]
    - wrong_comparison_operator__is_valid_password__variant2 [VARIANT]
    - wrong_return_in_loop__sum_scores_by_player__variant3 [NOVEL]
    - off_by_one__merge_intervals__variant2 [VARIANT]
    - wrong_string_case_comparison__count_vowels__variant2 [VARIANT]
    - wrong_accumulator_init__count_word_frequency__variant2 [VARIANT]
    - wrong_string_case_comparison__is_palindrome__variant2 [VARIANT]
  - **C** (C -- Small + Cheater (soluzione pregressa)): 13 mancanti
    - wrong_accumulator_init__sum_scores_by_player__variant2 [VARIANT]
    - wrong_return_in_loop__count_word_frequency__variant3 [NOVEL]
    - wrong_comparison_operator__binary_search__variant2 [VARIANT]
    - integer_division_truncation__sum_digits__variant2 [VARIANT]
    - inverted_boolean_logic__is_valid_username__variant2 [VARIANT]
    - off_by_one__run_length_encode__variant2 [VARIANT]
    - index_out_of_range_boundary__merge_intervals__variant2 [VARIANT]
    - wrong_comparison_operator__is_valid_password__variant2 [VARIANT]
    - wrong_return_in_loop__sum_scores_by_player__variant3 [NOVEL]
    - off_by_one__merge_intervals__variant2 [VARIANT]
    - wrong_string_case_comparison__count_vowels__variant2 [VARIANT]
    - wrong_accumulator_init__count_word_frequency__variant2 [VARIANT]
    - wrong_string_case_comparison__is_palindrome__variant2 [VARIANT]
  (rilancia `tools\start.bat` per far avanzare -- riprende da solo dal checkpoint)

## 2. Confronto A / B / F
A = Expert da solo, B = Small da solo, F = Small + skill dalla Libreria.

| config | split | n | accuracy | costo tot | latenza media (ms) |
|---|---|---|---|---|---|
| A | KNOWN | 10 | 100.0% | $0.0000 | 12676 |
| A | NOVEL | 6 | 100.0% | $0.0000 | 15345 |
| A | VARIANT | 10 | 100.0% | $0.0000 | 12634 |
| B | KNOWN | 10 | 80.0% | $0.0000 | 738 |
| B | NOVEL | 6 | 100.0% | $0.0000 | 698 |
| B | VARIANT | 10 | 90.0% | $0.0000 | 728 |
| C | KNOWN | 10 | 100.0% | $0.0000 | 1082 |
| C | NOVEL | 6 | 83.3% | $0.0000 | 1147 |
| C | VARIANT | 10 | 90.0% | $0.0000 | 852 |
| F | KNOWN | 10 | 100.0% | $0.0000 | 827 |
| F | NOVEL | 6 | 100.0% | $0.0000 | 690 |
| F | VARIANT | 10 | 90.0% | $0.0000 | 718 |

**Totali per config:**
- A -- Expert da solo: accuracy 100.0%, costo totale $0.0000, latenza media 13276ms, n=26
- B -- Small da solo: accuracy 88.5%, costo totale $0.0000, latenza media 725ms, n=26
- F -- Small + Librarian: accuracy 96.2%, costo totale $0.0000, latenza media 753ms, n=26
- C -- Small + Cheater (soluzione pregressa): accuracy 92.3%, costo totale $0.0000, latenza media 1008ms, n=26
- B vs A (Small senza aiuto vs Expert): -11.5% accuracy
- F vs B (effetto della Libreria sul modello Small): +7.7% accuracy
- F vs A (quanto F si avvicina all'Expert): -3.8% accuracy
- C vs B (l'accesso a una soluzione pregressa aiuta rispetto a niente?): +3.8% accuracy
- C vs F (soluzione specifica vs skill generalizzata -- la domanda centrale del Cheater Agent): -3.8% accuracy

## 3. Retrieval vs Architecture (coverage NONE/PARTIAL/FULL)
Separa "il meccanismo di retrieval esiste" da "il retrieval ha trovato qualcosa di pertinente" -- per F (Skill Library) e C (Solution Bank), ogni quest ha gia' un `coverage` salvato (NONE=niente trovato, PARTIAL=match parziale/imperfetto, FULL=match esatto/completo). Se **F-NONE ~= B** e **F-FULL > B**, e' il retrieval a spostare l'accuracy, non la sola presenza del meccanismo.

**F -- Small + Librarian:**
| coverage | n | accuracy |
|---|---|---|
| NONE | 6 | 100.0% |
| FULL | 20 | 95.0% |
- Δ Retrieval (FULL − NONE, dentro F stesso): -5.0%
- Δ Architecture (F-FULL − B): +6.5%

**C -- Small + Cheater (soluzione pregressa):**
| coverage | n | accuracy |
|---|---|---|
| NONE | 6 | 83.3% |
| PARTIAL | 10 | 90.0% |
| FULL | 10 | 100.0% |
- Δ Retrieval (FULL − NONE, dentro C stesso): +16.7%
- Δ Architecture (C-FULL − B): +11.5%

Il dettaglio per split (KNOWN/VARIANT/NOVEL) di ogni config e' gia' nella tabella della sezione 2 sopra -- known_example ~ FULL/EXACT, variant ~ PARTIAL/SEEN per definizione di come route()/lookup() funzionano, quindi le due viste si leggono insieme.

- ⚠️ **Δ Retrieval di segno opposto tra F (-5.0%, n=6+20) e C (+16.7%, n=6+10)** -- con questi n puo' essere rumore, ma se si ripete su run future vale la pena chiedersi se il Librarian sta recuperando skill anche quando non aiutano (over-triggering) piu' spesso del Cheater.

## 4. Token accounting
Token reali per config -- separato da costo_usd perche' quello e' $0 finche' GEMINI_INPUT_PER_MTOK/OUTPUT_PER_MTOK non sono impostati in .env. "reasoning" sono i token di pensiero di Gemini (fatturati, ma mai inclusi in "output").

| config | n | input | output | reasoning | totale | tok/task | tok/successo | accuracy |
|---|---|---|---|---|---|---|---|---|
| A | 26 | 3968 | 1765 | 25000 | 30733 | 1182 | 1182 | 100.0% |
| B | 26 | 3968 | 1815 | 0 | 5783 | 222 | 251 | 88.5% |
| F | 26 | 9934 | 1821 | 0 | 11755 | 452 | 470 | 96.2% |
| C | 26 | 6060 | 1803 | 0 | 7863 | 302 | 328 | 92.3% |
- "tok/successo" = token totali / task risolti (non /n) -- un config con qualche fallimento sta comunque spendendo quei token senza ottenere un risultato utile, quindi e' un confronto piu' onesto di tok/task quando le accuracy non sono identiche.

- Overhead della Libreria (F vs B, stesso task): +229 token di input in media (min 0, max 366) -- il costo di *usare* uno skill gia' pronto.
- Costo dell'Optimizer in questa run (costo di *costruire* la conoscenza, non di usarla): 54 compressioni + 108 riverifiche = 66735 token totali (1236/skill in media). E' un costo una tantum per skill, non per uso -- si ammortizza sulle usi future, a differenza dell'overhead della Libreria sopra che si paga ad ogni retrieval.

## 5. Ammortamento delle skill (costruzione vs uso)
Per pattern di bug: costo una tantum per costruire/comprimere quella skill (Optimizer, qualunque tentativo, accettato o no) contro il risparmio medio per uso di F rispetto ad A sui task che quella skill copre. "breakeven" = dopo quanti usi il costo di costruzione si ripaga rispetto a chiamare sempre Expert. **Attenzione**: 2 task per pattern in questa run -- direzione indicativa, non un numero da citare come definitivo.

| pattern | costo costruzione | n task | A tok/task | F tok/task | risparmio/uso | breakeven |
|---|---|---|---|---|---|---|
| `floating_point_equality` | 36945 | 2 | 2709 | 478 | +2231 | 16.6 usi |
| `index_out_of_range_boundary` | 36068 | 2 | 1003 | 600 | +402 | 89.6 usi |
| `integer_division_truncation` | 28424 | 2 | 884 | 540 | +344 | 82.7 usi |
| `inverted_boolean_logic` | 20746 | 2 | 1988 | 513 | +1474 | 14.1 usi |
| `key_error_missing_dict_check` | 7353 | 2 | 358 | 538 | -180 | mai (F costa piu' di A qui) |
| `mutable_default_argument` | 27080 | 2 | 1510 | 508 | +1002 | 27.0 usi |
| `off_by_one` | 26137 | 2 | 712 | 466 | +246 | 106.5 usi |
| `wrong_accumulator_init` | 26219 | 2 | 658 | 502 | +156 | 168.6 usi |
| `wrong_comparison_operator` | 27935 | 2 | 1374 | 524 | +850 | 32.9 usi |
| `wrong_string_case_comparison` | 6985 | 2 | 809 | 536 | +273 | 25.6 usi |

## 6. Quest fallite
- **B** [KNOWN] `floating_point_equality__average_matches_target__known_example`
- **B** [KNOWN] `wrong_string_case_comparison__find_matching_tag__known_example`
- **B** [VARIANT] `wrong_string_case_comparison__is_valid_username__variant`
- **C** [VARIANT] `floating_point_equality__temperature_reached__variant`
- **C** [NOVEL] `variable_shadowing__reverse_words__novel_b`
- **F** [VARIANT] `floating_point_equality__temperature_reached__variant`

**Pattern di bug con fallimenti in piu' di un config:**
- `floating_point_equality`: B su floating_point_equality__average_matches_target__known_example, F su floating_point_equality__temperature_reached__variant, C su floating_point_equality__temperature_reached__variant -- **task diversi della stessa famiglia di bug** falliscono su config diversi. Da controllare quest per quest in `observer_table.csv` (colonna `retrieved_tokens`) se lo skill recuperato e' lo stesso e se l'ha aiutato o confuso.

## 7. Uso degli skill (Librarian)
| skill | usi | token medi | quest passate su quest usate |
|---|---|---|---|
| `book_floating_point_equality` | 2 | 327 | 1/2 |
| `book_index_out_of_range_boundary` | 2 | 296 | 2/2 |
| `book_integer_division_truncation` | 2 | 292 | 2/2 |
| `book_inverted_boolean_logic` | 2 | 314 | 2/2 |
| `book_key_error_missing_dict_check` | 2 | 360 | 2/2 |
| `book_mutable_default_argument` | 2 | 291 | 2/2 |
| `book_off_by_one` | 1 | 306 | 1/1 |
| `book_off_by_one_v2` | 1 | 134 | 1/1 |
| `book_wrong_accumulator_init` | 2 | 309 | 2/2 |
| `book_wrong_comparison_operator` | 1 | 288 | 1/1 |
| `book_wrong_comparison_operator_v2` | 1 | 128 | 1/1 |
| `book_wrong_string_case_comparison` | 2 | 366 | 2/2 |
| `solution_average_matches_target` | 2 | 74 | 1/2 |
| `solution_binary_search` | 2 | 131 | 2/2 |
| `solution_count_vowels` | 2 | 90 | 2/2 |
| `solution_count_word_frequency` | 2 | 84 | 2/2 |
| `solution_dedupe_preserve_order` | 2 | 97 | 2/2 |
| `solution_find_matching_tag` | 2 | 88 | 2/2 |
| `solution_is_leap_year` | 2 | 93 | 2/2 |
| `solution_merge_intervals` | 2 | 144 | 2/2 |
| `solution_rolling_average` | 2 | 98 | 2/2 |
| `solution_run_length_encode` | 2 | 155 | 2/2 |

## 8. Optimizer (compressione skill)
- `book_mutable_default_argument`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_index_out_of_range_boundary`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_inverted_boolean_logic`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_wrong_accumulator_init`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_integer_division_truncation`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_floating_point_equality`: ACCETTATA (compresso 1 passate vs originale 1 passate, stesso set di task riverificati)
- `book_mutable_default_argument`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_index_out_of_range_boundary`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_inverted_boolean_logic`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_wrong_accumulator_init`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_integer_division_truncation`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_floating_point_equality`: ACCETTATA (compresso None passate vs originale 1 passate, stesso set di task riverificati)
- `book_wrong_string_case_comparison`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_key_error_missing_dict_check`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)

## 9. Mappa delle sezioni
Vista condensata -- il dettaglio (crescita della libreria nel tempo, file su disco vs skill "attuali") e' in `knowledge_map.md` (`tools\knowledge_map.bat`).

| sezione | pattern | coverage | book | usi | costo costruzione |
|---|---|---|---|---|---|
| `boundary_conditions` | off_by_one, wrong_comparison_operator, index_out_of_range_boundary, wrong_return_in_loop | PARTIALLY_COVERED | 3 | 6 | 90140 |
| `numerical_computing` | floating_point_equality, integer_division_truncation | COVERED | 2 | 4 | 65369 |
| `loop_state` | wrong_accumulator_init | COVERED | 1 | 2 | 26219 |
| `language_semantics` | mutable_default_argument, variable_shadowing | PARTIALLY_COVERED | 1 | 2 | 27080 |
| `boolean_logic` | inverted_boolean_logic | COVERED | 1 | 2 | 20746 |
| `data_ordering` | incorrect_sort_key_or_order | EMPTY | 0 | 0 | 0 |
| `data_structures` | key_error_missing_dict_check | COVERED | 1 | 2 | 7353 |
| `string_processing` | wrong_string_case_comparison | COVERED | 1 | 2 | 6985 |

## Nota metodologica
Ogni cella (task, config) ha una sola run. Un singolo fallimento non basta per dire se e' un problema sistematico dello skill o una variazione casuale del modello -- serve ripetere lo stesso task piu' volte per distinguerli.
Tutti i costi risultano $0.00: probabile prezzo non configurato per il provider in uso (vedi `GEMINI_INPUT_PER_MTOK`/`GEMINI_OUTPUT_PER_MTOK` in `.env`), non un run gratuito per davvero -- non affidarti a questo numero per ora.
