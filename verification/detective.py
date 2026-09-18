"""Detective: generates a verified hypothesis about WHICH CASE of a skill's
own multi-case decision rule applies to one specific task -- the piece a
small model needs, and (per this whole session's findings) does not
spontaneously supply, before it can apply a tiered rule like floating_point_
equality's "explicit value > known domain convention > conservative
fallback" correctly to a NEW, unseen task instead of copying whichever
example it happened to see.

Design history (2026-09-18): the user's own proposal was a Detective that
finds hints about "what type of problem this is." First implementation used
a fixed checklist of 4 clue types (named concept / symptom type / branching
presence / domain convention) -- the user correctly rejected this as the
same mistake as a hardcoded keyword list, just one level up: not genuinely
generic, and liable to miss whatever a future skill's real distinguishing
signal turns out to be.

This version is generic across ANY skill with a multi-case rule, via the
SAME index-then-solve-each decomposition already validated live this
session for calculate_median (index the cases, solve each independently,
merge) and reused again in skill_conflict.py (index the task's own cases
before comparing two skills):

  1. Extract the DISTINCT CASES from the skill's own decision rule
     MECHANICALLY (a listing task, like slot_identifier's
     _EXTRACT_LITERALS_SYSTEM_PROMPT -- not a judgment call).
  2. For EACH case, generate the SPECIFIC QUESTION whose answer would
     confirm or rule out that case for THIS task -- open-ended per case,
     never drawn from a fixed list of question/clue types. A skill with
     different cases gets different questions, generated fresh every time;
     nothing here names "check for a percentage" or "check for a named
     domain" in advance.
  3. Answer each question using ONLY the task's own text (buggy_source,
     docstring, test_source) -- a VERBATIM quote from the task is required
     as evidence, or that case gets no support. Same fail-closed evidence
     bar as every other identify_*/extract_* function in this package.
  4. Exactly ONE case with real supporting evidence -> that is the
     hypothesis. Zero or more-than-one supported case -> INCONCLUSIVE, not
     an arbitrary pick -- ambiguity is a real, reportable outcome.
  5. Voted across samples (stabilizer.vote_for_result) for the same
     holistic-judgment stability reason as every identify_*/extract_*
     function elsewhere in this package.

What this is NOT: a repair mechanism. Detective does not rewrite the skill
or the task -- it produces a HYPOTHESIS (which case, backed by which real
quote) meant to be handed to the Worker as extra context, the same role
skill_conflict.py's COMPOUND annotation plays. Like skill_conflict.py, this
is deliberately NOT wired into quest_runner.py's real pipeline yet -- it
needs its own broad, real A/B/F/C-style validation of net effect before
being trusted as an always-on addition, exactly the lesson `general_case_
completeness` taught the hard way."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config
from ..adapters.base import ModelAdapter
from ..models import Book, Task
from .stabilizer import vote_for_result

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class DetectiveHypothesis:
    book_id: str
    task_id: str
    cases: list[str]
    case_questions: dict[str, str]
    supported_case: str | None  # None means INCONCLUSIVE
    evidence_quote: str | None  # None when resolved BY ELIMINATION (see by_elimination) -- a
    # fallback case has no positive marker to quote, so its "evidence" is that
    # every other case was explicitly ruled out, not a quote about itself.
    all_verdicts: dict[str, str | None]  # case -> evidence quote or None (transparency/logging)
    status: str  # RESOLVED | INCONCLUSIVE
    by_elimination: bool = False


_EXTRACT_CASES_SYSTEM_PROMPT = (
    "You are given a procedure ('skill') that describes a MULTI-CASE decision "
    "rule -- a rule that tells a reader to pick between two or more different "
    "cases/tiers/branches depending on the situation (e.g. 'if X, do A; else "
    "if Y, do B; else do C'). List each distinct case EXACTLY as it is "
    "described, in the order given. This is a MECHANICAL LISTING task, not a "
    "judgment call about which case applies to anything -- just enumerate the "
    "cases the rule itself defines.\n\n"
    "If the procedure has no such multi-case rule (a single, unconditional "
    "instruction), return an empty list.\n\n"
    "Return ONLY a JSON array of short strings, one per case, e.g. "
    '["an explicit tolerance is stated in the problem", "a known domain '
    'convention applies", "neither applies"]. Empty array [] if there is no '
    "multi-case rule."
)

_GENERATE_QUESTIONS_SYSTEM_PROMPT = (
    "You are given a procedure's multi-case decision rule and its FULL list "
    "of cases, in order. For EACH case, write the single most concrete, "
    "specific question whose answer -- if you could inspect a NEW, "
    "unrelated task -- would tell you whether THIS case applies to that "
    "task or not. Each question must be answerable by pointing at concrete "
    "text in the task (a stated number, a named domain, a specific "
    "phrase), not by opinion or by re-reading the rule itself.\n\n"
    "CRITICAL: you are shown every case together specifically so each "
    "question can be made to DISTINGUISH its case from every OTHER case "
    "listed -- two questions that could both be answered the same way for "
    "the same task are not doing their job. If two cases are naturally "
    "close (e.g. 'a specific convention applies' vs 'no convention "
    "applies'), make each question target what is UNIQUELY true of ITS "
    "case only.\n\n"
    "If a case is itself defined as a FALLBACK ('neither/none of the other "
    "cases applies') -- its truth is an ABSENCE (nothing else applies), "
    "which cannot be proven by quoting a specific piece of text (you cannot "
    "quote something that isn't there). For that case ONLY, return null "
    "instead of a question -- it will correctly be resolved by ruling out "
    "every other case instead, not by answering a question of its own.\n\n"
    "Every question MUST be a strict yes/no question, answerable only with "
    "true or false -- start it with a word like Is/Are/Does/Do/Did/Has/"
    "Have/Can/Was/Were. NEVER write an open question ('What tolerance is "
    "given?', 'Which convention applies?') even with a fallback instruction "
    "attached ('...if none, leave blank') -- that hybrid form is NOT a "
    "yes/no question and will be rejected. Bad: 'What known domain "
    "convention applies here? If none, leave blank.' Good: 'Does the task "
    "explicitly reference a currency, monetary amount, or other named "
    "domain convention?'\n\n"
    'Return ONLY JSON: {"questions": ["question for case 1", "question for '
    'case 2", null, ...]} -- same order and same length as the case list '
    "given, one entry per case (a real yes/no question, or null only for a "
    "fallback case as instructed above)."
)

_YES_NO_START_RE = re.compile(
    r"^(is|are|does|do|did|has|have|had|can|could|will|would|should|was|were)\b", re.IGNORECASE
)


def _is_yes_no_question(question: str) -> bool:
    """Mechanical well-formedness check, not a judgment call -- same
    verbatim-style discipline as everywhere else in this package: a
    generated 'question' that isn't even grammatically a yes/no question
    (starts with What/Which, or bolts on 'if none, leave blank') cannot be
    answered reliably as true/false no matter how good the answering model
    is. Found live: this exact malformed shape ('What X applies? If none,
    leave blank.') was one contributing cause of a wrong case resolution
    on a real catalog task."""
    q = question.strip()
    if not q.endswith("?"):
        return False
    if _YES_NO_START_RE.match(q) is None:
        return False
    lowered = q.lower()
    if "if none" in lowered or "if not" in lowered or "leave blank" in lowered:
        return False
    return True

_ANSWER_QUESTION_SYSTEM_PROMPT = (
    "You are given a specific task (its buggy source code, docstring, and "
    "test suite) and ONE yes/no question about it. Answer the question ONLY "
    "using what is actually stated in the task's own text. If your answer is "
    "yes, quote the EXACT substring from the task's text that supports it, "
    "copyable verbatim. If the task's text does not actually say anything "
    "that answers the question, answer no -- do not infer, assume, or guess "
    "from general knowledge of the domain.\n\n"
    "First, in the reasoning field, name the SPECIFIC part of the task's "
    "text you are looking at and state plainly what it does or does not "
    "say about the question -- decide your answer only after doing this, "
    "not before.\n\n"
    'Return ONLY JSON: {"reasoning": "one or two sentences, written first", '
    '"answer": true|false, "evidence_quote": "exact verbatim substring '
    'from the task" or null}'
)


def _task_text(task: Task) -> str:
    return f"{task.buggy_source}\n\n# Tests:\n{task.test_source}"


def _extract_cases(book: Book, adapter: ModelAdapter) -> list[str]:
    prompt = f"Procedure text (pattern: {book.pattern_id!r}):\n\n{book.procedure_text}"
    completion = adapter.complete(prompt=prompt, system=_EXTRACT_CASES_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
    match = re.search(r"\[.*\]", completion.text, re.DOTALL)
    if not match:
        return []
    try:
        cases = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [c for c in cases if isinstance(c, str) and c.strip()]


def _generate_questions(book: Book, cases: list[str], adapter: ModelAdapter) -> dict[str, str]:
    """All cases in ONE call (2026-09-18, real bug found live testing with
    Gemma: generating one question per case in ISOLATION -- the original
    design -- let two close cases ('a known convention applies' / 'neither
    applies') get near-duplicate questions, since neither call could see
    the other case's wording to differentiate against. Both questions then
    got answered the same way for every task, and the case could never be
    resolved (0/3 real trials on real catalog tasks, all INCONCLUSIVE).
    Showing every case together lets the model deliberately make each
    question distinguish its case from the others -- the fix is structural
    (more context, not a smarter model), consistent with every other fix
    in this package that helps a small model by decomposing/restructuring
    the task rather than asking it to try harder at the same one."""
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(cases))
    prompt = f"Procedure's decision rule:\n\n{book.procedure_text}\n\nFull list of cases:\n{numbered}"
    completion = adapter.complete(prompt=prompt, system=_GENERATE_QUESTIONS_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    questions = data.get("questions")
    if not isinstance(questions, list) or len(questions) != len(cases):
        return {}
    # Filtro meccanico (2026-09-18): una domanda mal formata (aperta, o
    # ibrida con un "if none, leave blank") non e' recuperabile -- scartarla
    # equivale a trattare quel caso come senza domanda, risolvibile solo per
    # esclusione, non a rischiare una risposta su qualcosa che non e'
    # davvero un sì/no.
    return {case: q for case, q in zip(cases, questions) if isinstance(q, str) and q.strip() and _is_yes_no_question(q)}


def _answer_question(task: Task, question: str, adapter: ModelAdapter) -> dict:
    """Tri-state, not binary -- 2026-09-18 fix for a real wrinkle found live:
    a FALLBACK case ('neither a nor b applies') has no positive textual
    marker to quote, so demanding a verbatim quote to confirm it degenerated
    to quoting the whole task, technically verbatim but not informative.
    Returns {"verdict": "YES"|"NO"|"UNKNOWN", "quote": str|None} -- YES needs
    a real verbatim quote (same fail-closed bar as everywhere else in this
    package); NO is an explicit, confirmed exclusion; UNKNOWN covers every
    unparseable/hallucinated-quote case, deliberately kept SEPARATE from NO
    -- inferring a fallback case by elimination (see _investigate_once) is
    only sound when every OTHER case was actually ruled out, not when we
    simply failed to get a clean answer for one of them."""
    # Delimitatore esplicito (2026-09-18) tra il testo del task (dati da cui
    # citare) e la domanda (istruzione) -- prima erano separati solo da
    # un'etichetta in prosa ("Task:\n\n..."), un confine debole per un
    # modello piccolo. I tripli backtick rendono il confine strutturale, non
    # solo testuale.
    prompt = f"Task:\n```\n{_task_text(task)}\n```\n\nQuestion: {question}"
    # 768, not 512: the "reasoning" field now written before answer/
    # evidence_quote adds real output length -- same truncation-risk
    # lesson as everywhere else in this project (raise the cap when the
    # required output grows, don't let a fixed tokens/reasoning field
    # collide with a fixed token cap).
    completion = adapter.complete(prompt=prompt, system=_ANSWER_QUESTION_SYSTEM_PROMPT, max_tokens=768, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return {"verdict": "UNKNOWN", "quote": None}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"verdict": "UNKNOWN", "quote": None}
    answer = data.get("answer")
    if answer is False:
        return {"verdict": "NO", "quote": None}
    if answer is not True:
        return {"verdict": "UNKNOWN", "quote": None}
    quote = data.get("evidence_quote")
    if not isinstance(quote, str) or not quote.strip():
        return {"verdict": "UNKNOWN", "quote": None}
    task_text = _task_text(task)
    if quote not in task_text:
        # Citazione allucinata -- non recuperabile, stesso principio
        # verbatim di ogni altro identify_*/extract_* in questo package.
        return {"verdict": "UNKNOWN", "quote": None}
    # Verifica di pertinenza (2026-09-18, bug reale trovato dal vivo): una
    # citazione VERA (appare per davvero nel testo) non e' la stessa cosa di
    # una citazione PERTINENTE alla domanda -- trovato dal vivo un caso dove
    # Gemma ha citato la riga del confronto stesso ('return sum(nums) /
    # len(nums) == target') come "prova" di una convenzione di dominio, che
    # quella riga non menziona affatto. Non e' lo stesso controllo di
    # survives_adversarial_check (quello cerca una citazione che CONTRADDICE
    # la conclusione, cosa impossibile qui perche' l'assenza non si cita) --
    # questo chiede direttamente, a un secondo giudizio indipendente, se la
    # citazione sostiene davvero la risposta o esiste solo nel testo.
    if not _quote_actually_supports(question, quote, adapter):
        return {"verdict": "UNKNOWN", "quote": None}
    return {"verdict": "YES", "quote": quote}


_QUOTE_RELEVANCE_SYSTEM_PROMPT = (
    "You are given a yes/no question and a quote claimed as evidence for "
    "answering YES to it. Decide, as a skeptical second reviewer: does this "
    "EXACT quote, read plainly, actually support a yes answer to the "
    "question -- or does it merely exist somewhere in the source text "
    "without genuinely answering the question (e.g. it's a piece of code "
    "or a generic statement that happens to be quotable, but says nothing "
    "about what the question actually asks)?\n\n"
    "First, in the reasoning field, state PLAINLY what the quote literally "
    "says, in your own words, with no reference to the question -- then "
    "decide separately whether that plain meaning actually answers the "
    "question.\n\n"
    'Return ONLY JSON: {"reasoning": "one sentence, written first", '
    '"quote_is_relevant": true|false}'
)


def _quote_actually_supports(question: str, quote: str, adapter: ModelAdapter) -> bool:
    prompt = f"Question: {question}\n\nQuote claimed as evidence: {quote!r}"
    completion = adapter.complete(prompt=prompt, system=_QUOTE_RELEVANCE_SYSTEM_PROMPT, max_tokens=512, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return False  # fail closed: risposta illeggibile non conta come pertinenza confermata
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return False
    return data.get("quote_is_relevant") is True


def _investigate_once(book: Book, task: Task, cases: list[str], case_questions: dict[str, str], adapter: ModelAdapter) -> dict:
    all_verdicts: dict[str, str | None] = {}
    raw: dict[str, dict] = {}
    for case in cases:
        question = case_questions.get(case)
        if question is None:
            raw[case] = {"verdict": "UNKNOWN", "quote": None}
            all_verdicts[case] = None
            continue
        raw[case] = _answer_question(task, question, adapter)
        all_verdicts[case] = raw[case]["quote"]

    supported = [c for c, r in raw.items() if r["verdict"] == "YES"]
    if len(supported) == 1:
        return {"status": "RESOLVED", "supported_case": supported[0], "evidence_quote": raw[supported[0]]["quote"],
                "all_verdicts": all_verdicts, "by_elimination": False}

    if len(supported) == 0:
        # Nessun caso ha evidenza positiva diretta -- possibile solo per
        # ELIMINAZIONE se OGNI altro caso e' stato esplicitamente escluso
        # (NO confermato, non solo "non determinato"). Un caso di fallback
        # ("nessuno dei due si applica") tipicamente finisce qui: non ha un
        # marcatore positivo da citare, ma e' comunque una conclusione solida
        # se tutte le alternative sono state davvero escluse una per una.
        ruled_out = [c for c, r in raw.items() if r["verdict"] == "NO"]
        remaining = [c for c in cases if c not in ruled_out]
        if len(remaining) == 1 and len(ruled_out) == len(cases) - 1:
            return {"status": "RESOLVED", "supported_case": remaining[0], "evidence_quote": None,
                    "all_verdicts": all_verdicts, "by_elimination": True}

    return {"status": "INCONCLUSIVE", "supported_case": None, "evidence_quote": None, "all_verdicts": all_verdicts, "by_elimination": False}


def investigate(book: Book, task: Task, adapter: ModelAdapter, n_samples: int = 3) -> DetectiveHypothesis | None:
    """None means the skill has no multi-case rule to investigate at all
    (extract_cases found nothing) -- a caller should not treat this the same
    as INCONCLUSIVE (a real rule whose applicable case could not be
    determined for this task): NONE means there was nothing to investigate,
    INCONCLUSIVE means investigation genuinely could not resolve it."""
    cases = _extract_cases(book, adapter)
    if len(cases) < 2:
        return None
    case_questions = _generate_questions(book, cases, adapter)
    if not case_questions:
        return None

    voted = vote_for_result(
        identify_fn=lambda: _investigate_once(book, task, cases, case_questions, adapter),
        key_fn=lambda r: r["supported_case"] or "__INCONCLUSIVE__",
        n_samples=n_samples,
    )
    if voted is None:
        return DetectiveHypothesis(
            book_id=book.id, task_id=task.task_id, cases=cases, case_questions=case_questions,
            supported_case=None, evidence_quote=None, all_verdicts={}, status="INCONCLUSIVE",
        )
    return DetectiveHypothesis(
        book_id=book.id, task_id=task.task_id, cases=cases, case_questions=case_questions,
        supported_case=voted["supported_case"], evidence_quote=voted["evidence_quote"],
        all_verdicts=voted["all_verdicts"], status=voted["status"], by_elimination=voted.get("by_elimination", False),
    )


_CACHE_PATH = Path(config.LOG_DIR) / "detective_cache.json"


def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def investigate_cached(book: Book, task: Task, adapter: ModelAdapter, n_samples: int = 3, force: bool = False) -> DetectiveHypothesis | None:
    """Same as investigate(), but checks a persistent on-disk cache first
    (2026-09-18, user-requested): the investigating model runs the SAME
    generic, already-authored procedure (index the cases, ask a
    distinguishing question per case, answer with verbatim evidence, resolve
    by elimination if needed) every time for a given (book, task) pair, so
    the hypothesis doesn't depend on which experiment run or which repeated
    trial is asking -- repeated validation runs (needed for the statistical
    power a single pilot run doesn't have) shouldn't redo that work every
    single time. Keyed by (book.id, task.task_id): a non-destructively
    versioned repair naturally gets a new book.id, so a repaired skill's
    cache entry does NOT stick around stale.

    IMPORTANT (corrected 2026-09-18, user pushback): `adapter` here should
    be the SAME Small-role model used elsewhere in the pipeline, not Expert
    -- calling a live Expert at runtime to help Detective would smuggle
    Expert's capability back into F+Detective, defeating the point of a
    Small-model system (the same failure mode the Cheater config exists to
    catch). Expert's real job already happened when this module's own
    prompts were authored (the generic method itself IS "how Claude would
    approach it") -- verified live that Gemma alone, with those prompts,
    correctly resolves real cases once a question-generation bug (two
    cases getting near-duplicate questions when generated in isolation,
    see _generate_questions) was fixed.

    `force=True` is the explicit "decide to re-run it anyway" escape hatch
    this caching intentionally keeps available -- e.g. after changing
    Detective's own prompts, or to check the hypothesis is still stable,
    rather than trusting a cache forever with no way back.

    Real bug found live (2026-09-18): a mock-mode infrastructure smoke test
    (EXPERT_PROVIDER=mock, canned garbage responses) called this through
    quest_runner.py and silently poisoned the persistent cache with `None`
    for real task ids, since a mock adapter can never produce a real
    extraction -- a later REAL run then trusted that cached `None` instead
    of recomputing, hiding a genuinely present rule. A `mock` provider is
    never authoritative about anything, so its calls bypass the cache
    entirely -- neither read nor written -- rather than being trusted or
    poisoning what real callers see later."""
    if getattr(adapter, "PROVIDER", None) == "mock":
        return investigate(book, task, adapter, n_samples=n_samples)
    cache = _load_cache()
    key = f"{book.id}::{task.task_id}"
    if not force and key in cache:
        cached = cache[key]
        return DetectiveHypothesis(**cached) if cached is not None else None
    hyp = investigate(book, task, adapter, n_samples=n_samples)
    cache[key] = asdict(hyp) if hyp is not None else None
    _save_cache(cache)
    return hyp
