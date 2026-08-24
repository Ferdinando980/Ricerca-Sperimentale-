"""Hard ceiling on how much context one quest's prompt may consume -- independent
of the Librarian's relevance scoring. librarian.route() (and solution_bank.route())
only ever see the skills they found; they have no idea how big the REST of the
prompt (base instructions + the buggy function itself) already is. That's why this
lives where the final prompt is assembled (quest_runner.py calls enforce_budget()),
not inside route() itself -- the Librarian keeps deciding what's relevant, the
assembler decides what actually fits.

Two checks, kept deliberately separate rather than one combined token sum:

  1. Does base_prompt (task + instructions, no skills) already exceed the budget
     on its own? That's a base-prompt problem -- nothing to do with skills, and
     conflating it with step 2 would make "too many skills" the reported cause of
     a problem that lives elsewhere.
  2. Only if the base fits: how many of the retrieved Books fit in what's left?

When over budget, whole Books are dropped, never truncated mid-text. A Book's
procedure_text is an ordered set of steps where a later step can qualify or
correct an earlier one (confirmed by the 2026-08-19 compression ablation, where
dropping the final caveat line changed measured accuracy) -- cutting at an
arbitrary token boundary risks keeping an instruction without the qualifier that
follows it, which is worse than not injecting the Book at all.

librarian.route() already returns SkillPackage.books ordered most-relevant-first
(highest tag-overlap first, see librarian.py:79). Dropping starts from the LEAST
relevant book, i.e. from wherever a book stops fitting onward -- a kept prefix,
dropped suffix, not a bin-packing optimization. This is deliberately predictable
over "squeeze in one more small book further down the list": knowing exactly
which books get dropped, and why, matters more here than maximizing how many fit.
"""

from collections.abc import Callable

from ..adapters.base import ModelAdapter
from ..models import Book, SkillPackage

# Declared context window per model, tokens.
#
# Claude entries: claude-api skill, cached 2026-06-24 -- Opus 5/Sonnet 5 are
# 1M, Haiku 4.5 is 200K. This project never actually calls a Claude model in
# the real (non-mock) run today (EXPERT_PROVIDER/SMALL_PROVIDER=gemini in
# .env, see providers.py) -- these entries are correct but currently inert.
#
# Gemini entries: NOT covered by any skill in this project (same gap noted in
# adapters/gemini_adapter.py) -- verified instead via WebFetch against the
# live official docs (ai.google.dev/gemini-api/docs/models/<id>) on
# 2026-08-21, input token limit field, exact figures. This matters because
# Gemini is what this codebase actually calls (EXPERT_GEMINI_MODEL=
# gemini-3.7-flash, SMALL_GEMINI_MODEL=gemini-3.1-flash-lite as of this
# writing, see .env / adapters/factory.py's per-role override) -- an
# unverified number here would have been a real, not theoretical, gap: this
# table's first version guessed at "gemini-3.6-flash"/"gemini-3.5-flash-lite"
# from a stale memory note and got the Small model's id outright wrong (it
# was never gemini-3.5-flash-lite), which would have silently fallen through
# to FALLBACK_CONTEXT_WINDOW_TOKENS below on every real run instead of using
# a real number -- caught and fixed same day before any real run relied on it.
#
# gpt-4.1: still unverified (OpenAI has no skill in this project either, and
# .env's OPENAI_MODEL is an inactive optional override today) -- re-verify
# before OpenAI is ever made the active provider for a role.
#
# Keyed by the exact model id used in CLAUDE_MODEL/EXPERT_GEMINI_MODEL/
# SMALL_GEMINI_MODEL/OPENAI_MODEL -- add a row (and verify it the same way)
# whenever a new model id gets pinned in .env. Unknown ids fall back to
# FALLBACK_CONTEXT_WINDOW_TOKENS.
CONTEXT_WINDOW_TOKENS: dict[str, int] = {
    "claude-opus-5": 1_000_000,
    "claude-sonnet-5": 1_000_000,
    "claude-haiku-4-5": 200_000,
    "gemini-3.7-flash": 1_048_576,  # verified 2026-08-21, ai.google.dev
    "gemini-3.6-flash": 1_048_576,  # verified 2026-08-21, ai.google.dev
    "gemini-3.1-flash-lite": 1_048_576,  # verified 2026-08-21, ai.google.dev
    "gpt-4.1": 1_047_576,  # unverified -- OpenAI not covered by a skill here
    "mock-model": 1_000_000,
}
# Deliberately conservative for any model id not listed above -- an unrecognized
# model getting a small budget (and possibly dropping skills it didn't need to)
# is a cheap, visible failure; getting a budget too large for its real window
# would silently reproduce the truncation bug worker.py's MAX_OUTPUT_TOKENS fix
# already found once (see worker.py's comment on the 1024->4096 change).
# Confirmed the right direction, not just asserted: every real model this
# project can call today (Claude 200K-1M, Gemini 1,048,576, verified above)
# has a window well above this fallback, so hitting it under-budgets rather
# than over-budgets -- an unrecognized model id fails safe (drops more than
# strictly needed), never unsafe (lets a genuinely oversized prompt through).
FALLBACK_CONTEXT_WINDOW_TOKENS = 128_000

# Fraction of the declared window this codebase is willing to fill with INPUT
# (base prompt + skill context). Not derived from any measurement -- a
# deliberately named, commented constant instead of a bare number, same
# convention as optimizer.py's min_avg_tokens/min_uses thresholds. Leaves
# headroom for MAX_OUTPUT_TOKENS (worker.py) plus a safety margin; 0.80 is a
# starting point, not a tuned value -- revisit if a real run ever gets close.
CONTEXT_BUDGET_FRACTION = 0.80


def context_window_for(model: str) -> int:
    return CONTEXT_WINDOW_TOKENS.get(model, FALLBACK_CONTEXT_WINDOW_TOKENS)


def context_budget_for(model: str) -> int:
    return int(context_window_for(model) * CONTEXT_BUDGET_FRACTION)


def enforce_budget(
    base_tokens: int,
    skill_package: SkillPackage,
    adapter: ModelAdapter,
    system: str,
    build_prompt_with_books: Callable[[list[Book]], str],
    model: str,
) -> tuple[SkillPackage, bool, list[str]]:
    """Returns (narrowed_skill_package, base_over_budget, dropped_book_ids).

    base_tokens: real token count of the prompt with NO skills (task +
    instructions only) -- quest_runner.py already computes this for every
    quest regardless of librarian/cheater use.

    build_prompt_with_books: builds the real prompt text for a candidate list
    of books (e.g. `lambda books: build_prompt(task, SkillPackage(books, ""))`)
    so token counts here are measured via adapter.count_input_tokens, not
    estimated -- same real-numbers convention as the rest of the event log.
    """
    budget = context_budget_for(model)

    if base_tokens > budget:
        # Step 1: nothing would fit -- not a skill problem, don't touch skill_package's
        # books beyond reporting them as dropped for the caller's event log.
        return SkillPackage(books=[], coverage="NONE"), True, [b.id for b in skill_package.books]

    if not skill_package.books:
        return skill_package, False, []

    # Step 2: keep a relevance-ordered prefix, drop the suffix from wherever it
    # first stops fitting.
    kept: list[Book] = []
    dropped: list[str] = []
    for i, book in enumerate(skill_package.books):
        candidate_tokens = adapter.count_input_tokens(
            build_prompt_with_books(kept + [book]), system=system
        )
        if candidate_tokens > budget:
            dropped = [b.id for b in skill_package.books[i:]]
            break
        kept.append(book)

    if len(kept) == len(skill_package.books):
        coverage = skill_package.coverage
    elif kept:
        coverage = "PARTIAL"
    else:
        coverage = "NONE"

    return SkillPackage(books=kept, coverage=coverage), False, dropped
