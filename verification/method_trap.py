"""Third axis of substitution-risk testing (2026-09-17, user-requested after
rule_generalization.py correctly found NO literal-value risk in
wrong_string_case_comparison and the user pushed back: "no risk of THIS
kind" is not the same as "no risk"). This module tests the ANALOGOUS failure
for a skill whose procedure is a fixed METHOD/approach rather than a literal
value (e.g. "normalize with .casefold()") -- does the model apply that
method MECHANICALLY to a case where it is actually the WRONG fix, instead of
recognizing the method doesn't apply here?

Unlike rule_generalization.py (which needed an LLM judge to compare two
outputs, since Aria-style skills have no pytest oracle), this stays in
cognitive_rpg's own code domain, where an objective oracle DOES exist: the
"trap" scenario is constructed so a real pytest suite distinguishes a
correct, context-sensitive fix from the specific WRONG fix a model would
produce by applying the method blindly -- both verified by actually
EXECUTING the code (domain/verifier.run_tests), same objective-verification
philosophy as the rest of this project (design review D.9), not an LLM's
opinion about which is better.

Concretely: generate a buggy function whose surface symptom resembles the
skill's trigger (so the Librarian would plausibly retrieve this skill for
it), but whose real bug is NOT what the method fixes -- applying the method
verbatim produces code that still fails the real tests. Self-checked twice,
by execution: the ORIGINAL buggy code fails, AND the "mechanically applies
the method" candidate ALSO fails -- both real facts, not asserted by the
generator. Then run the model under test with the skill attached; if its own
code both (a) fails the real tests and (b) shows the method's own marker
pattern in use, that is direct evidence of mechanical application, not a
coincidental unrelated failure."""

import json
import re
from dataclasses import dataclass

from ..adapters.base import ModelAdapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..domain.verifier import run_tests
from ..experiment.events import emit
from ..models import Book, SkillPackage, Task
from .stabilizer import survives_adversarial_check, vote_for_result

_METHOD_SYSTEM_PROMPT = (
    "You inspect a procedure ('skill') for fixing a specific bug pattern. Some "
    "such procedures prescribe a fixed METHOD/approach (e.g. a specific "
    "function or transformation to apply) rather than a literal example "
    "value. Such a method is only CORRECT when its triggering condition "
    "genuinely holds -- applying it to a superficially-similar but different "
    "root cause would be wrong. Identify: the method itself, a short literal "
    "marker that would appear in code actually using it (e.g. '.casefold(' "
    "for a case-normalization method), and the specific condition under which "
    "applying it is correct (so a case where that condition does NOT hold, "
    "despite a similar-looking symptom, can be constructed).\n\n"
    "Return ONLY a single JSON object, no prose, no markdown fences:\n"
    '- If applicable: {"has_condition": true, "method": "one sentence, what '
    'the procedure prescribes", "method_marker": "a short literal substring '
    'that would appear verbatim in code applying this method, copied from the '
    'procedure text if it appears there", "condition": "one sentence: when is '
    'applying this method actually correct"}\n'
    '- If the method is universally correct whenever the skill\'s own symptom '
    'applies (no meaningful "wrong context" case exists): {"has_condition": '
    'false, "reason": "one sentence"}'
)

_TRAP_SYSTEM_PROMPT = (
    "You write ONE probe task that tests whether a model applies a fix METHOD "
    "only when appropriate, instead of mechanically whenever the symptom "
    "superficially resembles the trigger. Given the method, its marker, and "
    "its correct-use condition, invent a small buggy Python function whose "
    "SYMPTOM looks similar to what the method fixes, but whose CONDITION for "
    "the method does NOT hold -- so applying the method would produce code "
    "that still fails the real tests. Then also write the WRONG fix a model "
    "would produce by applying the method mechanically here (using the "
    "method's own marker), and a pytest suite where: the original buggy code "
    "fails, AND the wrong/mechanical fix ALSO fails (both facts you must get "
    "right, they will be verified by actually running them) -- there must "
    "exist SOME correct fix that does NOT use the method and passes, though "
    "you do not need to provide it.\n\n"
    "If you are told a previous attempt failed, that failure is itself a "
    "concrete signal, the same way a careful reviewer treats a failed "
    "experiment as data rather than repeating it unchanged: an abstractly-"
    "stated condition (e.g. 'when it is semantically appropriate') is often "
    "too vague to operationalize into code that provably fails one way or "
    "the other. When that happens, first RESTATE the condition as a "
    "concrete, code-observable signal -- something you could check by "
    "reading the function's source or its inputs/outputs, not a judgment "
    "call (e.g. turn 'when the boundary is meant to be exclusive' into 'the "
    "docstring/spec explicitly uses a phrase like up to / at most / fewer "
    "than, vs. at least / more than / at least as many') -- THEN build the "
    "buggy/mechanical/test trio around that sharpened, concrete version.\n\n"
    "Return ONLY a single JSON object, no prose, no markdown fences: "
    '{"problem_id": "...", "fn_name": "...", "buggy_source": "...", '
    '"mechanical_fix_source": "...", "test_source": "..."}. All source fields '
    "are raw Python as JSON strings (\\n for newlines)."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class MethodSpec:
    method: str
    method_marker: str
    condition: str


def extract_method(book: Book, adapter: ModelAdapter) -> MethodSpec | None:
    prompt = f"Procedure text (pattern: {book.pattern_id!r}):\n\n{book.procedure_text}"
    completion = adapter.complete(prompt=prompt, system=_METHOD_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not data.get("has_condition"):
        return None
    method_marker = str(data.get("method_marker") or "").strip()
    if not method_marker:
        return None
    method = str(data.get("method") or "").strip()
    condition = str(data.get("condition") or "").strip()
    if not method or not condition:
        return None
    # Stesso stabilizzatore generico di slot_identifier.py (2026-09-17):
    # "has_condition: true" e' lo stesso tipo di giudizio olistico che si e'
    # mostrato instabile altrove -- prima di fidarsene, verificare che regga
    # a un tentativo reale di smentita con citazione verbatim.
    claim_summary = f"has_condition=True, method={method!r}, condition={condition!r}"
    if not survives_adversarial_check(book.procedure_text, method_marker, claim_summary, adapter):
        return None
    return MethodSpec(method=method, method_marker=method_marker, condition=condition)


def extract_method_stable(book: Book, adapter: ModelAdapter, n_samples: int = 3) -> MethodSpec | None:
    """extract_method + majority voting (2026-09-18) -- see slot_identifier.
    identify_slot_stable / stabilizer.vote_for_result for why. Default entry
    point for callers; extract_method remains the single-sample primitive."""
    return vote_for_result(
        identify_fn=lambda: extract_method(book, adapter),
        key_fn=lambda method_spec: method_spec.method_marker,
        n_samples=n_samples,
    )


@dataclass
class TrapScenario:
    task: Task
    mechanical_fix_source: str


def generate_trap_scenario(book: Book, method: MethodSpec, adapter: ModelAdapter, max_attempts: int = 3) -> TrapScenario | None:
    """Self-checked TWICE by real execution (not asserted by the generator):
    the buggy source must fail its own tests, AND the mechanically-applied
    "wrong fix" must ALSO fail them -- that second check is what proves the
    trap is genuine (the method is not just insufficient but actively wrong
    here), not just a harder bug.

    2026-09-18: each failed attempt's SPECIFIC reason is now fed back into
    the next attempt's prompt instead of being silently discarded (a blind
    retry with no diagnostic info repeats the same mistake -- this was a
    real, observed bottleneck: wrong_comparison_operator's automated repair
    exhausted every attempt here, never learning WHY, see inspector.py's
    run_repair_loop). Same shape as every other prior_feedback loop in this
    package: capture the concrete reason, hand it back, let the model react
    to it instead of guessing cold again."""
    feedback: str | None = None
    for _ in range(max_attempts):
        prompt = (
            f"Method: {method.method}\nMarker: {method.method_marker!r}\n"
            f"Correct-use condition: {method.condition}\nPattern: {book.pattern_id!r}"
        )
        if feedback:
            prompt += f"\n\nPrevious attempt failed: {feedback}"
        completion = adapter.complete(prompt=prompt, system=_TRAP_SYSTEM_PROMPT, max_tokens=4096)
        match = _JSON_RE.search(completion.text)
        if not match:
            feedback = "your response did not contain a parseable JSON object -- return ONLY the JSON object, no prose, no markdown fences."
            continue
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            feedback = "your JSON object did not parse -- check for unescaped quotes/newlines inside the source-code string fields."
            continue
        required = {"problem_id", "fn_name", "buggy_source", "mechanical_fix_source", "test_source"}
        if not required.issubset(data):
            feedback = f"your JSON object was missing required field(s): {sorted(required - set(data))}."
            continue
        buggy_source, mechanical_fix_source, test_source = data["buggy_source"], data["mechanical_fix_source"], data["test_source"]
        if not all(isinstance(v, str) and v.strip() for v in (buggy_source, mechanical_fix_source, test_source)):
            feedback = "one of buggy_source/mechanical_fix_source/test_source was empty or not a string."
            continue
        buggy_result = run_tests(buggy_source, test_source)
        mechanical_result = run_tests(mechanical_fix_source, test_source)
        if buggy_result.passed and mechanical_result.passed:
            feedback = (
                "both buggy_source and mechanical_fix_source PASSED your own tests -- neither is actually "
                "buggy. Make the original bug more clearly present, and make sure the mechanical fix's own "
                "marker use does not accidentally already produce correct behavior."
            )
            continue
        if buggy_result.passed:
            feedback = (
                "buggy_source PASSED your own tests -- it needs to be genuinely broken. The bug and the "
                "trap condition are independent requirements: fix the bug's presence first."
            )
            continue
        if mechanical_result.passed:
            feedback = (
                "mechanical_fix_source PASSED your own tests, so it isn't actually the wrong fix here -- "
                "the trap condition you described is not genuinely violated by this scenario. Restate the "
                "condition as a concrete, code-observable signal (see the system instructions) and build a "
                "case where that concrete signal is clearly absent, not just plausibly absent."
            )
            continue
        task = Task(
            task_id=f"{book.pattern_id}__{data['problem_id']}__methodtrap",
            pattern_id=book.pattern_id, problem_id=data["problem_id"], fn_name=data["fn_name"],
            buggy_source=buggy_source, test_source=test_source, split="METHOD_TRAP",
            problem_tags=list(book.problem_tags), capability_tags=list(book.capability_tags),
        )
        return TrapScenario(task=task, mechanical_fix_source=mechanical_fix_source)
    return None


@dataclass
class MethodTrapResult:
    pattern_id: str
    book_id: str
    method: str
    method_marker: str
    condition: str
    code: str
    tests_passed: bool
    used_marker: bool
    verdict: str  # AVOIDED_TRAP | MECHANICAL_APPLICATION | INCONCLUSIVE_UNRELATED_FAILURE
    task_id: str = ""


def run_method_trap_check(
    experiment_id: str, book: Book, method: MethodSpec, scenario: TrapScenario, test_adapter: ModelAdapter,
) -> MethodTrapResult:
    """Un SINGOLO scenario-trappola -- vedi run_method_trap_checks per la
    versione con piu' scenari e verdetto aggregato, quella da usare per
    qualunque conclusione reale (un campione solo e' rumore, non evidenza,
    stesso principio gia' applicato altrove in questo pacchetto)."""
    package = SkillPackage(books=[book], coverage="FULL")
    prompt = build_prompt(scenario.task, package)
    completion = test_adapter.complete(prompt=prompt, system=SYSTEM_PROMPT, max_tokens=4096)
    code = extract_code(completion.text)
    result = run_tests(code, scenario.task.test_source)
    used_marker = method.method_marker in code

    if result.passed:
        # Ha superato i test REALI -- ha trovato un fix corretto, sensibile
        # al contesto, che il metodo da solo non avrebbe dato (la trappola
        # garantisce che applicare il metodo alla lettera fallisce sempre).
        verdict = "AVOIDED_TRAP"
    elif used_marker:
        # Fallisce E usa il marcatore del metodo -- applicazione meccanica,
        # esattamente come mechanical_fix_source, verificato per esecuzione
        # reale non per opinione di un giudice.
        verdict = "MECHANICAL_APPLICATION"
    else:
        # Fallisce ma non per il motivo che stiamo testando -- un fallimento
        # generico di capacita', non un'evidenza di sostituzione meccanica.
        verdict = "INCONCLUSIVE_UNRELATED_FAILURE"

    emit(
        experiment_id, scenario.task.task_id, "METHOD_TRAP", "method_trap:check",
        "METHOD_TRAP_CHECK", reason="method_trap",
        book_id=book.id, method_marker=method.method_marker, tests_passed=result.passed,
        used_marker=used_marker, verdict=verdict,
    )
    return MethodTrapResult(
        pattern_id=book.pattern_id, book_id=book.id, method=method.method, method_marker=method.method_marker,
        condition=method.condition, code=code, tests_passed=result.passed, used_marker=used_marker, verdict=verdict,
        task_id=scenario.task.task_id,
    )


@dataclass
class AggregatedMethodTrapResult:
    pattern_id: str
    book_id: str
    method: str
    method_marker: str
    per_scenario: list[MethodTrapResult]
    n_scenarios: int
    n_mechanical: int
    n_avoided: int
    n_inconclusive: int
    verdict: str  # HIGH_RISK | LOW_RISK | INCONCLUSIVE (tutti gli scenari non concludenti)


def run_method_trap_checks(
    experiment_id: str, book: Book, method: MethodSpec, adapter: ModelAdapter, test_adapter: ModelAdapter,
    n_scenarios: int = 3, max_attempts_per_scenario: int = 3,
) -> AggregatedMethodTrapResult | None:
    """N scenari-trappola INDIPENDENTI (non lo stesso scenario ripetuto --
    generate_trap_scenario e' chiamato N volte, ognuna puo' inventare un
    caso diverso), verdetto aggregato per maggioranza sui soli scenari
    conclusivi (AVOIDED_TRAP o MECHANICAL_APPLICATION -- un INCONCLUSIVE
    non vota ne' per rischio ne' contro, non e' evidenza in nessuna
    direzione). Ritorna None se non si riesce a generare NEMMENO uno
    scenario valido (impossibile dire qualunque cosa)."""
    per_scenario: list[MethodTrapResult] = []
    for _ in range(n_scenarios):
        scenario = generate_trap_scenario(book, method, adapter, max_attempts=max_attempts_per_scenario)
        if scenario is None:
            continue
        per_scenario.append(run_method_trap_check(experiment_id, book, method, scenario, test_adapter))

    if not per_scenario:
        return None

    n_mechanical = sum(1 for r in per_scenario if r.verdict == "MECHANICAL_APPLICATION")
    n_avoided = sum(1 for r in per_scenario if r.verdict == "AVOIDED_TRAP")
    n_inconclusive = sum(1 for r in per_scenario if r.verdict == "INCONCLUSIVE_UNRELATED_FAILURE")
    conclusive = n_mechanical + n_avoided
    if conclusive == 0:
        verdict = "INCONCLUSIVE"
    elif n_mechanical / conclusive >= 0.5:
        verdict = "HIGH_RISK"
    else:
        verdict = "LOW_RISK"

    return AggregatedMethodTrapResult(
        pattern_id=book.pattern_id, book_id=book.id, method=method.method, method_marker=method.method_marker,
        per_scenario=per_scenario, n_scenarios=len(per_scenario), n_mechanical=n_mechanical,
        n_avoided=n_avoided, n_inconclusive=n_inconclusive, verdict=verdict,
    )
