"""Second, complementary axis of substitution-risk testing (added 2026-09-17
after a design correction from the user): substitution_ablation.py tests by
MANIPULATING THE SKILL (inject a fake variant literal) while holding the
scenario fixed, and needs to know the "correct" value to score a match --
fine when there's an objective oracle (pytest), but this project's Aria port
has none for a generic user-written skill (see skillSubstitutionRisk.ts's
own documented limitation: a self-declared "expected value" is not an
independent oracle).

This module instead HOLDS THE SKILL FIXED and VARIES THE SCENARIO: extract
the skill's own GENERAL RULE (a principle for deriving the value from a
situation's specifics, e.g. "tolerance scales with the domain's precision")
plus an explicit ANTI-PATTERN (literally reusing the skill's own illustrative
example value regardless of context -- named concretely, verified verbatim
in the text, exactly as substitution_ablation.py's slot does). Then generate
two DELIBERATELY CONTRASTING scenarios that, under that rule, should need
CLEARLY DIFFERENT derived values (a qualitative direction only -- "A should
need much less than B" -- never an absolute number, so no self-declared
oracle is needed). Run the SAME unmodified skill on both. Score two things
that do NOT require knowing an absolute ground truth:
  1. a cheap, deterministic, no-LLM substring check: does either raw
     response literally contain the named anti-pattern literal where the
     scenario doesn't call for it? (mirrors identify_slot's own verbatim
     philosophy -- exact text presence, not an LLM's opinion about it)
  2. one LLM judge call comparing BOTH responses side by side against the
     stated rule and expected direction: did they differ the way the rule
     predicts (real derivation), or collapse to the same value/approach
     despite needing to differ (recitation)?

This is the SAME floating_point_equality canary.py originally did by hand
(same_destination vs invoice_totals_match, two different domains, one
skill) -- generalized into a reusable, repeatable engine instead of a
one-off hand-authored pair. Uses Gemma for the model under test, the Expert
role for rule/scenario generation and judging -- same role split as every
other module in this package."""

import json
import re
from dataclasses import dataclass, field

from ..adapters.base import ModelAdapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..domain.verifier import run_tests
from ..experiment.events import emit
from ..models import Book, SkillPackage, Task
from .stabilizer import survives_adversarial_check, vote_for_result

_RULE_SYSTEM_PROMPT = (
    "You inspect a procedure ('skill') written to help an economical language "
    "model avoid a specific bug pattern. If it illustrates the rule with ONE "
    "concrete literal example value (a number, a threshold, a default), your "
    "job is to state the GENERAL PRINCIPLE that value is an instance of -- how "
    "the right value should depend on the SPECIFIC situation, not the fixed "
    "example. State also, explicitly, the ANTI-PATTERN: reusing that exact "
    "example value in a situation where it does not apply.\n\n"
    "Return ONLY a single JSON object, no prose, no markdown fences:\n"
    '- If there is such an example: {"has_rule": true, "rule": "the general '
    'principle, as a function of situation-specific properties, one or two '
    'sentences", "literal_to_avoid": "the EXACT example value as it appears '
    'in the text, verbatim", "anti_pattern": "one sentence naming what reusing '
    'that literal inappropriately would look like"}\n'
    '- If the skill has no such illustrative literal (a discrete structural/'
    'operator choice, nothing to generalize a rule from): {"has_rule": false, '
    '"reason": "one sentence"}\n'
    "literal_to_avoid must be copyable verbatim from the procedure text."
)

_SCENARIO_SYSTEM_PROMPT = (
    "You write TWO probe tasks that test whether a language model DERIVES a "
    "value from a situation's specifics, following a stated general rule, "
    "instead of reusing one fixed example value regardless of context. Given "
    "the rule and the pattern it applies to, invent two small, self-contained "
    "buggy Python functions (matching the pattern) set in DELIBERATELY "
    "DIFFERENT situations such that, under the rule, the correct value for "
    "situation A should be clearly different from situation B (state only the "
    "QUALITATIVE direction -- 'A needs a much smaller value than B' -- never "
    "an exact number, since no one has independently verified the exact "
    "correct number). Neither situation may mention the rule's own literal "
    "example verbatim, and neither may state its own target value numerically "
    "-- the model being tested must derive it, not read it off. Provide a real "
    "pytest suite for each that actually FAILS against the buggy version and "
    "would PASS a correct derivation-based fix (the tests may use a tolerant "
    "range rather than one exact number, since the exact correct value is "
    "itself not independently known).\n\n"
    "Return ONLY a single JSON object, no prose, no markdown fences: "
    '{"scenario_a": {"problem_id": "...", "fn_name": "...", "buggy_source": '
    '"...", "test_source": "...", "situation": "one sentence"}, "scenario_b": '
    '{same shape}, "direction": "one sentence stating which of A/B should need '
    'the larger/smaller/different value and why, qualitatively"}. buggy_source '
    "and test_source are raw Python source as JSON strings (\\n for newlines)."
)

_COMPARE_SYSTEM_PROMPT = (
    "You compare two responses to two deliberately contrasting situations, "
    "given the general rule they should both follow and the expected "
    "qualitative direction of difference between them. Decide: did the two "
    "responses actually differ the way the rule predicts (genuine derivation "
    "from each situation), or did they collapse to essentially the same value "
    "or approach despite needing to differ (the rule was not really applied)? "
    "Reply with EXACTLY two lines: GENERALIZES or DOES_NOT_GENERALIZE alone on "
    "line 1, one short sentence of reasoning on line 2. No other text."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class RuleSpec:
    rule: str
    literal_to_avoid: str
    anti_pattern: str


def extract_rule(book: Book, adapter: ModelAdapter) -> RuleSpec | None:
    prompt = f"Procedure text (pattern: {book.pattern_id!r}):\n\n{book.procedure_text}"
    completion = adapter.complete(prompt=prompt, system=_RULE_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not data.get("has_rule"):
        return None
    literal_to_avoid = data.get("literal_to_avoid")
    if not isinstance(literal_to_avoid, str) or not literal_to_avoid.strip():
        return None
    if literal_to_avoid not in book.procedure_text:
        # Stesso principio di verbatim-fail-closed di slot_identifier.py --
        # non fidarsi di un letterale che il modello ha paraprasato.
        return None
    rule = str(data.get("rule") or "").strip()
    anti_pattern = str(data.get("anti_pattern") or "").strip()
    if not rule or not anti_pattern:
        return None
    # Stesso stabilizzatore generico di slot_identifier.py/method_trap.py
    # (2026-09-17): "has_rule: true" e' lo stesso tipo di giudizio olistico
    # instabile altrove -- verificare che regga a un tentativo di smentita.
    claim_summary = f"has_rule=True, rule={rule!r}"
    if not survives_adversarial_check(book.procedure_text, literal_to_avoid, claim_summary, adapter):
        return None
    return RuleSpec(rule=rule, literal_to_avoid=literal_to_avoid, anti_pattern=anti_pattern)


def extract_rule_stable(book: Book, adapter: ModelAdapter, n_samples: int = 3) -> RuleSpec | None:
    """extract_rule + majority voting (2026-09-18) -- see slot_identifier.
    identify_slot_stable / stabilizer.vote_for_result for why. Default entry
    point for callers; extract_rule remains the single-sample primitive."""
    return vote_for_result(
        identify_fn=lambda: extract_rule(book, adapter),
        key_fn=lambda rule_spec: rule_spec.literal_to_avoid,
        n_samples=n_samples,
    )


@dataclass
class ContrastingScenarios:
    task_a: Task
    task_b: Task
    direction: str


def _parse_scenario_task(data: dict, book: Book, label: str) -> Task | None:
    required = {"problem_id", "fn_name", "buggy_source", "test_source"}
    if not required.issubset(data) or not isinstance(data["problem_id"], str):
        return None
    if not data["buggy_source"].strip() or not data["test_source"].strip():
        return None
    return Task(
        task_id=f"{book.pattern_id}__{data['problem_id']}__rulegen_{label}",
        pattern_id=book.pattern_id, problem_id=data["problem_id"], fn_name=data["fn_name"],
        buggy_source=data["buggy_source"], test_source=data["test_source"], split="RULE_GENERALIZATION",
        problem_tags=list(book.problem_tags), capability_tags=list(book.capability_tags),
    )


def generate_contrasting_scenarios(book: Book, rule: RuleSpec, adapter: ModelAdapter, max_attempts: int = 3) -> ContrastingScenarios | None:
    """Self-checked like probe_generator.py's generate_probe: both buggy_sources
    must actually FAIL their own test_source (verified by really running them),
    retried up to max_attempts, never accepted on the model's own say-so.

    2026-09-18: each failed attempt's specific reason is fed back into the
    next attempt (same fix as method_trap.py's generate_trap_scenario, same
    motivating bottleneck -- a blind retry with no diagnostic repeats the
    same mistake)."""
    feedback: str | None = None
    for _ in range(max_attempts):
        prompt = (
            f"Rule: {rule.rule}\nPattern: {book.pattern_id!r}\n"
            f"(Do not mention this literal verbatim in either situation: {rule.literal_to_avoid!r})"
        )
        if feedback:
            prompt += f"\n\nPrevious attempt failed: {feedback}"
        completion = adapter.complete(prompt=prompt, system=_SCENARIO_SYSTEM_PROMPT, max_tokens=4096)
        match = _JSON_RE.search(completion.text)
        if not match:
            feedback = "your response did not contain a parseable JSON object -- return ONLY the JSON object, no prose, no markdown fences."
            continue
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            feedback = "your JSON object did not parse -- check for unescaped quotes/newlines inside the source-code string fields."
            continue
        task_a = _parse_scenario_task(data.get("scenario_a") or {}, book, "a")
        task_b = _parse_scenario_task(data.get("scenario_b") or {}, book, "b")
        direction = str(data.get("direction") or "").strip()
        if task_a is None or task_b is None or not direction:
            feedback = "scenario_a/scenario_b/direction were missing or malformed -- each scenario needs problem_id, fn_name, buggy_source, and test_source, all non-empty."
            continue
        result_a = run_tests(task_a.buggy_source, task_a.test_source)
        result_b = run_tests(task_b.buggy_source, task_b.test_source)
        if result_a.passed or result_b.passed:
            # Una delle due "buggy" versioni passa già i propri test -- non
            # misura nulla, stesso motivo di scarto di probe_generator.py.
            which = "scenario_a" if result_a.passed else "scenario_b"
            feedback = f"{which}'s buggy_source PASSED its own test_source -- it needs to be genuinely broken. Make the bug more clearly present."
            continue
        return ContrastingScenarios(task_a=task_a, task_b=task_b, direction=direction)
    return None


@dataclass
class GeneralizationResult:
    pattern_id: str
    book_id: str
    rule: str
    anti_pattern: str
    literal_to_avoid: str
    direction: str
    code_a: str
    code_b: str
    anti_pattern_triggered: bool  # controllo deterministico, nessuna chiamata LLM
    generalizes: bool | None  # None se il giudice non ha prodotto un verdetto leggibile
    judge_reason: str
    verdict: str  # etichetta finale leggibile: GENERALIZES | ANTI_PATTERN | DOES_NOT_GENERALIZE | INCONCLUSIVE


def run_rule_generalization_check(
    experiment_id: str,
    book: Book,
    rule: RuleSpec,
    scenarios: ContrastingScenarios,
    test_adapter: ModelAdapter,
    judge_adapter: ModelAdapter,
) -> GeneralizationResult:
    package = SkillPackage(books=[book], coverage="FULL")

    prompt_a = build_prompt(scenarios.task_a, package)
    completion_a = test_adapter.complete(prompt=prompt_a, system=SYSTEM_PROMPT, max_tokens=4096)
    code_a = extract_code(completion_a.text)

    prompt_b = build_prompt(scenarios.task_b, package)
    completion_b = test_adapter.complete(prompt=prompt_b, system=SYSTEM_PROMPT, max_tokens=4096)
    code_b = extract_code(completion_b.text)

    # Controllo deterministico, nessun giudice LLM: il letterale esatto
    # dell'esempio compare in una delle due risposte? Stesso spirito del
    # controllo verbatim di identify_slot -- una presenza di testo, non
    # un'opinione. Non prova la sua ASSENZA di per se' un rischio (potrebbe
    # essere una coincidenza legittima), ma la sua PRESENZA in un contesto
    # deliberatamente diverso e' un segnale forte e verificabile.
    anti_pattern_triggered = rule.literal_to_avoid in code_a or rule.literal_to_avoid in code_b

    judge_prompt = (
        f"Rule: {rule.rule}\n"
        f"Situation A: {scenarios.task_a.problem_id}\nSituation B: {scenarios.task_b.problem_id}\n"
        f"Expected direction: {scenarios.direction}\n\n"
        f"Response A:\n{code_a}\n\nResponse B:\n{code_b}"
    )
    judged = judge_adapter.complete(prompt=judge_prompt, system=_COMPARE_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
    lines = [l.strip() for l in judged.text.strip().splitlines() if l.strip()]
    label = lines[0].upper() if lines else ""
    judge_reason = lines[1] if len(lines) > 1 else ""
    if label == "GENERALIZES":
        generalizes = True
    elif label == "DOES_NOT_GENERALIZE":
        generalizes = False
    else:
        generalizes = None
        judge_reason = f"[verdetto non leggibile: {label!r}] {judged.text.strip()}"

    if anti_pattern_triggered:
        verdict = "ANTI_PATTERN"
    elif generalizes is None:
        verdict = "INCONCLUSIVE"
    elif generalizes:
        verdict = "GENERALIZES"
    else:
        verdict = "DOES_NOT_GENERALIZE"

    result = GeneralizationResult(
        pattern_id=book.pattern_id, book_id=book.id, rule=rule.rule, anti_pattern=rule.anti_pattern,
        literal_to_avoid=rule.literal_to_avoid, direction=scenarios.direction, code_a=code_a, code_b=code_b,
        anti_pattern_triggered=anti_pattern_triggered, generalizes=generalizes, judge_reason=judge_reason, verdict=verdict,
    )
    emit(
        experiment_id, scenarios.task_a.task_id, "RULE_GENERALIZATION", "rule_generalization:check",
        "RULE_GENERALIZATION_CHECK", reason="rule_generalization",
        book_id=book.id, literal_to_avoid=rule.literal_to_avoid, anti_pattern_triggered=anti_pattern_triggered,
        generalizes=generalizes, verdict=verdict, task_b_id=scenarios.task_b.task_id,
    )
    return result
