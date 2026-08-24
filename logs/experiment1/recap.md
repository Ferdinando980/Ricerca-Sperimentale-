# Recap -- experiment1
_Generato: 2026-08-18 14:33 UTC_

## 1. Stato di avanzamento
- 63/104 quest completate (26 task x 4 config: A/B/F)
- **41 quest ancora da fare:**
  - **A** (A -- Expert da solo): 5 mancanti
    - wrong_string_case_comparison__is_valid_username__variant [VARIANT]
    - key_error_missing_dict_check__count_word_frequency__known_example [KNOWN]
    - key_error_missing_dict_check__sum_scores_by_player__variant [VARIANT]
    - wrong_string_case_comparison__find_matching_tag__known_example [KNOWN]
    - wrong_return_in_loop__dedupe_preserve_order__novel_a [NOVEL]
  - **B** (B -- Small da solo): 5 mancanti
    - wrong_string_case_comparison__is_valid_username__variant [VARIANT]
    - key_error_missing_dict_check__count_word_frequency__known_example [KNOWN]
    - key_error_missing_dict_check__sum_scores_by_player__variant [VARIANT]
    - wrong_string_case_comparison__find_matching_tag__known_example [KNOWN]
    - wrong_return_in_loop__dedupe_preserve_order__novel_a [NOVEL]
  - **F** (F -- Small + Librarian): 5 mancanti
    - wrong_string_case_comparison__is_valid_username__variant [VARIANT]
    - key_error_missing_dict_check__count_word_frequency__known_example [KNOWN]
    - key_error_missing_dict_check__sum_scores_by_player__variant [VARIANT]
    - wrong_string_case_comparison__find_matching_tag__known_example [KNOWN]
    - wrong_return_in_loop__dedupe_preserve_order__novel_a [NOVEL]
  - **C** (C -- Small + Cheater (soluzione pregressa)): 26 mancanti
    - variable_shadowing__rolling_average__novel_a [NOVEL]
    - wrong_accumulator_init__count_vowels__known_example [KNOWN]
    - inverted_boolean_logic__is_valid_password__variant [VARIANT]
    - wrong_string_case_comparison__is_valid_username__variant [VARIANT]
    - incorrect_sort_key_or_order__dedupe_preserve_order__novel_b [NOVEL]
    - integer_division_truncation__rolling_average__known_example [KNOWN]
    - mutable_default_argument__flatten_list__variant [VARIANT]
    - floating_point_equality__average_matches_target__known_example [KNOWN]
    - index_out_of_range_boundary__binary_search__variant [VARIANT]
    - key_error_missing_dict_check__count_word_frequency__known_example [KNOWN]
    - floating_point_equality__temperature_reached__variant [VARIANT]
    - incorrect_sort_key_or_order__merge_intervals__novel_a [NOVEL]
    - off_by_one__rolling_average__variant [VARIANT]
    - index_out_of_range_boundary__run_length_encode__known_example [KNOWN]
    - key_error_missing_dict_check__sum_scores_by_player__variant [VARIANT]
    - wrong_accumulator_init__reverse_words__variant [VARIANT]
    - wrong_comparison_operator__merge_intervals__known_example [KNOWN]
    - variable_shadowing__reverse_words__novel_b [NOVEL]
    - wrong_string_case_comparison__find_matching_tag__known_example [KNOWN]
    - mutable_default_argument__dedupe_preserve_order__known_example [KNOWN]
    - wrong_return_in_loop__flatten_list__novel_b [NOVEL]
    - integer_division_truncation__binary_search__variant [VARIANT]
    - inverted_boolean_logic__is_leap_year__known_example [KNOWN]
    - off_by_one__binary_search__known_example [KNOWN]
    - wrong_comparison_operator__run_length_encode__variant [VARIANT]
    - wrong_return_in_loop__dedupe_preserve_order__novel_a [NOVEL]
  (rilancia `tools\start.bat` per far avanzare -- riprende da solo dal checkpoint)

## 2. Confronto A / B / F
A = Expert da solo, B = Small da solo, F = Small + skill dalla Libreria.

| config | split | n | accuracy | costo tot | latenza media (ms) |
|---|---|---|---|---|---|
| A | KNOWN | 8 | 87.5% | $0.0000 | 5874 |
| A | NOVEL | 5 | 100.0% | $0.0000 | 5965 |
| A | VARIANT | 8 | 100.0% | $0.0000 | 7004 |
| B | KNOWN | 8 | 87.5% | $0.0000 | 1805 |
| B | NOVEL | 5 | 100.0% | $0.0000 | 715 |
| B | VARIANT | 8 | 100.0% | $0.0000 | 1546 |
| F | KNOWN | 8 | 100.0% | $0.0000 | 1354 |
| F | NOVEL | 5 | 100.0% | $0.0000 | 3641 |
| F | VARIANT | 8 | 100.0% | $0.0000 | 1389 |

**Totali per config:**
- A -- Expert da solo: accuracy 95.2%, costo totale $0.0000, latenza media 6326ms, n=21
- B -- Small da solo: accuracy 95.2%, costo totale $0.0000, latenza media 1447ms, n=21
- F -- Small + Librarian: accuracy 100.0%, costo totale $0.0000, latenza media 1912ms, n=21
- B vs A (Small senza aiuto vs Expert): +0.0% accuracy
- F vs B (effetto della Libreria sul modello Small): +4.8% accuracy
- F vs A (quanto F si avvicina all'Expert): +4.8% accuracy

## 3. Token accounting
Token reali per config -- separato da costo_usd perche' quello e' $0 finche' GEMINI_INPUT_PER_MTOK/OUTPUT_PER_MTOK non sono impostati in .env. "reasoning" sono i token di pensiero di Gemini (fatturati, ma mai inclusi in "output").

| config | n | input | output | reasoning | totale | tok/task | tok/successo | accuracy |
|---|---|---|---|---|---|---|---|---|
| A | 21 | 3330 | 1538 | 28146 | 33014 | 1572 | 1651 | 95.2% |
| B | 21 | 3330 | 1507 | 0 | 4837 | 230 | 242 | 95.2% |
| F | 21 | 10526 | 1580 | 0 | 12106 | 576 | 576 | 100.0% |
- "tok/successo" = token totali / task risolti (non /n) -- un config con qualche fallimento sta comunque spendendo quei token senza ottenere un risultato utile, quindi e' un confronto piu' onesto di tok/task quando le accuracy non sono identiche.

- Overhead della Libreria (F vs B, stesso task): +343 token di input in media (min 0, max 908) -- il costo di *usare* uno skill gia' pronto.
- Costo dell'Optimizer in questa run (costo di *costruire* la conoscenza, non di usarla): 98 compressioni + 196 riverifiche = 108576 token totali (1108/skill in media). E' un costo una tantum per skill, non per uso -- si ammortizza sulle usi future, a differenza dell'overhead della Libreria sopra che si paga ad ogni retrieval.

## 4. Ammortamento delle skill (costruzione vs uso)
Per pattern di bug: costo una tantum per costruire/comprimere quella skill (Optimizer, qualunque tentativo, accettato o no) contro il risparmio medio per uso di F rispetto ad A sui task che quella skill copre. "breakeven" = dopo quanti usi il costo di costruzione si ripaga rispetto a chiamare sempre Expert. **Attenzione**: 2 task per pattern in questa run -- direzione indicativa, non un numero da citare come definitivo.

| pattern | costo costruzione | n task | A tok/task | F tok/task | risparmio/uso | breakeven |
|---|---|---|---|---|---|---|
| `floating_point_equality` | 18572 | 2 | 2662 | 1062 | +1600 | 11.6 usi |
| `index_out_of_range_boundary` | 16069 | 2 | 1404 | 720 | +684 | 23.5 usi |
| `integer_division_truncation` | 14794 | 2 | 2430 | 664 | +1766 | 8.4 usi |
| `inverted_boolean_logic` | 13285 | 2 | 548 | 625 | -78 | mai (F costa piu' di A qui) |
| `mutable_default_argument` | 14259 | 2 | 1419 | 632 | +787 | 18.1 usi |
| `off_by_one` | 8689 | 2 | 1800 | 552 | +1248 | 7.0 usi |
| `wrong_accumulator_init` | 13616 | 2 | 872 | 619 | +253 | 53.8 usi |
| `wrong_comparison_operator` | 9292 | 2 | 1546 | 605 | +942 | 9.9 usi |

## 5. Quest fallite
- **A** [KNOWN] `floating_point_equality__average_matches_target__known_example`
- **B** [KNOWN] `floating_point_equality__average_matches_target__known_example`

**Pattern di bug con fallimenti in piu' di un config:**
- `floating_point_equality`: A su floating_point_equality__average_matches_target__known_example, B su floating_point_equality__average_matches_target__known_example -- stesso task, probabilmente e' il task in se' ad essere difficile per tutti (non e' una domanda sulla Libreria).

## 6. Uso degli skill (Librarian)
| skill | usi | token medi | quest passate su quest usate |
|---|---|---|---|
| `book_floating_point_equality` | 2 | 908 | 2/2 |
| `book_floating_point_equality_v2` | 2 | 908 | 2/2 |
| `book_index_out_of_range_boundary` | 2 | 415 | 2/2 |
| `book_index_out_of_range_boundary_v2` | 2 | 415 | 2/2 |
| `book_integer_division_truncation` | 2 | 416 | 2/2 |
| `book_integer_division_truncation_v2` | 2 | 416 | 2/2 |
| `book_inverted_boolean_logic` | 2 | 426 | 2/2 |
| `book_inverted_boolean_logic_v2` | 2 | 426 | 2/2 |
| `book_mutable_default_argument` | 2 | 413 | 2/2 |
| `book_mutable_default_argument_v2` | 2 | 413 | 2/2 |
| `book_off_by_one` | 2 | 306 | 2/2 |
| `book_wrong_accumulator_init` | 2 | 426 | 2/2 |
| `book_wrong_accumulator_init_v2` | 2 | 426 | 2/2 |
| `book_wrong_comparison_operator` | 2 | 288 | 2/2 |

## 7. Optimizer (compressione skill)
- `book_mutable_default_argument_v2`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_mutable_default_argument`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_wrong_comparison_operator`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_index_out_of_range_boundary_v2`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_index_out_of_range_boundary`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_inverted_boolean_logic_v2`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_inverted_boolean_logic`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_wrong_accumulator_init_v2`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_wrong_accumulator_init`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_integer_division_truncation_v2`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_integer_division_truncation`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_floating_point_equality_v2`: RESPINTA (compresso 1 passate vs originale 2 passate, stesso set di task riverificati)
- `book_floating_point_equality`: RESPINTA (compresso 1 passate vs originale 2 passate, stesso set di task riverificati)
- `book_off_by_one`: ACCETTATA (compresso 2 passate vs originale 2 passate, stesso set di task riverificati)
- `book_mutable_default_argument_v2`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_mutable_default_argument`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_wrong_comparison_operator`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_index_out_of_range_boundary_v2`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_index_out_of_range_boundary`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_inverted_boolean_logic_v2`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_inverted_boolean_logic`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_wrong_accumulator_init_v2`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_wrong_accumulator_init`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_integer_division_truncation_v2`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_integer_division_truncation`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_floating_point_equality_v2`: RESPINTA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_floating_point_equality`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)
- `book_off_by_one`: ACCETTATA (compresso None passate vs originale 2 passate, stesso set di task riverificati)

## 8. Mappa delle sezioni
Vista condensata -- il dettaglio (crescita della libreria nel tempo, file su disco vs skill "attuali") e' in `knowledge_map.md` (`tools\knowledge_map.bat`).

| sezione | pattern | coverage | book | usi | costo costruzione |
|---|---|---|---|---|---|
| `boundary_conditions` | off_by_one, wrong_comparison_operator, index_out_of_range_boundary, wrong_return_in_loop | PARTIALLY_COVERED | 3 | 8 | 34050 |
| `numerical_computing` | floating_point_equality, integer_division_truncation | COVERED | 2 | 8 | 33366 |
| `loop_state` | wrong_accumulator_init | COVERED | 1 | 4 | 13616 |
| `language_semantics` | mutable_default_argument, variable_shadowing | PARTIALLY_COVERED | 1 | 4 | 14259 |
| `boolean_logic` | inverted_boolean_logic | COVERED | 1 | 4 | 13285 |
| `data_ordering` | incorrect_sort_key_or_order | EMPTY | 0 | 0 | 0 |
| `data_structures` | key_error_missing_dict_check | COVERED | 1 | 0 | 0 |
| `string_processing` | wrong_string_case_comparison | COVERED | 1 | 0 | 0 |

## Nota metodologica
Ogni cella (task, config) ha una sola run. Un singolo fallimento non basta per dire se e' un problema sistematico dello skill o una variazione casuale del modello -- serve ripetere lo stesso task piu' volte per distinguerli.
Tutti i costi risultano $0.00: probabile prezzo non configurato per il provider in uso (vedi `GEMINI_INPUT_PER_MTOK`/`GEMINI_OUTPUT_PER_MTOK` in `.env`), non un run gratuito per davvero -- non affidarti a questo numero per ora.
