from ..adapters.base import ModelAdapter
from ..agents.worker import MAX_OUTPUT_TOKENS, SYSTEM_PROMPT, build_prompt, extract_code
from ..cheater import solution_bank
from ..domain.verifier import run_tests
from ..librarian import librarian
from ..librarian.context_budget import enforce_budget
from ..models import SkillPackage, Task
from ..verification import detective
from .events import emit
from .experiment_log import LogRecord, append, new_record


def run_quest(
    task: Task,
    experiment_id: str,
    config_name: str,
    adapter: ModelAdapter,
    use_librarian: bool = False,
    use_cheater: bool = False,
    use_detective: bool = False,
) -> LogRecord:
    """use_detective (2026-09-18, opt-in, default False -- does not change
    A/B/F/C behavior at all): after Librarian retrieval, if the retrieved
    book has a multi-case rule, runs detective.investigate_cached (Expert-
    driven, on-disk cached per (book, task) so repeated validation runs
    don't re-invoke the Expert for the same pair) and, if it resolves,
    appends the hypothesis as an explicit hint in the Worker's prompt --
    same annotation role as skill_conflict.py's COMPOUND note. Deliberately
    a NEW opt-in config (e.g. "FD"), never mutates what F itself means, so
    F's own historical numbers stay comparable."""
    npc = f"{config_name}:npc"
    ev = emit(
        experiment_id, task.task_id, config_name, npc, "QUEST_CREATED",
        reason="assign_quest", split=task.split, pattern_id=task.pattern_id,
    )

    ev = emit(
        experiment_id, task.task_id, config_name, npc, "NPC_ASSIGNED",
        parent_event_id=ev.event_id, reason="fixed_experiment_design",
        provider=adapter.PROVIDER, model=getattr(adapter, "model", None) or getattr(adapter, "model_name", "?"),
        use_librarian=use_librarian, use_cheater=use_cheater,
    )

    # Real token cost of retrieval, broken down: the base prompt (task alone) vs
    # what the retrieved skill context adds on top of it -- answers "who's using
    # all those extra tokens" instead of only seeing one combined number.
    base_prompt = build_prompt(task, None)
    base_tokens = adapter.count_input_tokens(base_prompt, system=SYSTEM_PROMPT)

    skill_package = None
    if use_librarian or use_cheater:
        source = "librarian" if use_librarian else "cheater"
        ev = emit(
            experiment_id, task.task_id, config_name, f"{config_name}:{source}", "RETRIEVAL_STARTED",
            parent_event_id=ev.event_id, reason="route_skill",
        )
        skill_package = librarian.route(task) if use_librarian else solution_bank.route(task)

        model_id = getattr(adapter, "model", None) or getattr(adapter, "model_name", "?")
        skill_package, base_over_budget, dropped_book_ids = enforce_budget(
            base_tokens=base_tokens,
            skill_package=skill_package,
            adapter=adapter,
            system=SYSTEM_PROMPT,
            build_prompt_with_books=lambda books: build_prompt(task, SkillPackage(books=books)),
            model=model_id,
        )
        if base_over_budget:
            ev = emit(
                experiment_id, task.task_id, config_name, f"{config_name}:{source}",
                "CONTEXT_BUDGET_BASE_EXCEEDED",
                parent_event_id=ev.event_id, reason="base_prompt_too_large",
                base_prompt_tokens=base_tokens, model=model_id,
                dropped_book_ids=dropped_book_ids,
            )
        elif dropped_book_ids:
            ev = emit(
                experiment_id, task.task_id, config_name, f"{config_name}:{source}",
                "CONTEXT_BUDGET_BOOKS_DROPPED",
                parent_event_id=ev.event_id, reason="over_context_budget",
                dropped_book_ids=dropped_book_ids, model=model_id,
            )

        detective_hint = None
        if use_detective and skill_package.books:
            # Small (adapter), NOT Expert -- 2026-09-18, corrected: the whole
            # point of this project is a Small-model ecosystem approaching
            # Expert performance WITHOUT calling Expert at runtime. Expert's
            # actual job already happened when Detective's own prompts were
            # authored (the generic index-cases/ask-a-distinguishing-
            # question/answer-with-evidence method IS "how Claude would do
            # it", already baked into detective.py's system prompts) --
            # running a live Expert call here would just smuggle Expert back
            # into F+Detective's runtime, defeating the comparison against F
            # the same way the Cheater config exists to catch. Verified
            # live: Gemma alone correctly resolves both real cases here once
            # the question-generation bug (see detective.py) was fixed.
            detective_adapter = adapter
            for book in skill_package.books:
                hyp = detective.investigate_cached(book, task, detective_adapter)
                if hyp is not None and hyp.status == "RESOLVED":
                    detective_hint = (
                        f"For this specific task, the applicable case of the skill's rule is: {hyp.supported_case!r}."
                        + (f' Evidence: "{hyp.evidence_quote}".' if hyp.evidence_quote else " (determined by ruling out the other cases).")
                    )
                    break  # un solo indizio basta -- generico, non legato a un libro specifico

        prompt = build_prompt(task, skill_package)
        if detective_hint:
            prompt = prompt.replace(
                "Return the corrected function.",
                f"Hint for this specific task (from a separate investigation of which case of the skill's "
                f"rule applies here): {detective_hint}\n\nReturn the corrected function.",
            )
        prompt_tokens = adapter.count_input_tokens(prompt, system=SYSTEM_PROMPT)
        ev = emit(
            experiment_id, task.task_id, config_name, f"{config_name}:{source}", "RETRIEVAL_RESULT",
            parent_event_id=ev.event_id, reason="route_skill",
            coverage=skill_package.coverage,
            skill_ids=[book.id for book in skill_package.books],
            detective_hint_used=detective_hint is not None,
            base_prompt_tokens=base_tokens,
            skill_context_tokens=max(0, prompt_tokens - base_tokens),
            # Deterministic tag-overlap / solution-lookup retrieval makes no
            # model call of its own -- the skill_context_tokens above are
            # what it adds to the NEXT call (the worker's), not a cost the
            # retrieval step itself incurs.
            input_tokens=0, output_tokens=0,
        )
    else:
        prompt = base_prompt
        prompt_tokens = base_tokens

    ev = emit(
        experiment_id, task.task_id, config_name, f"{config_name}:worker", "PROMPT_BUILT",
        parent_event_id=ev.event_id, reason="build_prompt",
        prompt_chars=len(prompt), input_tokens_estimate=prompt_tokens,
        base_prompt_tokens=base_tokens,
        skill_context_tokens=max(0, prompt_tokens - base_tokens),
    )

    ev = emit(
        experiment_id, task.task_id, config_name, f"{config_name}:worker", "MODEL_CALL_STARTED",
        parent_event_id=ev.event_id, reason="solve_task",
        provider=adapter.PROVIDER, model=getattr(adapter, "model", None) or getattr(adapter, "model_name", "?"),
    )
    completion = adapter.complete(prompt=prompt, system=SYSTEM_PROMPT, max_tokens=MAX_OUTPUT_TOKENS)
    candidate_source = extract_code(completion.text)

    ev = emit(
        experiment_id, task.task_id, config_name, f"{config_name}:worker", "MODEL_CALL_FINISHED",
        parent_event_id=ev.event_id, reason="solve_task",
        model=completion.model, provider=completion.provider,
        input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
        cached_input_tokens=completion.cached_input_tokens,
        reasoning_output_tokens=completion.reasoning_output_tokens,
        cost_usd=completion.cost_usd, latency_ms=completion.latency_ms,
        retries=completion.retries, paused_seconds=completion.paused_seconds,
    )

    verification = run_tests(candidate_source, task.test_source)
    ev = emit(
        experiment_id, task.task_id, config_name, f"{config_name}:checker", "VERIFICATION",
        parent_event_id=ev.event_id, reason="verify_fix",
        passed=verification.passed, tests_total=verification.tests_total,
        tests_passed=verification.tests_passed,
        # pytest subprocess makes no model call -- real cost here is 0.
        input_tokens=0, output_tokens=0,
    )

    record = new_record(
        experiment_id=experiment_id,
        task_id=task.task_id,
        split=task.split,
        config_name=config_name,
        completion=completion,
        passed=verification.passed,
        coverage=skill_package.coverage if skill_package else "N/A",
    )
    append(record)
    emit(
        experiment_id, task.task_id, config_name, npc, "QUEST_COMPLETED",
        parent_event_id=ev.event_id, reason="log_result", passed=verification.passed,
    )
    return record
