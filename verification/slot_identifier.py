"""Generic detection of a mechanically-substitutable literal slot in a Book's
procedure_text, plus generic extraction of which value a model's generated
code actually used -- the two pieces substitution_ablation.py's own docstring
named as deliberately NOT automated ("real, harder future work... not faked
here to look more automatic than it actually is").

Both pieces are done here by the Expert adapter (generation/judging
infrastructure, not the model under test -- same role split as
probe_generator.py/skill_repair.py), not by a per-skill hand-written regex,
so the pipeline can run over the WHOLE library instead of one hand-authored
skill at a time (see the plan, Workstream A point 6).

Kept honest the same way probe_generator.py is: fail closed on anything
unverifiable rather than trust the model's say-so.
  - identify_slot: the claimed literal must appear VERBATIM in
    procedure_text (a substring check), or the identification is rejected,
    not silently accepted/corrected.
  - the extractor built by make_extractor: the judge's claimed value must
    appear VERBATIM in the generated code it was shown, or it's treated as
    no-match (None) -- a hallucinated "match" that isn't actually in the
    text would silently corrupt the tracking-ratio measurement otherwise.

MANDATORY before trusting this on any skill it hasn't been checked against
before (plan, Workstream A points 2 and 4): validate_slot_identifier_
milestone.py cross-checks this against 4 ALREADY hand-verified cases (not
just floating_point_equality) before library_benchmark.py is trusted on the
rest of the library.

Every classification call here passes thinking_budget=0 (2026-09-18, see
adapters/base.py's own docstring for the concrete bug this fixes: a
reasoning-capable model can spend a variable, topic-dependent number of
invisible thinking tokens even on a narrow yes/no classification, truncating
the actual JSON answer on one specific candidate but not another -- looking
exactly like "the model disagrees on which slot is real" when it is really a
token-budget artifact). These are fixed-shape verdicts, not open-ended
problem solving, so forcing deterministic token usage is strictly a
reliability fix here, unlike a generative call (skill_repair.py's rewrite,
worker.py's task-solving) where thinking is left dynamic on purpose."""

import json
import re
from dataclasses import dataclass
from typing import Callable

from ..adapters.base import ModelAdapter
from .stabilizer import survives_adversarial_check, vote_for_result

_IDENTIFY_SYSTEM_PROMPT = (
    "You inspect a procedure ('skill') written to help an economical language "
    "model avoid a specific bug pattern. Some such procedures illustrate the "
    "rule with ONE concrete literal example value (a number, a threshold, a "
    "specific default, a specific string) that a model could copy verbatim "
    "into an unrelated task instead of deriving the right value for that new "
    "task -- this is a known failure mode (mechanical substitution). Others "
    "describe a discrete choice (which operator, which structural fix) with "
    "no such literal to copy at all. Decide which this is.\n\n"
    "First, in the reasoning field, state which of the two kinds of "
    "procedure this is and why, before deciding.\n\n"
    "Return ONLY a single JSON object, no prose, no markdown fences:\n"
    '- If there IS such a literal: {"reasoning": "one sentence, written '
    'first", "has_slot": true, "slot_name": "short label", "original_value": '
    '"the EXACT literal substring as it appears in the text, character for '
    'character, copyable verbatim", "context_hint": "what this value '
    'represents and where it appears, one sentence", "alt_values": '
    '["plausible alternative value 1", "plausible alternative value 2"]}\n'
    '- If there is no such literal: {"reasoning": "one sentence, written '
    'first", "has_slot": false, "reason": "one sentence"}\n'
    "original_value must be copyable verbatim from the procedure text -- do "
    "not paraphrase, reformat, or round it."
)

_MATCH_SYSTEM_PROMPT = (
    "You inspect a piece of generated Python code and decide which, if any, "
    "of a list of candidate values is used at a specific point described to "
    "you (e.g. a tolerance, a default, a threshold). Two values that are the "
    "SAME number in different notation (e.g. 1e-9 and 0.000000001, or 3.3e-4 "
    "and 0.00033) count as a match -- do not be fooled by formatting. A "
    "genuinely different number, or a value derived without matching any "
    "candidate, does not match.\n\n"
    "First, in the reasoning field, quote the specific part of the code "
    "that computes or uses the value in question, before deciding which "
    "candidate (if any) it matches.\n\n"
    "Return ONLY a single JSON object, no prose, no markdown fences: "
    '{"reasoning": "one sentence, written first", "matched_index": N} where '
    'N is the 0-based index of the matching candidate, or {"reasoning": '
    '"...", "matched_index": null} if none match.'
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

ValueExtractor = Callable[[str], "str | None"]


@dataclass
class SlotCandidate:
    source_label: str  # book.id for a Book, or a short name for a static app prompt
    slot_name: str
    original_value: str
    context_hint: str
    alt_values: list[str]

    def variant_values(self) -> list[str]:
        # original_value first, so it is always available as one of the
        # variants to build_slot_variants (a no-op "variant" == the live
        # text) alongside the genuinely manipulated alternatives.
        return [self.original_value] + list(self.alt_values)


def identify_slot(text: str, source_label: str, adapter: ModelAdapter) -> SlotCandidate | None:
    """text is any procedure/instruction text -- a Book's procedure_text, or
    a static app prompt constant (see static_audit.py, which reuses this
    same function on fixed system-prompt strings, not just Books). Returns
    None both when the model reports no slot exists AND when its answer
    fails the verbatim check -- callers cannot distinguish the two from the
    return value alone by design (both mean "no ablation-testable slot found
    here"); the reason is only for a human reading logs, printed by the
    caller."""
    prompt = f"Procedure/instruction text ({source_label!r}):\n```\n{text}\n```"
    completion = adapter.complete(prompt=prompt, system=_IDENTIFY_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
    match = _JSON_RE.search(completion.text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not data.get("has_slot"):
        return None
    original_value = data.get("original_value")
    if not isinstance(original_value, str) or not original_value.strip():
        return None
    if original_value not in text:
        # Verbatim check fallito -- il modello ha paraprasato invece di
        # citare esattamente. Non tentare di "correggerlo" da soli (sarebbe
        # indovinare quale slot intendesse davvero); trattarlo come nessuno
        # slot trovato, non come un errore da recuperare.
        return None
    alt_values = data.get("alt_values") or []
    alt_values = [v for v in alt_values if isinstance(v, str) and v.strip() and v != original_value]
    if not alt_values:
        return None
    return SlotCandidate(
        source_label=source_label,
        slot_name=str(data.get("slot_name") or "slot"),
        original_value=original_value,
        context_hint=str(data.get("context_hint") or ""),
        alt_values=alt_values[:2],
    )


_EXTRACT_LITERALS_SYSTEM_PROMPT = (
    "List every concrete literal value in this text that appears as part of an "
    "example, default, or illustrative case -- a number, a specific quoted "
    "string, or a specific named method/function call. This is a MECHANICAL "
    "LISTING task, not a judgment call about risk: list every literal-looking "
    "value you find, even ones you are not sure matter.\n\n"
    "Do NOT list a formula, expression, or code template that contains a "
    "variable name (e.g. `abs(a - b) < epsilon` is a reusable template, not a "
    "literal -- `epsilon` is a placeholder, nothing to extract there; but the "
    "number 1e-9 inside `epsilon = 1e-9` IS a literal, extract that). Only "
    "list something a reader could copy-paste as-is into unrelated code -- a "
    "bare number, a bare quoted string, or a bare method name with no "
    "variable in it.\n\n"
    "Return ONLY a JSON array of exact substrings, copied verbatim "
    'character-for-character from the text, e.g. ["1e-9", "casefold()"]. '
    "Empty array [] if none. (This is a mechanical listing task -- no "
    "reasoning field needed, just the list.)"
)

_CLASSIFY_LITERAL_SYSTEM_PROMPT = (
    "You are given a procedure's text and ONE specific literal value that "
    "appears in it. Answer two narrow, concrete questions about THIS SPECIFIC "
    "literal only -- not about the procedure as a whole:\n"
    "1. presented_as_definitive: does the text present this exact value as THE "
    "one to use, with no explicit statement that the real value depends on the "
    "situation/domain? (true/false)\n"
    "2. substitutable: if this literal were replaced with a different value of "
    "the same kind, would the surrounding sentence still read as a complete, "
    "coherent instruction (i.e. nothing else in the sentence depends on this "
    "exact value grammatically)? (true/false)\n"
    "Only if BOTH are true, also suggest: a short slot_name, a one-sentence "
    "context_hint (what this value represents), and 2 plausible alt_values of "
    "the same kind.\n\n"
    "First, in the reasoning field, quote the specific sentence around this "
    "literal and state plainly what it says about the two questions above, "
    "before answering them.\n\n"
    'Return ONLY JSON: {"reasoning": "one or two sentences, written first", '
    '"presented_as_definitive": true|false, "substitutable": true|false, '
    '"slot_name": "...", "context_hint": "...", "alt_values": ["...", "..."]} '
    "(slot_name/context_hint/alt_values omitted or empty when either answer "
    "is false)."
)


def identify_slot_decomposed(text: str, source_label: str, adapter: ModelAdapter, max_candidates: int = 5) -> SlotCandidate | None:
    """Same goal as identify_slot, DECOMPOSED instead of one holistic yes/no
    judgment over the whole text -- the same fix already validated for
    method_trap.py's mechanical-application detection (2026-09-17): a single
    call asking 'does this text have a risky slot?' is exactly the kind of
    abstract judgment call that was unstable across repeated runs on the same
    input (key_error_missing_dict_check: 3 different verdicts in 3 separate
    runs this session). Splitting it into (1) a mechanical extraction of every
    literal-looking candidate, then (2) a narrow, concrete classification of
    EACH candidate independently, mirrors the divide-and-conquer fix that
    turned calculate_median from 0/4 to 4/4 -- index the candidates, judge
    each on its own, only then decide. MANDATORY before replacing
    identify_slot as the default: re-run validate_slot_identifier_milestone.py
    (or an equivalent repeated-run stability check) against this function
    before trusting it more than the one it replaces."""
    extract_prompt = f"Procedure/instruction text ({source_label!r}):\n```\n{text}\n```"
    extract_completion = adapter.complete(prompt=extract_prompt, system=_EXTRACT_LITERALS_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
    match = re.search(r"\[.*\]", extract_completion.text, re.DOTALL)
    if not match:
        return None
    try:
        candidates = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(candidates, list):
        return None
    # Verbatim, come identify_slot: uno slot candidato allucinato (non
    # presente per davvero nel testo) non e' recuperabile, va scartato.
    candidates = [c for c in candidates if isinstance(c, str) and c.strip() and c in text][:max_candidates]

    for candidate in candidates:
        classify_prompt = f"Procedure/instruction text:\n```\n{text}\n```\n\nSpecific literal to evaluate: {candidate!r}"
        completion = adapter.complete(prompt=classify_prompt, system=_CLASSIFY_LITERAL_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
        match = _JSON_RE.search(completion.text)
        if not match:
            continue
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if not (data.get("presented_as_definitive") is True and data.get("substitutable") is True):
            continue
        # Stabilizzatore generico: prima di fidarsi del "presentato come
        # definitivo", chiedi allo stesso modello di provare a smentirsi con
        # una citazione verbatim reale -- se ci riesce, il candidato non
        # regge, si passa al prossimo invece di accettarlo alla cieca.
        claim_summary = f"presented_as_definitive={data.get('presented_as_definitive')}, substitutable={data.get('substitutable')}"
        if not survives_adversarial_check(text, candidate, claim_summary, adapter):
            continue
        alt_values = data.get("alt_values") or []
        alt_values = [v for v in alt_values if isinstance(v, str) and v.strip() and v != candidate]
        if not alt_values:
            continue
        return SlotCandidate(
            source_label=source_label,
            slot_name=str(data.get("slot_name") or "slot"),
            original_value=candidate,
            context_hint=str(data.get("context_hint") or ""),
            alt_values=alt_values[:2],
        )
    return None


def build_slot_variants(text: str, slot: SlotCandidate) -> dict[str, str]:
    """Deterministic, verified substring replace -- the same mechanism
    validated by hand for floating_point_equality's '1e-9' fallback,
    generalized to whatever slot.original_value identify_slot found. Variant
    label == the value substituted in, matching substitution_ablation.py's
    own convention (slot_variants: label == expected tracked value)."""
    return {value: text.replace(slot.original_value, value) for value in slot.variant_values()}


def make_slot_transform(slot: SlotCandidate) -> Callable[[str, str], str]:
    """Returns a SlotTransform (see skill_repair.py) closed over this slot's
    original_value, so a REWRITTEN candidate's own text can be re-probed for
    the SAME literal instead of reusing pre-baked strings built from the
    original -- the exact false-negative bug skill_repair.py's own docstring
    documents finding live on 2026-09-16."""

    def _transform(text: str, label: str) -> str:
        return text.replace(slot.original_value, label)

    return _transform


def make_extractor(slot: SlotCandidate, adapter: ModelAdapter) -> ValueExtractor:
    """Returns a ValueExtractor (see substitution_ablation.py) that asks the
    Expert model to CLASSIFY which known candidate value (by index) the
    generated code uses, instead of transcribing the literal as free text.

    Real bug found live (2026-09-17, first real library-wide run): an
    earlier version of this function asked the judge to type out the exact
    literal, and it silently truncated scientific notation ("3.3e-4" ->
    "3.3") on a real Gemma completion that WAS mechanically copying the
    manipulated slot verbatim -- confirmed by re-running the same code
    through the OLD hand-written regex extractor (validate_floating_point_
    milestone.py's extract_epsilon), which caught it correctly. The
    truncated answer then never equalled any variant_label in
    substitution_ablation.py's exact-string comparison, undercounting real
    tracking to 0/12 on the very first pattern of the very first real run --
    exactly the kind of disagreement validate_slot_identifier_milestone.py
    exists to catch (it was skipped before this run; do not skip it again).

    Classifying by index instead of transcribing sidesteps the whole
    reformatting-fidelity problem: whatever this returns is always one of
    `candidates` verbatim (built from slot.original_value/alt_values, never
    retyped by the model), so it can never silently diverge from
    variant_label's own exact string, only correctly or incorrectly report
    which one (if any) matched."""
    candidates = slot.variant_values()

    def _extract(code: str) -> str | None:
        if not code.strip():
            return None
        candidate_list = "\n".join(f"{i}: {value}" for i, value in enumerate(candidates))
        prompt = (
            f"What to look for: {slot.context_hint or slot.slot_name}\n"
            f"Candidates:\n{candidate_list}\n\n"
            f"Code:\n```\n{code}\n```"
        )
        # 1024, non un valore piccolo come 64: stesso bug reale gia' documen-
        # tato altrove nel progetto (agents/worker.py, probe_generator.py) --
        # un modello "reasoning" (gemini-3.7-flash) spende token invisibili
        # di ragionamento anche per una risposta finale minuscola, e un cap
        # troppo basso tronca il JSON a meta' prima che scriva la risposta
        # vera. Trovato dal vivo 2026-09-17: con max_tokens=64 la risposta
        # era '{"matched' o addirittura vuota, non un vero matched_index.
        completion = adapter.complete(prompt=prompt, system=_MATCH_SYSTEM_PROMPT, max_tokens=1024, thinking_budget=0)
        match = _JSON_RE.search(completion.text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        idx = data.get("matched_index")
        if idx is None:
            return None
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return None
        if not (0 <= idx < len(candidates)):
            return None
        return candidates[idx]

    return _extract


def identify_slot_stable(text: str, source_label: str, adapter: ModelAdapter, n_samples: int = 3) -> SlotCandidate | None:
    """identify_slot_decomposed + majority voting (2026-09-18) -- see
    stabilizer.vote_for_result's own docstring for why voting is still
    needed even after decomposition + the adversarial check. This is the
    function callers should use by default now; identify_slot_decomposed
    itself is kept as the single-sample primitive voting calls repeatedly,
    not removed."""
    return vote_for_result(
        identify_fn=lambda: identify_slot_decomposed(text, source_label, adapter),
        key_fn=lambda slot: slot.original_value,
        n_samples=n_samples,
    )
