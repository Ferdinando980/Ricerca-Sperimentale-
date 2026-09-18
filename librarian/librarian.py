from ..library.loader import load_books
from ..models import Book, SkillPackage, Task

# Real, measured evidence (2026-08-19, prompted by external review), not a
# guess: experiment/metrics.py's retrieval_waste_analysis(), run across all
# 4 real experiments in this investigation (75 quests where a skill was
# actually injected), found that these 8 patterns NEVER once produced a
# measured behavioral difference vs B (no skill) -- every single injection
# was either neutral (B passed anyway -- 61/75 quests overall, 81.3%) or
# harmful. Only floating_point_equality and wrong_string_case_comparison
# ever had a quest where the skill demonstrably made the difference (B
# failed, F passed) -- consistent with economics.py's earlier, independently
# -derived accuracy_value classification (LOW for the same 8, HIGH only for
# these 2). The other 3 patterns covered by bug_catalog.py (variable_
# shadowing, incorrect_sort_key_or_order, wrong_return_in_loop) are the
# permanently-NOVEL control group with no Book at all -- already never
# retrieved, not included here.
#
# This is a snapshot of current evidence, not a permanent verdict: if a
# pattern's Book changes materially, or usage volume grows, recompute
# retrieval_waste_analysis() across the updated experiment set before
# trusting this list unchanged.
LOW_VALUE_RETRIEVAL_PATTERNS = {
    "off_by_one",
    "wrong_comparison_operator",
    "mutable_default_argument",
    "integer_division_truncation",
    "inverted_boolean_logic",
    "wrong_accumulator_init",
    "index_out_of_range_boundary",
    "key_error_missing_dict_check",
}


# Meccanismo per skill generiche, non legate a un pattern di bug specifico --
# "sempre incluse" bypassando il tag-matching, per una regola di ragionamento
# potenzialmente utile a QUALSIASI task. Aggiunto 2026-09-17 per
# `general_case_completeness` (verification/, sessione sul motore di
# sostituzione meccanica), poi RIMOSSO lo stesso giorno dopo un vero run
# experiment_0 (A/B/F/C, 39 task, coverage=NONE isolato): sugli stessi 33
# task dove F non aveva nessuna skill specifica, B (Gemma nudo) ha fatto
# 84.8%, F (Gemma + solo quella skill generica) 63.6% -- un calo di 21 punti,
# non rumore. La validazione originale (calculate_median 0/4->4/4,
# rolling_average 1/4->2/4) era su 2 casi scelti apposta perche' avevano
# bisogno esattamente di quel ragionamento -- mai testata sul caso ordinario
# dove non serve, e li' costa piu' di quanto aiuti (token, il modello si
# mette a cercare casi nascosti che non esistono). Insegnamento generale: una
# skill "sempre attiva" va validata su un campione ampio e vario PRIMA di
# essere collegata qui, non solo sul caso che ha motivato a scriverla.
# `book_general_case_completeness.yaml` resta in libreria (non e' pericolosa
# di per se', i suoi capability_tags non intersecano nessun task reale, quindi
# resta comunque irraggiungibile anche dal tag-matching normale) -- solo
# l'inclusione incondizionata e' stata rimossa. L'infrastruttura sotto resta,
# per una futura skill genuinamente generica che sia stata validata su un
# campione ampio prima di essere collegata qui, non solo su 1-2 casi.
ALWAYS_INCLUDED_PATTERN_IDS: set[str] = set()


def _always_included_books(books: list[Book]) -> list[Book]:
    return [b for b in _latest_per_pattern(books) if b.pattern_id in ALWAYS_INCLUDED_PATTERN_IDS]


def _latest_per_pattern(books: list[Book]) -> list[Book]:
    """When the optimizer saves a compressed copy of a Book, it keeps the same
    pattern_id and bumps version, never overwriting the original file (see
    librarian/optimizer.py:save_compressed_book) -- so two files for the same
    pattern can legitimately coexist on disk. Routing on tag overlap alone
    doesn't know they're versions of the same skill and was injecting both
    into the prompt together, double-charging tokens and mixing an outdated
    compressed procedure with an updated original. Keep only the
    highest-version Book per pattern_id before scoring."""
    best: dict[str, Book] = {}
    for book in books:
        current = best.get(book.pattern_id)
        if current is None or book.version > current.version:
            best[book.pattern_id] = book
    return list(best.values())


def route(task: Task, max_books: int = 2, min_overlap: int = 1, respect_value_policy: bool = True) -> SkillPackage:
    """Deterministic tag-overlap retrieval -- no model call, no embedding API, so
    routing itself never shows up as a hidden cost (design review D.6). At the
    20-50 Book scale of MVP-1 this is sufficient; embeddings/ANN only become
    necessary at the library-scaling stage of §L.

    respect_value_policy (default True, added 2026-08-19): skip retrieval
    entirely -- return SkillPackage(books=[], coverage="NONE") -- for
    patterns in LOW_VALUE_RETRIEVAL_PATTERNS, the 8 (of 13 tested) patterns
    whose skill has never once shown a measured benefit over B across 75
    real injected quests (81.3% measured waste overall). This is the direct
    fix, not a cost-reduction workaround: stop paying retrieval-overhead
    tokens on patterns already shown not to need it, instead of optimizing
    the cost of injecting where it doesn't help. Set False to reproduce the
    old tag-overlap-only behavior -- e.g. to re-test whether a pattern's
    classification still holds after its Book changes, since this list is a
    snapshot of evidence, not a permanent verdict (see the set's own
    comment). ALWAYS_INCLUDED_PATTERN_IDS (added 2026-09-17) e' un asse
    separato -- una regola di ragionamento generica, non un match di pattern
    -- e viene unita al risultato in ogni caso, anche quando
    respect_value_policy fa scattare lo short-circuit sotto: NON conta ai
    fini di `coverage`, che resta il segnale di retrieval PER-PATTERN che
    metrics.py/knowledge_map.py gia' usano com'e'."""
    all_books = load_books()
    always_books = _always_included_books(all_books)

    if respect_value_policy and task.pattern_id in LOW_VALUE_RETRIEVAL_PATTERNS:
        return SkillPackage(books=always_books, coverage="NONE")

    scored = []
    for book in _latest_per_pattern(all_books):
        if book.pattern_id in ALWAYS_INCLUDED_PATTERN_IDS:
            continue  # gia' incluso incondizionatamente, non farlo pesare due volte sul matching per tag
        overlap = len(set(book.capability_tags) & set(task.capability_tags))
        if overlap >= min_overlap:
            scored.append((overlap, book))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top_books = [book for _, book in scored[:max_books]]

    if not top_books:
        coverage = "NONE"
    elif scored[0][0] == len(task.capability_tags):
        coverage = "FULL"
    else:
        coverage = "PARTIAL"

    return SkillPackage(books=always_books + top_books, coverage=coverage)
