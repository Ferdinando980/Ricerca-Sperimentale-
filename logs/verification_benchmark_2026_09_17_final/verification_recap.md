# Recap verifica sostituzione meccanica -- verification_benchmark_2026_09_17_final

## 1. Riepilogo

11 pattern testati.

- **NO_SLOT** (7): nessuno slot identificato (nessun letterale da sostituire meccanicamente)
- **LOW_RISK** (2): slot trovato, tracking basso (rischio non materializzato)
- **HIGH_RISK_REPAIRED** (1): slot trovato, tracking alto, riparato e riverificato con successo
- **HIGH_RISK_UNRESOLVED** (1): slot trovato, tracking alto, NESSUNA riparazione sicura trovata

## 2. I 2 pattern con beneficio reale misurato oggi

Su 13 pattern nella libreria, solo questi 2 sono mai stati recuperati in una quest reale con un beneficio comportamentale dimostrato (librarian.py, retrieval_waste_analysis su 75 quest reali). Gli altri 8 sono in LOW_VALUE_RETRIEVAL_PATTERNS e route() li salta sempre -- il loro risultato qui sotto e' comunque reale, ma riguarda una skill che oggi non viene mai iniettata in pratica.

- **floating_point_equality**: NO_SLOT (tracking n/d) -- nessun letterale sostituibile identificato (atteso per circa meta' della libreria)
- **wrong_string_case_comparison**: HIGH_RISK_REPAIRED (tracking 50%) -- il letterale manipolabile non è più presente nel testo riscritto (swap non più applicabile allo stesso modo), holdout wrong_string_case_comparison__find_matching_tag__known_example superato

## 3. Validazione incrociata sui 4 casi noti

- **floating_point_equality** [DISACCORDO -- nessuno slot trovato]: atteso -- atteso HIGH_RISK (verificato a mano 2026-08-19, canary.py); il testo attuale potrebbe essere cambiato dall'audit del 2026-08-18 (vedi generation_method/version del Book)
- **wrong_accumulator_init** [DISACCORDO -- nessuno slot trovato]: atteso -- atteso LOW_RISK (slot candidato trovato, audit manuale 2026-08-18: rischio non materializzato); il testo attuale potrebbe essere cambiato dall'audit del 2026-08-18 (vedi generation_method/version del Book)
- **key_error_missing_dict_check** [DISACCORDO -- nessuno slot trovato]: atteso -- atteso LOW_RISK (slot candidato trovato, audit manuale 2026-08-18: rischio non materializzato); il testo attuale potrebbe essere cambiato dall'audit del 2026-08-18 (vedi generation_method/version del Book)
- **mutable_default_argument** [DISACCORDO]: atteso -- atteso LOW_RISK (slot candidato trovato, audit manuale 2026-08-18: rischio non materializzato); osservato -- HIGH_RISK_UNRESOLVED (tracking non sceso a sufficienza (tracking 75% -> 58%, richiesto un calo di almeno 25%))

**ATTENZIONE**: almeno un caso noto non e' stato riprodotto. Le conclusioni sui pattern MAI controllati a mano in questo stesso run vanno trattate con sospetto finche' il disaccordo non e' capito -- vedi validate_slot_identifier_milestone.py.

## 4. Skill riparate

- **wrong_string_case_comparison** (book_wrong_string_case_comparison_v2_v3 -> C:\Users\grego\Desktop\Ricerca\cognitive_rpg\library\books\book_wrong_string_case_comparison_v2_v3_v4.yaml): tracking 50% -> letterale rimosso, nessuna ri-ablazione applicabile. il letterale manipolabile non è più presente nel testo riscritto (swap non più applicabile allo stesso modo), holdout wrong_string_case_comparison__find_matching_tag__known_example superato

## 5. Casi non risolti -- materiale di analisi, non solo un numero

Ogni riga qui e' un fallimento reale della riparazione automatica, non solo un conteggio -- capire PERCHE' non ha funzionato e' esplicitamente parte dello scopo di questo benchmark (2026-09-17).

### mutable_default_argument (book_mutable_default_argument_v2_v3_v4)
- Slot identificato: `sentinel_value` = `None`
- Tracking originale: 75%
- Tracking dopo il tentativo di riscrittura: 58%
- Calo ottenuto: 17% (soglia richiesta per l'accettazione: 25%)
- Motivo: tracking non sceso a sufficienza (tracking 75% -> 58%, richiesto un calo di almeno 25%)


## 6. Tabella completa

| Pattern | Book | Status | Slot | Tracking | Dopo riparazione |
|---|---|---|---|---|---|
| floating_point_equality | book_floating_point_equality_v4_v5_v6 v6 | NO_SLOT | -- | -- | -- |
| general_case_completeness | book_general_case_completeness v1 | NO_SLOT | -- | -- | -- |
| index_out_of_range_boundary (low-value) | book_index_out_of_range_boundary_v2_v3_v4 v4 | LOW_RISK | length_function | 33% | -- |
| integer_division_truncation (low-value) | book_integer_division_truncation_v2_v3_v4 v4 | NO_SLOT | -- | -- | -- |
| inverted_boolean_logic (low-value) | book_inverted_boolean_logic_v2_v3 v3 | NO_SLOT | -- | -- | -- |
| key_error_missing_dict_check (low-value) | book_key_error_missing_dict_check_v2 v2 | NO_SLOT | -- | -- | -- |
| mutable_default_argument (low-value) | book_mutable_default_argument_v2_v3_v4 v4 | HIGH_RISK_UNRESOLVED | sentinel_value | 75% | 58% |
| off_by_one (low-value) | book_off_by_one_v2_v3_v4 v4 | LOW_RISK | test_input_element_count | 0% | -- |
| wrong_accumulator_init (low-value) | book_wrong_accumulator_init_v2_v3_v4 v4 | NO_SLOT | -- | -- | -- |
| wrong_comparison_operator (low-value) | book_wrong_comparison_operator_v2_v3_v4_v5 v5 | NO_SLOT | -- | -- | -- |
| wrong_string_case_comparison | book_wrong_string_case_comparison_v2_v3 v3 | HIGH_RISK_REPAIRED | case_normalization_method | 50% | -- |

## 7. Costo reale (solo chiamate al modello sotto test, vedi limite sotto)

70 chiamate al modello sotto test: $0.0000, 21549 token input, 4691 token output.

**Limite noto, non nascosto**: questo copre solo le chiamate al modello sotto test dentro substitution_ablation.py. Il costo delle chiamate Expert (identify_slot, generazione probe, giudice di estrazione dentro make_extractor, riscrittura in skill_repair.py) non e' ancora loggato per-chiamata -- e' un costo reale, non contabilizzato qui, non un costo assente.

## 8. Cosa questo run NON copre

- Un run per pattern, nessuna ripetizione: un singolo tracking ratio puo' muoversi per rumore di campionamento, non e' un effetto sistematico dimostrato con n=1.
- I pattern in LOW_VALUE_RETRIEVAL_PATTERNS sono testati per esercitare la pipeline, ma non sono mai raggiunti dal Librarian reale oggi -- un loro esito HIGH_RISK non e' un problema in produzione finche' quella politica resta com'e'.
- GENERATION_FAILED significa che il generatore di probe non ha prodotto nulla di usabile per quel pattern in questo run -- non e' evidenza che il pattern sia sicuro, solo che non e' stato misurato.
- L'audit delle direttive statiche nei prompt dell'app (fuori dalla libreria Book) e' una modalita' separata (static_audit.py), non incluso qui.

