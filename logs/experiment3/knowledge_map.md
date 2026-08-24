# Knowledge Map -- experiment3
_Generato: 2026-08-18 23:18 UTC_

Fase 1 dell'evoluzione della libreria (vedi conversazione 2026-08-18): sola lettura, nessun cambio di comportamento a retrieval o generazione. COVERED = tutti i pattern della sezione hanno un Book; EMPTY = nessuno (i 3 pattern NOVEL permanenti -- variable_shadowing, incorrect_sort_key_or_order, wrong_return_in_loop -- risultano sempre EMPTY per design, non e' un gap da colmare).

| sezione | pattern | coverage | book attuali | file su disco | usi | costo costruzione | risparmio medio/uso |
|---|---|---|---|---|---|---|---|
| `boundary_conditions` (Boundary Conditions) | off_by_one, wrong_comparison_operator, index_out_of_range_boundary, wrong_return_in_loop | PARTIALLY_COVERED | 3 | 3 | 0 | 0 | n/d |
| `numerical_computing` (Numerical Computing) | floating_point_equality, integer_division_truncation | COVERED | 2 | 2 | 4 | 36945 | +388 |
| `loop_state` (Loop State & Accumulation) | wrong_accumulator_init | COVERED | 1 | 1 | 0 | 0 | n/d |
| `language_semantics` (Python Language Semantics) | mutable_default_argument, variable_shadowing | PARTIALLY_COVERED | 1 | 1 | 0 | 0 | n/d |
| `boolean_logic` (Boolean Logic) | inverted_boolean_logic | COVERED | 1 | 1 | 0 | 0 | n/d |
| `data_ordering` (Data Ordering) | incorrect_sort_key_or_order | EMPTY | 0 | 0 | 0 | 0 | n/d |
| `data_structures` (Data Structures) | key_error_missing_dict_check | COVERED | 1 | 1 | 0 | 0 | n/d |
| `string_processing` (String & Text Processing) | wrong_string_case_comparison | COVERED | 1 | 1 | 0 | 0 | n/d |


## Similarity / Duplicate detection
- DISTINCT: 3, RELATED: 1 (totale 4 coppie)

## Genealogia
`derived_from` (compressione meccanica -- dalla convenzione di naming dell'optimizer) e `duplicate_of`/`related_skills` (solo il caso informativo cross-pattern -- vedi Similarity sopra) sui file attuali.

| book | derived_from | duplicate_of | related_skills |
|---|---|---|---|
| `book_floating_point_equality_v4_v5` | book_floating_point_equality_v4 | - | - |
| `book_index_out_of_range_boundary_v2_v3` | book_index_out_of_range_boundary_v2 | - | book_off_by_one_v2_v3 |
| `book_integer_division_truncation_v2_v3_v4` | book_integer_division_truncation_v2_v3 | - | - |
| `book_inverted_boolean_logic_v2_v3` | book_inverted_boolean_logic_v2 | - | - |
| `book_key_error_missing_dict_check_v2` | book_key_error_missing_dict_check | - | - |
| `book_mutable_default_argument_v2_v3_v4` | book_mutable_default_argument_v2_v3 | - | - |
| `book_off_by_one_v2_v3` | book_off_by_one_v2 | - | book_index_out_of_range_boundary_v2_v3 |
| `book_wrong_accumulator_init_v2_v3_v4` | book_wrong_accumulator_init_v2_v3 | - | - |
| `book_wrong_comparison_operator_v2_v3` | book_wrong_comparison_operator_v2 | - | - |
| `book_wrong_string_case_comparison_v2` | book_wrong_string_case_comparison | - | - |

## Classificazione economica
Due assi per pattern: **accuracy_value** = HIGH se F ha davvero salvato un fallimento di A o B su un task di quel pattern (non solo "F ha accuracy alta" in astratto); **economic_value** = HIGH se il risparmio e' positivo e il breakeven e' entro 20 usi (soglia dichiarata in `economics.py`, non nascosta). **NEGATIVE non significa "elimina"** -- puo' avere valore strategico non catturato da queste due metriche con cosi' pochi dati.

| pattern | accuracy_value | economic_value | classificazione |
|---|---|---|---|
| `floating_point_equality` | HIGH | LOW | ACCURACY_POSITIVE |

## Library usefulness (densita' di conoscenza utile)
- 10 contenuti distinti su 10 file su disco -> densita' 100% (spec #21: il numero di skill non e' la metrica giusta, questa lo e').

## Crescita della libreria (snapshot nel tempo)
| snapshot | n. book |
|---|---|
| `mid_evolutionary_optimizer_2026-08-18_1451` | 21 |
| `post_evolutionary_optimizer_2026-08-18` | 22 |
| `post_skill_generator_2026-08-18` | 18 |
| `pre_duplicate_cleanup_2026-08-18` | 22 |
| `pre_phase1_knowledge_map` | 22 |

