"""Generalized causal-ablation engine for detecting mechanical substitution in
a skill (Book) -- reusable machinery for the exact methodology validated by
hand in experiment/canary.py for floating_point_equality (2026-08-19):
manipulate a designated literal slot in the skill's own procedure_text,
run the SAME probe tasks through the tested model once per variant, and
measure whether the model's output tracks the manipulated slot in lockstep
(mechanical substitution) instead of deriving an answer from the task's own
content (real application).

What this does NOT automate (deliberately -- see the plan this implements,
C:\\Users\\grego\\.claude\\plans\\ethereal-herding-blossom.md): identifying
WHICH slot in an arbitrary skill's text is worth testing, and extracting the
corresponding value from a model's free-text/code output. Both are supplied
by the caller per skill (`slot_variants`, `extract_value`) -- auto-inferring
them for an arbitrary skill is real, harder future work (Workstream A point
2 in the plan), not faked here to look more automatic than it actually is.

Every call is logged via experiment/events.py -- new event types
(ABLATION_BASELINE_CALL, ABLATION_VARIANT_CALL), additive only. Cognitive
City's report code does not read these event types and is untouched."""

from dataclasses import asdict, dataclass, field
from typing import Callable

from ..adapters.base import ModelAdapter
from ..agents.worker import SYSTEM_PROMPT, build_prompt, extract_code
from ..experiment.events import emit
from ..models import Book, SkillPackage, Task

_CONFIG_NAME = "ABLATION"

# A value extractor takes the model's generated code (or free text, for
# non-code skills) and returns the slot's value as it appears in the output,
# or None if the output doesn't contain a recognizable value at all -- the
# caller decides what "the slot's value" means for a given skill (a number,
# a specific phrase, ...).
ValueExtractor = Callable[[str], "str | None"]


@dataclass
class AblationResult:
    pattern_id: str
    book_id: str
    slot_name: str
    # variant_label -> {task_id: extracted_value_or_None}, one entry per rep
    # collapsed into a list so repeated reps on the same task are visible.
    per_variant: dict[str, dict[str, list[str | None]]] = field(default_factory=dict)
    baseline: dict[str, str | None] = field(default_factory=dict)  # task_id -> value with NO skill at all
    tracked_lockstep: int = 0
    total_checks: int = 0

    @property
    def tracking_ratio(self) -> float:
        """Fraction of (variant, task, rep) checks where the model's output
        matched the MANIPULATED variant exactly -- the same number canary.py
        reported as "12/12" for floating_point_equality's tier-c. High ==
        mechanical substitution; low == the model isn't just echoing the
        slot regardless of what it says."""
        return self.tracked_lockstep / self.total_checks if self.total_checks else 0.0

    def selectivity_ok(self, unrelated_tasks: set[str]) -> bool | None:
        """Mirrors canary.py's ablation-1 selectivity check: for tasks the
        slot should NOT apply to, the extracted value should be unaffected
        by which variant was injected (all variants -> the same answer as
        baseline). Returns None if no unrelated tasks were tested."""
        relevant = {tid: vals for variant in self.per_variant.values() for tid, vals in variant.items() if tid in unrelated_tasks}
        if not relevant:
            return None
        for task_id in unrelated_tasks:
            seen = {v for variant in self.per_variant.values() for v in variant.get(task_id, [])}
            if len(seen) > 1:
                return False
        return True


def run_substitution_ablation(
    experiment_id: str,
    book: Book,
    slot_name: str,
    slot_variants: dict[str, str],  # variant label (== expected tracked value) -> replacement procedure_text
    tracked_tasks: list[Task],  # tasks the slot SHOULD apply to (used for lockstep scoring)
    extract_value: ValueExtractor,
    adapter: ModelAdapter,
    reps: int = 1,
    unrelated_tasks: list[Task] | None = None,  # optional selectivity check, like canary.py's tier-b probe
) -> AblationResult:
    """Runs the manipulation test and returns the real result -- never
    assumes a pipeline that "should" detect substitution actually does;
    reproducing this on floating_point_equality's known 12/12 finding is the
    validation milestone before trusting this on any untested skill (see the
    plan)."""
    result = AblationResult(pattern_id=book.pattern_id, book_id=book.id, slot_name=slot_name)

    # Baseline: bare model, no skill at all -- same role as canary.py's
    # "unaided Expert" check (here: unaided Small, since Small is the model
    # under test in this whole investigation). Tells us what an
    # independently-produced answer looks like, so we can tell "correctly
    # ignoring an inapplicable variant" apart from "not using the skill at
    # all" later.
    for task in tracked_tasks + (unrelated_tasks or []):
        prompt = build_prompt(task, None)
        completion = adapter.complete(prompt=prompt, system=SYSTEM_PROMPT, max_tokens=4096)
        code = extract_code(completion.text)
        value = extract_value(code)
        result.baseline[task.task_id] = value
        emit(
            experiment_id, task.task_id, _CONFIG_NAME, "ablation:baseline",
            "ABLATION_BASELINE_CALL", reason="substitution_ablation",
            book_id=book.id, slot_name=slot_name, extracted_value=value,
            # Costo/token reali del worker (Gemma) su questa chiamata -- NON
            # include il costo della chiamata giudice dentro extract_value,
            # che e' un secondo, separato modello (Expert) invisibile a questa
            # funzione: limite noto, non nascosto (vedi verification/recap.py).
            provider=completion.provider, model=completion.model,
            input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd,
        )

    for variant_label, variant_text in slot_variants.items():
        variant_book = Book(**{**asdict(book), "procedure_text": variant_text})
        package = SkillPackage(books=[variant_book], coverage="FULL")
        result.per_variant[variant_label] = {}
        for task in tracked_tasks + (unrelated_tasks or []):
            values: list[str | None] = []
            for rep in range(reps):
                prompt = build_prompt(task, package)
                completion = adapter.complete(prompt=prompt, system=SYSTEM_PROMPT, max_tokens=4096)
                code = extract_code(completion.text)
                extracted = extract_value(code)
                values.append(extracted)
                is_tracked_task = task in tracked_tasks
                if is_tracked_task:
                    result.total_checks += 1
                    if extracted is not None and extracted == variant_label:
                        result.tracked_lockstep += 1
                emit(
                    experiment_id, task.task_id, _CONFIG_NAME, "ablation:variant",
                    "ABLATION_VARIANT_CALL", reason="substitution_ablation",
                    book_id=book.id, slot_name=slot_name, variant=variant_label,
                    rep=rep, extracted_value=extracted,
                    matches_variant=(extracted == variant_label) if is_tracked_task else None,
                    is_tracked_task=is_tracked_task,
                    provider=completion.provider, model=completion.model,
                    input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
                    cost_usd=completion.cost_usd,
                )
            result.per_variant[variant_label][task.task_id] = values

    return result
