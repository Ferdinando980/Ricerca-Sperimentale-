"""Generic stabilizer for any single-shot LLM classification in this package
(2026-09-17, user-requested generalization). The instability this project has
repeatedly hit is not random noise -- it is that a holistic yes/no judgment
over a whole text ('does this skill have a risky slot?', 'is this method
conditioned?', 'is this candidate presented as definitive?') is exactly the
kind of abstract call an LLM makes inconsistently, the same failure class
substitution_ablation.py's own trap scenarios exist to detect in the model
UNDER TEST -- it turns out the Expert-role classification calls in this same
package are not immune to it either.

The fix is NOT a hardcoded keyword list (would not generalize across skills
or languages) and NOT majority-vote-and-hope (smooths symptoms, does not
explain them). It is teaching the model the move a careful human reviewer
makes: after reaching a conclusion, argue AGAINST it and see if you can
produce REAL, VERBATIM evidence from the same text. A quote that genuinely
appears in the text is real counter-evidence -- the original claim does not
survive. A fabricated or absent quote means the claim survived an adversarial
check it could have failed.

Concrete case this caught live: identify_slot_decomposed accepted
'collections.defaultdict' as a definitive slot in key_error_missing_dict_
check's text, even though the text introduces it as 'Alternative: Use
collections.defaultdict' -- one of three offered approaches. Asked to argue
against its own 'definitive' classification, the model correctly quoted
'Alternative' back verbatim in 5/5 repeated runs, and the stabilized result
went from unstable (0/5, 4/5 across two prior runs) to a clean 5/5 rejection
-- with no keyword list written by hand.

Every fixed-shape judge call here passes thinking_budget=0 (2026-09-18, see
adapters/base.py's docstring): these are narrow verdicts, not open-ended
generation, and a reasoning model's variable, topic-dependent thinking-token
spend can otherwise silently truncate the JSON answer for one specific input
and not another, which looks exactly like the instability this module exists
to fix but is actually a separate, token-budget-shaped bug."""

import json
import re
from collections import Counter
from typing import Callable, TypeVar

from ..adapters.base import ModelAdapter

T = TypeVar("T")

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_COUNTER_EVIDENCE_SYSTEM_PROMPT = (
    "You previously produced a classification about one specific detail of a "
    "text. Now act as a skeptic reviewing your own conclusion: try to find the "
    "STRONGEST evidence IN THE SAME TEXT that would argue AGAINST it. Quote it "
    "verbatim, character for character, ONLY if such evidence genuinely exists "
    "in the text -- do not paraphrase, do not invent something plausible-"
    "sounding. If you honestly cannot find any real counter-evidence, say so. "
    'Return ONLY JSON: {"counter_evidence": "exact quote" or null}.'
)


_CONTENT_PRESERVATION_SYSTEM_PROMPT = (
    "Compare an original procedure to a compressed rewrite of it. Check ONLY "
    "one thing: does the compressed version OMIT any actionable step, "
    "diagnostic detail, or fact that was present in the original? Shortening, "
    "rewording, reordering, and even adding NEW material are all fine and do "
    "not count as a problem -- only silently dropping something that was "
    "there is. Answer on the first line with exactly one word: PRESERVED (all "
    "original content is present, in any form) or LOST_CONTENT (something "
    "from the original is missing). On the next line, name the specific "
    "step/detail that is missing (or 'none' if PRESERVED)."
)


def check_content_preserved(original_text: str, rewritten_text: str, adapter: ModelAdapter) -> dict:
    """Moved here 2026-09-17, VERBATIM, from librarian/optimizer.py (built
    2026-09-09 for the compression pipeline only) so every rewrite pipeline in
    this project can share ONE implementation instead of drifting into copies
    -- text deliberately kept byte-for-byte identical so optimizer.py's own,
    already-validated accept/reject behavior does not shift from this move.

    skill_repair.py and method_repair.py did NOT have this gate before, and it
    would have caught a real regression live: wrong_string_case_comparison's
    substitution-repair pass (v3 -> v4) replaced the concrete '.casefold()'
    example with an abstract '<derived_case_normalization_method>' placeholder.
    The rewrite passed both existing gates (tracking dropped enough, real
    holdout task still solved) but is arguably worse for the common, correct
    case -- adding this gate is what should catch that automatically, not a
    human eyeballing the diff after the fact. See
    validate_content_preservation_on_v3_v4.py for whether the EXISTING prompt,
    unmodified, already catches it before considering a stricter variant.

    `UNPARSEABLE` is a real, distinct outcome, never coerced into PRESERVED or
    LOST_CONTENT -- callers must treat it as fail-closed (do not accept)."""
    prompt = f"Original procedure:\n{original_text.strip()}\n\nCompressed rewrite:\n{rewritten_text.strip()}"
    result = adapter.complete(prompt=prompt, system=_CONTENT_PRESERVATION_SYSTEM_PROMPT, max_tokens=200, thinking_budget=0)
    lines = [l.strip() for l in result.text.strip().splitlines() if l.strip()]
    label = lines[0].upper() if lines else ""
    reasoning = lines[1] if len(lines) > 1 else ""
    if label not in {"PRESERVED", "LOST_CONTENT"}:
        reasoning = f"[unparseable label {label!r}] {result.text.strip()}"
        label = "UNPARSEABLE"
    return {"label": label, "reasoning": reasoning}


_CONCRETENESS_PRESERVATION_SYSTEM_PROMPT = (
    "Compare an original procedure to a rewrite of it. Check ONLY one thing: "
    "does the rewrite replace any CONCRETE example, named method, specific "
    "default, or specific literal from the original with a VAGUER "
    "abstraction or an instruction to 'derive the right one' -- even if the "
    "general step is still gestured at? Shortening, rewording, reordering, "
    "and adding NEW concrete material are all fine. Only making something "
    "LESS concrete/actionable than it was counts as a problem. Answer on the "
    "first line with exactly one word: PRESERVED (everything that was "
    "concrete in the original is still just as concrete) or LOST_CONCRETENESS "
    "(something concrete was replaced by a vaguer abstraction). On the next "
    "line, name the specific detail that was made vaguer (or 'none' if "
    "PRESERVED)."
)


def check_concreteness_preserved(original_text: str, rewritten_text: str, adapter: ModelAdapter) -> dict:
    """Stricter sibling of check_content_preserved, for the REPAIR pipelines
    only (skill_repair.py, method_repair.py) -- kept SEPARATE from the
    original rather than changing its wording, after testing live
    (2026-09-17) that the original, unmodified prompt says PRESERVED (3/3
    repeated runs) for wrong_string_case_comparison's v3->v4 rewrite, which
    replaced the concrete '.casefold()' with an abstract
    '<derived_case_normalization_method>' placeholder -- the ORIGINAL
    question ('was any actionable step omitted?') is satisfied because the
    step is still gestured at, just less concrete; it does not ask the
    narrower, different question this function asks instead. Do not merge
    this back into check_content_preserved without re-validating against
    optimizer.py's own historical compression results first -- that pipeline
    depends on the original's specific tolerance for legitimate
    generalization during compression, which this stricter check would very
    likely reject more often than intended."""
    prompt = f"Original procedure:\n{original_text.strip()}\n\nRewrite:\n{rewritten_text.strip()}"
    result = adapter.complete(prompt=prompt, system=_CONCRETENESS_PRESERVATION_SYSTEM_PROMPT, max_tokens=200, thinking_budget=0)
    lines = [l.strip() for l in result.text.strip().splitlines() if l.strip()]
    label = lines[0].upper() if lines else ""
    reasoning = lines[1] if len(lines) > 1 else ""
    if label not in {"PRESERVED", "LOST_CONCRETENESS"}:
        reasoning = f"[unparseable label {label!r}] {result.text.strip()}"
        label = "UNPARSEABLE"
    return {"label": label, "reasoning": reasoning}


def vote_for_result(identify_fn: Callable[[], "T | None"], key_fn: Callable[["T"], str], n_samples: int = 3) -> "T | None":
    """Generic majority-vote stabilizer (2026-09-18) -- self-consistency
    (Wang et al. 2022) applied to the IDENTIFICATION step itself, not just
    the task under test. Real, repeated instability this fixes: `identify_
    slot_decomposed`/`extract_rule`/`extract_method` each ask a holistic
    'does this exist?' question over a whole text, and that single call has
    flipped its answer across separate runs on the EXACT same input all
    session (key_error_missing_dict_check: 3 different verdicts in 3 runs
    before the adversarial stabilizer; integer_division_truncation: found a
    slot most of the day, then found none on a fresh call while testing the
    Inspector loop). Decomposition and the adversarial check reduce this but
    do not eliminate it -- voting is the complementary fix for what's left,
    not a replacement for either.

    identify_fn is called n_samples times, each a fresh, independent
    invocation (no shared state between calls). None means 'not found' for
    that sample. Ties, and 'not found' winning outright, both resolve to
    None -- fail closed, consistent with every other check in this module:
    a slot/rule/method only counts as real when it's the CLEAR majority
    finding, not a coin flip. Among samples that DID find something, key_fn
    extracts a comparable identity (e.g. the literal value found) so the
    modal (most common) finding wins, breaking ties among slightly
    different phrasings of the same underlying finding is NOT attempted --
    a genuine disagreement on WHICH value, not just whether one exists, is
    itself real instability worth surfacing, not silently averaging over."""
    results = [identify_fn() for _ in range(n_samples)]
    found = [r for r in results if r is not None]
    not_found_count = len(results) - len(found)
    if len(found) <= not_found_count:
        return None
    keys = [key_fn(r) for r in found]
    mode_key, _ = Counter(keys).most_common(1)[0]
    return next(r for r, k in zip(found, keys) if k == mode_key)


def survives_adversarial_check(text: str, subject: str, claim_summary: str, adapter: ModelAdapter) -> bool:
    """Generic across the package -- text/subject/claim_summary carry no
    assumption about what kind of classification produced the claim (a slot,
    a method condition, a rule, anything with the same shape). Returns False
    (claim does NOT survive) only when the model produces a quote that
    verifiably appears in the text -- real, checkable counter-evidence. A
    fabricated or absent quote means the claim survived (True); an unreadable
    response fails OPEN (True) rather than silently rejecting every candidate
    on a parsing hiccup -- this is a stabilizer, not a new veto with its own
    failure mode to debug."""
    prompt = f"Text:\n\n{text}\n\nSpecific detail: {subject!r}\nYour classification: {claim_summary}"
    completion = adapter.complete(prompt=prompt, system=_COUNTER_EVIDENCE_SYSTEM_PROMPT, max_tokens=512, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return True
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return True
    counter = data.get("counter_evidence")
    if not isinstance(counter, str) or not counter.strip():
        return True
    return counter not in text
