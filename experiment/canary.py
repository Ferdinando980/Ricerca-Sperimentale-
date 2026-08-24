"""Canary tasks (conversation 2026-08-18, after floating_point_equality's fix
passed one holdout and then a stricter review found that holdout wasn't a fair
test -- a single "holdout" score conflated three different questions).

Per bug-pattern, up to three synthetic probe tasks, deliberately never added
to domain/bug_catalog.py (never seen by the optimizer or skill_generator,
never used to tune a skill's wording) -- and crucially, category A is the
ONLY one allowed to double as calibration data; B and C must be tasks that
were never looked at while writing/fixing the skill, or they don't measure
what they claim to measure:

  CATEGORY_A (seen/explicit) -- a new problem where the missing parameter
    (e.g. a tolerance) IS stated in the problem itself (explicit wording, a
    percentage, a named margin). Measures: can the model APPLY the procedure
    when given what it needs.
  CATEGORY_B (novel/implicit-domain) -- a new problem where the parameter is
    NOT stated, but the domain is recognizable from naming (a physical unit
    in a variable name, a term like "sensor"/"reading") -- some signal, just
    not a number. Measures: transfer of the procedure WITH domain knowledge.
  CATEGORY_C (novel/no-hint) -- no number, no percentage, no unit, no
    domain-revealing naming anywhere. Measures: does the model have an
    abstract-enough procedure to reconstruct the missing parameter with
    (almost) no signal at all -- NOTE: with truly zero signal there may be no
    objectively "correct" epsilon at all (see sensor_readings_agree below,
    where even A/B/expert-and-unaided fail identically) -- a C failure that
    is uniform across ALL FOUR configs (A/B/F/C alike) shows the task is hard
    for everyone, not that the skill specifically underperforms baseline. The
    informative comparison for "does the skill help/hurt" is F vs B on the
    SAME task, not F's raw pass/fail alone.

Run: python -m cognitive_rpg.experiment.canary [experiment_id]
experiment_id defaults to "canary" but can point at an existing one (e.g.
"experiment3") to reuse results already collected there -- already-logged
(task_id, config) pairs are skipped (same checkpoint logic experiment_0.py
uses), so pointing this at old data costs nothing.
Costo: SI' per qualunque (task, config) non ancora loggato -- NO per quelli
gia' presenti (skip).

STABILITY CHECK (2026-08-18): same_destination re-run 5x independently on F --
epsilon=0.1 all 5 times. The per-task value is deterministic/stable, not
sampling noise -- whatever produces a given number for a given task does so
consistently, it just isn't (yet) shown to be a context-derived, per-domain-
correct number (0.1 is still wrong for this task's real ~2km scale).

CAUSAL ABLATION (2026-08-19, superseding the "well-supported hypothesis, not
demonstrated" framing below): moved from correlational evidence to a direct
manipulation test. First cleaned procedure_text of accumulated changelog
prose (it was repeating "0.01" many times in narrative asides -- a real
confound for this test, moved to a YAML comment, never sent to the model --
see the skill file's own changelog for the full note). Then, on the SAME
two no-hint tasks (sensor_readings_agree, same_destination):
  - Varied tier-b's currency number (0.01/0.5/0.003), tier-c fixed at 1e-9:
    F's answer stayed 1e-9 in all 6 runs. No cross-tier leakage.
  - Varied tier-c's OWN fallback number (1e-9/2.5e-6/7e-4), tier-b fixed:
    F's answer tracked EXACTLY, every time, both tasks (12/12 runs).
  - SELECTIVITY check (2026-08-19, the reverse direction): varied tier-c's
    constant again (1e-9/2.5e-6/7e-4) but tested on invoice_totals_match
    (tier-b applies, not tier-c) -- F's answer stayed 0.01 all 3 times,
    untouched by tier-c changing. F doesn't just substitute whichever tier
    fires; it correctly SELECTS the applicable tier first.
PRECISE WORDING MATTERS HERE: this is not "F recites the skill's example" in
the loose sense used earlier in this investigation -- that phrasing left
open a semantic choice between several examples in the text. The ablation
rules that out specifically: there is exactly ONE designated fallback slot
(tier-c), F selects it correctly when it's the applicable tier and ignores
it entirely when it isn't (selectivity check above), and when it IS the
applicable tier, F performs no scale-sensitive reasoning at all -- it
substitutes that slot's literal constant verbatim, right or wrong for the
task. "Mechanical substitution of a single selected slot," not "recitation."
This is the strongest claim the method supports: not internal-mechanism
proof (no weight/activation access via the API), but the explanation that
survived a real attempt to falsify it by manipulating the suspected cause
directly, not just observing its effects.

RETROACTIVE EXPLANATION for something left unresolved several turns earlier
in this investigation: why did the PRE-rewrite skill give F 0.01 on one
no-hint task and 0.1 on another (same_destination), instead of one constant
everywhere? At the time this looked like it might be a different, fuzzier
mechanism than simple substitution. It wasn't -- it was the same mechanism,
observed with the wrong instrument. The pre-rewrite skill had no single
designated fallback slot: it had TWO worked examples (1e-9 for identity,
"often 0.01 or looser" for real-world) with no explicit rule for picking
between them when neither applied cleanly, so which one got substituted (or
some interpolation of both) varied by task in a way that was never
characterized. The rewrite collapsed this into one explicit, single fallback
slot (tier-c) -- and once there was only one slot to substitute, the
substitution became perfectly uniform and predictable, exactly as this
ablation demonstrates. Same substitution mechanism, before and after; the
rewrite didn't change WHAT F does, it changed HOW MANY candidate slots
existed for it to substitute from -- one instead of an uncharacterized two.

HIERARCHY REFINEMENT (2026-08-19, prompted by external review): decomposed
"does F generalize" into recognition -> tier selection -> rule application ->
autonomous parameter derivation, and localized exactly where transfer stops.
Staged probing (name the relevant property, without computing a value; then
compute given that property's value handed over directly) on the UNCHANGED
skill: F ignored both prompts and just re-emitted tier-c's literal 1e-9 --
including when the grounding value was handed to it directly in the same
prompt. It does not spontaneously initiate derivation when the operative
rule is a literal constant. But rewriting tier-c to explicitly REQUIRE
deriving epsilon from a stated magnitude (instead of stating a constant) made
F actually perform the derivation, correctly tracking magnitude across a
~1e7 range in two replications (200-300 units -> ~1e-4, one arithmetic slip;
0.001-0.005 units -> exactly 5e-9, no slip). Conclusion: application is not
the bottleneck (F reliably does what tier-c's rule says, substitution or
derivation alike) -- initiation is. F will not invent an unrequested
strategy, but reliably executes a requested one, imperfectly on arithmetic
precision but correctly on order of magnitude. Full detail in
experiment/metrics.py's _KNOWN_SKILL_FINDINGS (REFINEMENT entry) and the
skill's own YAML changelog.

DELEGATED-ARITHMETIC VALIDATION (2026-08-19, prompted by external review, not
yet live): the single arithmetic slip above (1e-4 instead of 2.5e-4) is a
known LLM weakness -- silent token-by-token arithmetic -- not evidence of
unreliable scale-tracking. Tested a tier-c wording that asks F to extract the
stated magnitude into a variable and write epsilon as an
INTERPRETER-EVALUATED EXPRESSION (`epsilon = 1e-6 * typical_magnitude`)
instead of hand-computing and hardcoding the result. 7 runs, 5 tasks: the two
original magnitude domains now produce a correct expression with no
arithmetic left to get wrong; a THIRD domain never used to write the rule
(400-600 kg shipment weights) generalized correctly on the first try; both
genuinely no-magnitude tasks (sensor_readings_agree x2, same_destination x1)
still correctly fell back to the untouched literal 1e-9 default rather than
hallucinating an expression -- selectivity between "derive" and "no basis to
derive" held 5/5; currency (tier-b) was unaffected, 1/1. Deployment to the
live procedure_text is a separate, deliberate decision, not made here --
consistent with two failed rewrite attempts earlier in this same
investigation (see the YAML changelog). Note also the cost tradeoff this
buys into: reasoning through a derivation costs more tokens than blind
literal substitution, moving F's cost toward (not to) Expert's per-task cost.

CORRECTION to the validation above (2026-08-19, prompted by external
review): "generalizes to a third domain" was graded against 1e-6 *
stated_magnitude -- the same formula the same investigator wrote into the
rule, same session. That is rule-application fidelity, not independent
validation that 1e-6*magnitude is objectively correct. Applying this
investigation's own canary check (does unaided Expert converge near the
same answer without help?) to shipment_weight_match: NO. Expert, given the
bare buggy_source with no skill and no formula, produced
`math.isclose(weight_a, weight_b)` (rel_tol=1e-9 default -- essentially
machine-precision equality) in 3/3 reps, nothing resembling 1e-6*magnitude
and no real engagement with the stated 400-600 kg range. shipment_weight_
match does not clear canary validation -- it belongs with the underdetermined
domains, not the validated ones. The same caveat applies retroactively to
the two original magnitude domains (instrument, sensor) used to build the
rule: their correctness was also graded against the rule's own formula,
never independently checked. What survives is narrower than first stated: F
reliably extracts a stated magnitude and applies an EXPLICITLY GIVEN formula
to unseen data (mechanically verifiable, Category-A-like generalization).
What does not survive: any claim that 1e-6*magnitude is itself a validated
real-world convention -- it is exactly as author-arbitrary as any other
constant this investigation has flagged.

CLOSING FRAME for this investigation (2026-08-18, F reliably applies a
stated tolerance when the problem states one -- CATEGORY_A, verified -- is
still accurate and unaffected by the ablation above). 3 of 4 candidate
"no-hint but independently derivable" domains tried failed the validation "A
passes it too" -- rare, not just unlucky. This is the honest conclusion this
investigation supports: not "F solves floating_point_equality", not "F has a
known gap" -- F applies an explicit rule faithfully (Category A, and, now
shown, tier-c's fallback too) but performs no scale-sensitive reasoning of
its own when nothing explicit is given.

BACKLOG (2026-08-18, not investigated yet): the mechanism found here -- a
skill reciting its own worked-example NUMBER instead of deriving one -- is a
property of ANY skill whose procedure_text includes a concrete illustrative
value, not something specific to floating_point_equality. Worth checking
whether off_by_one, mutable_default_argument, wrong_accumulator_init etc.
have the same vulnerability on their own never-tested Category C variants
before assuming this investigation's fix (whatever it ends up being) is
needed only here.

WHERE TO LOOK NEXT (2026-08-19, prompted by external review): the 6-of-7
underdetermined-domain count above is specific to floating_point_equality,
not to "no-hint parameter derivation" in general. The 2026-08-18 audit of
the other 8 skills (thesis §6) found 3 candidates -- accumulator init for a
product (should be 1, not 0), dict default (None vs the illustrated 0/[]/""),
mutable-default-argument's dict variant -- where A independently derived the
right value with NO formula given, because the answer follows from the
code's own local semantics (what operation is the loop doing, what type is
the default), not from a real-world convention absent from the code. That is
a genuinely different, more fertile territory than floating-point tolerance:
worth building MORE candidates there (other accumulator operators --
concatenation, intersection; other dict-default variants) rather than
continuing to mine floating-point's structurally-poor no-hint space.

SCREENED AND NOT ADOPTED (2026-08-19): significant-figures-implied precision
(trailing decimal digits in a literal, e.g. 12.30 vs 12.3, declaring
measurement precision via the standard error-propagation convention
epsilon = 0.5 * 10^-min(decimals_a, decimals_b)) was proposed as a possible
second validated Category C domain for THIS pattern, on the theory that the
precision info lives in the number's own written representation rather than
in an external real-world convention. Cheap screening per the process fix
below -- 3 variants (same 2-decimal precision both sides; mismatched 1-vs-3
decimals; same 3-decimal precision both sides), unaided Expert only, 2 reps
each, no F/B/C calls -- gave a MIXED result, not a clean pass: 4 of 6 runs
ignored the decimal-digit hint entirely (`math.isclose` with its 1e-9
default, same failure mode as every other floating-point no-hint domain);
2 of 6 did engage with the written precision (`round(value_a, 1) ==
round(value_b, 1)`; `round(reading_a, 2) == round(reading_b, 2)`) but at
inconsistent digit counts that don't converge on each other or cleanly match
the hypothesized formula. Conclusion: does not clear the canary bar (A
converging independently AND consistently) -- NOT built further, no F calls
spent, no thesis subsection written (still true as of the latest round
below -- this remains a screening note, not yet promoted to the thesis).
Kept here specifically
so this doesn't get rediscovered at the cost of another retraction:
significant-figures precision is closer to validatable than
sensor/km/wavelength/shipment (some real engagement, not zero) but is not
there yet with n=2 per variant. If revisited, more reps per variant (5+)
before any F call would be the right next step, not a rebuild from scratch.

The failure is not uniform, and the asymmetry is worth isolating rather than
averaging away: the two SAME-precision variants (12.30/12.31; 3.140/3.142)
show the already-familiar pattern -- A ignores the cue 3 of 4 reps. The
MISMATCHED-precision variant (7.2 vs 7.203) is the only one where A notices
something in BOTH reps, and does so structurally correctly in one of them
(rounds to the LESS precise side, 1 decimal, matching the standard
error-propagation convention). This suggests the real trigger may be the
ASYMMETRY between the two operands' precision, not decimal precision per se
-- a narrower, cheaper hypothesis than the original 3-way split: isolate
degree of asymmetry alone (e.g. 7.2 vs 7.201, 7.2 vs 7.2001), more reps each,
before touching F. Not tested here -- a lead, not a result.

Also worth keeping distinct from the sensor/km/wavelength/shipment failures:
this is a different KIND of "no". There, the problem was test validity
itself -- a threshold invented by whoever wrote the canary, no independently
real convention behind it. Here, the convention (significant figures /
error propagation from written precision) is real and textbook, not
invented for this experiment -- the failure is that the model does not
reliably self-apply it from a formatting cue alone, without being told to.
That's a more precisely localized "no": not "the question is ill-posed" but
"the cue is real but too weak/implicit for the model to pick up on its own,
consistently."

FOLLOW-UP 1 -- asymmetry DEGREE alone (2026-08-19): tested whether MORE
decimal-asymmetry produces a MORE reliable trigger. 3 variants, less-precise
side fixed at 7.2 (1 decimal), other side at 2/3/4 decimals (7.21 / 7.203 /
7.2001), 4 unaided-Expert reps each, still no F/B/C. Result: the opposite of
the hypothesis. Small asymmetry (7.2 vs 7.21) gave the CLEANEST signal found
in this pattern besides currency -- 3/4 reps exactly `round(x,1)==round(y,1)`,
matching the textbook convention. Medium asymmetry (7.2 vs 7.203): mixed,
1/4 exact, 2/4 ignored, 1/4 partial. Large asymmetry (7.2 vs 7.2001): 0/4
exact -- 3/4 engaged but converged on SMALL tolerances (rel_tol~1e-3,
abs_tol=0.01) that weight the MORE precise operand, the wrong direction for
the convention; 1/4 ignored. So: engagement (choosing any non-default
tolerance) rose with asymmetry, but CORRECTNESS fell -- engagement and
correctness are not the same axis here.

FOLLOW-UP 2 -- 2x2 factorial, asymmetry x absolute numeric distance
(2026-08-19, prompted by external review): follow-up 1 confounded asymmetry
with raw distance (7.2/7.21=0.01 apart, 7.2/7.203=0.003, 7.2/7.2001=0.0001 --
asymmetry and closeness moved together), so the degradation above could have
been driven by "these look almost identical" rather than by significant
figures at all. Crossed the two variables, still Expert-only, 4 reps/cell:

  asymmetry \\ distance |  large gap (~0.09)         | small gap
  low  (1 vs 2 dec)     |  7.2/7.29:  4/4 engage,     | 7.2/7.21 (follow-up 1):
                        |    1/4 exact round(.,1),    |   3/4 exact round(.,1)
                        |    rest coarser (round-int, |
                        |    abs<=0.1)                |
  high (1 vs 4 dec)     |  7.2/7.2900: 4/4 engage,    | 7.2/7.2001 (follow-up 1):
                        |    0/4 exact, all coarser   |   3/4 engage w/ SMALL
                        |    (round-int x2, abs<=0.1  |   tolerances (wrong
                        |    x2)                      |   direction), 1/4 ignore

  (a 5th cell, 7.2 vs 7.20 -- same asymmetry as the top row, distance
  EXACTLY zero -- was also run: 4/4 collapsed to bare `math.isclose()`
  default. Flagged, not used as clean "distance" evidence: 7.2==7.20 as
  floats are numerically IDENTICAL, so this example doesn't demonstrate a
  bug at all -- the collapse may reflect that degeneracy, not "small
  distance" as a continuous variable. A genuinely tiny-but-nonzero-distance
  low-asymmetry cell was not run.)

Reading: large distance reliably triggers SOME tolerance-adding behavior
regardless of asymmetry (8/8 non-default across both large-gap cells), but
its precision is coarser at high asymmetry (0/4 exact) than at low asymmetry
(1/4 exact, rest in a similar ballpark). Small distance behaves oppositely:
low asymmetry there gives the best result found in this pattern (3/4 exact,
follow-up 1), while high asymmetry with small distance drifts toward overly
tight tolerances -- closer to "these look nearly the same, be strict" than
to the significant-figures rule. Neither "asymmetry alone" nor "distance
alone" cleanly explains the full pattern; the single best-performing
controlled cell remains low-asymmetry + small-nonzero-distance (7.2 vs
7.21-style). STILL NOT PROMOTED to the thesis or to an F call: 30
Expert-only calls have now gone into this candidate across 3 rounds without
a single cell reaching the reliability standard the currency canary met (5/5
identical, not 3/4). Next honest step, if pursued further: replicate the
7.2-vs-7.21-style cell on 2-3 DIFFERENT literal pairs at the same
low-asymmetry/small-distance combination, to rule out that "7.2/7.21"
specifically is doing the work rather than the combination it represents --
otherwise, close as an interesting, real, but inconclusive open lead.

FOLLOW-UP 3 -- memorization control, DECISIVE (2026-08-19, prompted by
external review, stop condition fixed BEFORE running): 7.2 vs 7.21 is a
textbook-clean pair -- the exact kind of example that appears verbatim in
physics sig-fig explanations, so its 3/4-exact result was plausibly Expert
reciting a memorized worked example rather than applying a general
principle (the same memory-vs-competence question this whole chapter asks
of F, now aimed at the measuring instrument itself). Test: same cell (low
asymmetry, small nonzero distance) but with deliberately non-textbook pairs
-- more digits, not round numbers: 13.7/13.68 (delta 0.02), 241.6/241.58
(delta 0.02, different magnitude), 89.4/89.37 (delta 0.03). 4 reps each, 12
unaided-Expert calls, no F/B/C. Result: 11/12 EXACT `round(a,1)==round(b,1)`
(the 12th used round-to-integer, same direction, coarser) -- MORE
consistent than the textbook pair itself (11/12=92% vs 3/4=75%). This rules
out memorization: if the original result were recall, novel pairs should
have performed WORSE, not better. VALIDATED: this is a genuine second
CATEGORY_C domain for floating_point_equality, independent of the currency
one -- the first this investigation has confirmed since. Registered as
VALIDATED_C2_EXAMPLES below (a second module-level registry, parallel to
INVALID_EXAMPLES, since CanarySet's `c` slot is already occupied by
invoice_totals_match and this is a distinct sub-condition, not a
replacement). FOLLOW-UP 4 -- F test, DECISIVE, the sharpest positive result in this
chapter (2026-08-19, prompted by external review, two variables crossed in
ONE round per explicit design correction -- decimal structure AND skill
condition together, not sequential rounds like the asymmetry/distance
split): tests whether F, given the sig-figs convention, tracks each task's
OWN decimal structure (real derivation) or substitutes a single memorized
number everywhere (the same ambiguity currency's 0.01 never resolved, since
it happened to be scale-correct on both no-hint tasks it was tried on).

  BASELINE (live skill, sig-figs NOT in tier-b), 3 reps x 2 tasks:
    component_reading_matches (1v2 dec): 3/3 -> falls to tier-c (1e-9), as
      predicted -- F does not spontaneously invent the convention.
    dial2_reading_matches (2v3 dec): 1/3 -> tier-c (1e-9); 2/3 -> misfires
      to CURRENCY's 0.01 ("dial-based measurements" loosely associated with
      a known convention) -- A THIRD failure type this chapter had not yet
      catalogued: not blind fallback substitution (that's component_reading_
      matches, 3/3 to tier-c as predicted) and not correct derivation --
      generalization attempted via weak SEMANTIC word-association ("dial"
      loosely evoking "some conventional measurement"), not problem
      structure. More interesting than the other failure modes precisely
      because it shows what F does when it tries to generalize past pure
      substitution: reach for surface wording similarity, not structure.

  RESEARCH VARIANT (sig-figs added as a 2nd tier-b convention, same
  load/splice/restore pattern as the delegated-arithmetic test, live file
  restored in `finally`), 3 reps x 2 tasks: 6/6 correct, AND -- the
  decisive part -- the two tasks produced DIFFERENT epsilon values, each
  correctly scaled to ITS OWN decimal structure: component_reading_matches
  (d=1) -> 0.05 every time; dial2_reading_matches (d=2) -> 0.005 every time,
  both with the reasoning ("less precise value, d=N, epsilon=0.5*10^-N")
  written out in the generated comment. A single-constant-substitution
  mechanism would produce the SAME number regardless of task (as it did in
  the baseline's 1e-9, and in the misfired 0.01) -- producing two DIFFERENT,
  each-correctly-derived numbers rules that out. This is the first result
  in this entire chapter that resolves recitation-vs-derivation cleanly on
  a domain independently confirmed NOT to be a lucky-scale coincidence (see
  FOLLOW-UP 3) -- currency's 0.01 could never make this distinction because
  it was scale-appropriate on every no-hint task tried by chance. NOT
  adopted as the live procedure_text -- same deliberate-decision principle
  as the delegated-arithmetic result (§5.9): a validated research finding,
  deployment is a separate choice.

FOLLOW-UP 5 -- closing the last gap (2026-08-19, prompted by external
review): every independent A-validation of the sig-figs domain so far
(the textbook pair and the 3 memorization-control pairs) used 1-vs-2-decimal
structure (d=1, eps~0.05). FOLLOW-UP 4's F test also used a 2-vs-3-decimal
task (dial2_reading_matches, d=2, eps~0.005) to get F to produce two
DIFFERENT numbers -- but that specific structure (d=2) had never itself been
independently checked on A. Lower risk than shipment_weight_match (there the
whole formula was invented from nothing; here the formula 0.5*10^-d is
already validated -- extending it to a new value of d is a reasonable
extrapolation of a confirmed principle, not another guessed constant) but
still a gap worth closing before calling the result final. 4 Expert-only
reps on a fresh 2v3-decimal pair (58.34 vs 58.337), independent of the task
used in the F test: 4/4 exact `round(x,2)==round(x,2)`, matching d=2 (the
less precise side) unanimously. The last open thread is closed -- both
decimal structures used in the decisive F test are now independently
A-validated, not just the d=1 one. Chapter closed on this candidate.

PROCESS FIX ADOPTED THIS SESSION (2026-08-19, prompted by external review,
applied immediately to the sig-fig screening above): the shipment_weight_
match retraction cost far more to discover after the fact (thesis
subsection written, 4 docs updated, then all 4 corrected) than it would
have cost to check first. New default for any future no-hint domain
candidate: screen in bulk, Expert-only, no F/B/C, before writing anything
that assumes the domain is valid. Only candidates A solves independently and
consistently earn the expensive validation (F, ablation, four-document
writeup).

WHAT TODAY'S COST ACTUALLY BUYS -- A REUSABLE METHOD, NOT A PER-SKILL PRICE
(2026-08-19, prompted by external review): today's total spend (~700 calls
across screening, ablation, and experiment4) is not "the cost of validating
a floating-point-tolerance skill" in general -- it is the one-time cost of
BUILDING the validation method itself, paid once. The next skill with a
context-dependent numeric parameter does not start from zero: it inherits
the criterion (independent-baseline check before trusting a no-hint test),
the structural fix pattern (delegate arithmetic to the interpreter, never a
second hardcoded magic number), and a growing catalog of which domain
SHAPES tend to pass or fail (see VALIDATED_C2_EXAMPLES / INVALID_EXAMPLES
above) -- checking "is this domain shape already classified" is cheap;
discovering a domain's shape from nothing is where today's cost actually
went (5 of 6 sig-fig-adjacent domain attempts alone failed the validity
bar -- research into an unknown domain costs more than execution on a known
one, by construction, independent of how cheap any single call is).

Two levers make this reusable in practice, not just in principle:

1. RISK TRIAGE, not uniform scrutiny. The 2026-08-18 audit of the other 8
   skills (thesis §6) is a real, load-bearing data point here: DISCRETE/
   STRUCTURAL parameters (which operator, which transformation, 0 vs 1 vs
   [] as an accumulator seed) passed independent validation on the first
   try, every time, no ambiguity -- because the correct answer is read off
   the code's own local semantics, not an external convention. CONTINUOUS
   parameters tied to an external convention (a tolerance, a threshold) are
   the only category that has ever produced a real bug in this whole
   investigation. A new skill's parameter should be triaged into one of
   these two buckets FIRST: structural -> a light check (2-3 Expert-
   independent runs, matching the §6 audit's own protocol) is proportionate;
   continuous-external-convention -> the full apparatus (screening, ablation,
   memorization control) earns its cost.
2. TWO-SPEED VALIDATION, not one gate. A skill does not need today's full
   rigor before any use -- it needs it before being TRUSTED long-term
   without supervision. Start light (independent-baseline check, a handful
   of calls); escalate to the heavy apparatus only once real usage
   volume or ambiguous signal justifies the spend -- the same
   promote/demote-on-a-rolling-window principle already implemented for
   Aria's skill library (see ../../../Jarvis/src/lib/skills.ts,
   reviewSkills -- ported back here as a principle, not literal code, since
   this side has a real pytest oracle Aria's domain doesn't). This is what
   makes the cost model sustainable at scale: pay the heavy price on the
   skills that turn out to matter, not on all of them upfront.

What NOT to cut to save money, because today found exactly what cutting it
costs instead: the independent-baseline check before trusting a no-hint
test, and the causal ablation once a parameter is confirmed continuous and
externally-conventional. These two specifically are what caught
shipment_weight_match, exposed the "0.1%-of-scale" formula as unvalidated,
and ruled out memorization on the textbook pair. Skipping them does not
lower a skill's cost -- it moves the cost from "paid today, under control"
to "paid later, after a wrong skill has been giving confident wrong advice
in production for weeks" (see Jarvis's own skills.ts docstring for the
mirror-image version of this same risk, now guarded against there too).
"""

import sys
from dataclasses import dataclass

from ..adapters import build_adapter
from ..models import Task
from .experiment_log import read_all
from .quest_runner import run_quest

CONFIGS = ("A", "B", "F", "C")


@dataclass
class CanarySet:
    pattern_id: str
    a: Task | None = None  # explicit hint
    b: Task | None = None  # domain-recognizable, no number
    c: Task | None = None  # no signal at all -- ONLY register a task here once
    # its "correct answer" has been shown to be independently derivable (A
    # passing it, via a DIFFERENT mechanism than whatever F/the skill uses,
    # is the check -- see c_note below). A task where A also fails is not
    # evidence about the skill; it's evidence the task has no derivable
    # answer, and belongs in INVALID_EXAMPLES, not here.
    b_note: str = ""  # why `b` is or isn't clean calibration-wise
    c_note: str = ""


CANARY_SETS: dict[str, CanarySet] = {
    "floating_point_equality": CanarySet(
        pattern_id="floating_point_equality",
        a=Task(
            task_id="floating_point_equality__price_within_budget__holdout",
            pattern_id="floating_point_equality",
            problem_id="price_within_budget",
            fn_name="price_within_budget",
            buggy_source=(
                "def price_within_budget(price, budget):\n"
                "    # prices should be treated as matching if within 2% of the budget\n"
                "    # (rounding/display differences from the pricing feed)\n"
                "    return price == budget\n"
            ),
            test_source=(
                "def test_boundary_within():\n"
                "    assert price_within_budget(1020, 1000) is True\n\n"
                "def test_just_outside():\n"
                "    assert price_within_budget(1030, 1000) is False\n\n"
                "def test_large_budget_small_relative_diff():\n"
                "    assert price_within_budget(24800, 25000) is True\n\n"
                "def test_large_budget_large_relative_diff():\n"
                "    assert price_within_budget(20000, 25000) is False\n\n"
                "def test_exact():\n"
                "    assert price_within_budget(100, 100) is True\n"
            ),
            split="CATEGORY_A",
            problem_tags=["wrong-output", "runtime-bug"],
            capability_tags=["floating-point", "equality-check"],
        ),
        b=Task(
            task_id="floating_point_equality__same_destination__holdout_nohint",
            pattern_id="floating_point_equality",
            problem_id="same_destination",
            fn_name="same_destination",
            buggy_source=(
                "def same_destination(distance_km, target_km):\n"
                "    return distance_km == target_km\n"
            ),
            test_source=(
                "def test_exact():\n"
                "    assert same_destination(10.0, 10.0) is True\n\n"
                "def test_within_range():\n"
                "    assert same_destination(10.0, 11.5) is True\n\n"
                "def test_just_outside_range():\n"
                "    assert same_destination(10.0, 13.0) is False\n\n"
                "def test_far_outside():\n"
                "    assert same_destination(100.0, 150.0) is False\n\n"
                "def test_zero():\n"
                "    assert same_destination(0.0, 0.0) is True\n"
            ),
            split="CATEGORY_B",
            problem_tags=["wrong-output", "runtime-bug"],
            capability_tags=["floating-point", "equality-check"],
        ),
        b_note=(
            "DISPUTED (2026-08-18): variable names carry '_km', a residual unit "
            "hint, AND expert-tier A failed this too -- if the hint were enough "
            "to trigger real domain convention, A should pass it. A also failing "
            "means this task's specific threshold (~2km) is likely just as "
            "author-arbitrary as sensor_readings_agree's, not a fair B probe. "
            "Kept for the record, not cited as evidence either way. F's actual "
            "output here (verified directly, not assumed): epsilon=0.1 -- NOT "
            "the same 0.01 F used on sensor/currency, so 'F always recites 0.01' "
            "is FALSE; corrected 2026-08-18 after this was flagged as unverified."
        ),
        c=Task(
            task_id="floating_point_equality__invoice_totals_match__true_c2",
            pattern_id="floating_point_equality",
            problem_id="invoice_totals_match",
            fn_name="invoice_totals_match",
            buggy_source=(
                "def invoice_totals_match(computed_amount, invoice_amount):\n"
                "    return computed_amount == invoice_amount\n"
            ),
            test_source=(
                "def test_exact():\n"
                "    assert invoice_totals_match(100.00, 100.00) is True\n\n"
                "def test_subcent_rounding():\n"
                "    assert invoice_totals_match(100.005, 100.00) is True\n\n"
                "def test_full_cent_off():\n"
                "    assert invoice_totals_match(100.02, 100.00) is False\n\n"
                "def test_absolute_not_relative_large_amount():\n"
                "    assert invoice_totals_match(50000.05, 50000.00) is False\n\n"
                "def test_zero():\n"
                "    assert invoice_totals_match(0.00, 0.00) is True\n"
            ),
            split="CATEGORY_C",
            problem_tags=["wrong-output", "runtime-bug"],
            capability_tags=["floating-point", "equality-check"],
        ),
        c_note=(
            "VALIDATED clean (2026-08-18), n=1 for the A-check itself: A "
            "(unaided) passes invoice_totals_match via round(x, 2) == "
            "round(y, 2), independent of F's epsilon approach -- confirms "
            "'currency -> cent precision, absolute not relative' is genuinely "
            "derivable, not an author-arbitrary threshold (unlike sensor_"
            "readings_agree/same_destination/wavelength_matches, all in "
            "INVALID_EXAMPLES because A fails those too). C had coverage="
            "PARTIAL (real retrieval, not NONE) and still failed by copying "
            "the wrong literal -- a real memorization-doesn't-transfer point.\n"
            "SKILL REWRITTEN 2026-08-18 (explicit 3-tier fallback: stated "
            "tolerance -> known convention [currency only, so far] -> "
            "conservative 1e-9 + explicit comment, no more guessed real-world "
            "numbers) and re-verified directly: invoice_totals_match still "
            "PASSES unchanged (no regression on the one case with known "
            "ground truth). All 3 no-hint probes (sensor/km/wavelength) now "
            "consistently emit 1e-9 with an explicit assumption-comment "
            "instead of a varying guess (was 0.01/0.1, inconsistent) -- still "
            "fail the tests, correctly, since the audit already showed no "
            "derivable answer exists for those. KNOWN REGRESSION, accepted: "
            "temperature_reached (never independently validated on A, "
            "calibration-contaminated) now fails again. NOTE: these post-"
            "rewrite results are from direct diagnostic re-verification, NOT "
            "yet re-logged to logs/canary/ (the checkpoint skip-logic there "
            "still holds the PRE-rewrite results for these task_ids -- re-"
            "running canary.run_all() as-is will skip them, not update them; "
            "would need a fresh experiment_id to get an official re-logged "
            "record)."
        ),
    ),
    # NOTE: temperature_reached (the original bug that triggered this whole
    # investigation) is deliberately NOT registered here. Two independent
    # reasons, found on two different passes:
    # 1. It IS the calibration data (the fix's step 2 was written specifically
    #    to make this task pass) -- reusing it as a "domain transfer" data
    #    point double-counts the same observation as evidence of
    #    generalization (found + corrected 2026-08-18).
    # 2. Deeper problem found 2026-08-19: A/B's unaided "pass" on this task is
    #    NOT valid tier-2 evidence either. Checked their actual code for the
    #    first time -- both write `any(r >= target for r in readings)`, no
    #    epsilon at all, which is WRONG vs the true correct_source (fails on
    #    a reading just under target within tolerance -- verified directly).
    #    bug_catalog.py's own test suite for this task never covers that
    #    case, so this wrong solution passed undetected in every official run
    #    this session (experiment0/2/3 all count it as a correct A/B pass).
    #    Also: the 0.01 in correct_source is a bare, undocumented literal --
    #    exactly as author-arbitrary as sensor_readings_agree/same_
    #    destination/wavelength_matches. NOT hardening bug_catalog.py's test
    #    against it -- that would mean choosing the "right" tolerance in the
    #    task author's place. temperature_reached belongs in the same
    #    underdetermined bucket as the tier-3 INVALID_EXAMPLES, not as a
    #    second tier-2 convention alongside currency. A broader audit of the
    #    other 8 live skills' KNOWN/VARIANT tasks (2026-08-19) found no
    #    similar coverage gap elsewhere -- this looks specific to
    #    temperature_reached's ambiguous wording ("reached" admits a >=
    #    reinterpretation that sidesteps tolerance entirely), not systemic.
    "wrong_accumulator_init": CanarySet(
        pattern_id="wrong_accumulator_init",
        c=Task(
            task_id="wrong_accumulator_init__product_of_factors__true_c",
            pattern_id="wrong_accumulator_init",
            problem_id="product_of_factors",
            fn_name="product_of_factors",
            buggy_source=(
                "def product_of_factors(numbers):\n"
                "    result = 0\n"
                "    for n in numbers:\n"
                "        result *= n\n"
                "    return result\n"
            ),
            test_source=(
                "def test_multiple():\n"
                "    assert product_of_factors([2, 3, 4]) == 24\n\n"
                "def test_single():\n"
                "    assert product_of_factors([5]) == 5\n\n"
                "def test_ones():\n"
                "    assert product_of_factors([1, 1, 1]) == 1\n\n"
                "def test_empty():\n"
                "    assert product_of_factors([]) == 1\n"
            ),
            split="CATEGORY_C",
            problem_tags=["wrong-output", "runtime-bug"],
            capability_tags=["accumulator-init", "loop-state"],
        ),
        c_note=(
            "Backlog audit (2026-08-18): skill's example only illustrates "
            "'0 vs empty', never '1 for a product' -- same risk shape as "
            "floating_point_equality's epsilon. VALIDATED: A passes "
            "independently (result=1, derived, not recited). F ALSO passes "
            "(result=1, matches A) -- unlike floating_point_equality, F did "
            "NOT recite the skill's illustrated '0' default here. Risk did "
            "not materialize for this pattern."
        ),
    ),
    "key_error_missing_dict_check": CanarySet(
        pattern_id="key_error_missing_dict_check",
        c=Task(
            task_id="key_error_missing_dict_check__track_previous_value__true_c",
            pattern_id="key_error_missing_dict_check",
            problem_id="track_previous_value",
            fn_name="track_previous_value",
            buggy_source=(
                "def track_previous_value(history, key, current_value):\n"
                "    previous = history[key]\n"
                "    history[key] = current_value\n"
                "    return previous\n"
            ),
            test_source=(
                "def test_first_call_returns_none():\n"
                "    assert track_previous_value({}, 'a', 100) is None\n\n"
                "def test_second_call_returns_previous():\n"
                "    h = {'a': 100}\n"
                "    assert track_previous_value(h, 'a', 200) == 100\n\n"
                "def test_updates_value():\n"
                "    h = {'a': 100}\n"
                "    track_previous_value(h, 'a', 200)\n"
                "    assert h['a'] == 200\n\n"
                "def test_different_key_independent():\n"
                "    h = {'a': 100}\n"
                "    assert track_previous_value(h, 'b', 5) is None\n"
            ),
            split="CATEGORY_C",
            problem_tags=["wrong-output", "runtime-bug"],
            capability_tags=["missing-key-check", "dict-access"],
        ),
        c_note=(
            "Backlog audit (2026-08-18): skill's examples list '0, [], \"\"' "
            "but never None. VALIDATED: A passes independently (history."
            "get(key), None by Python's own default). F ALSO passes (same "
            "history.get(key) -- not one of the 3 illustrated defaults). "
            "Risk did not materialize for this pattern."
        ),
    ),
    "mutable_default_argument": CanarySet(
        pattern_id="mutable_default_argument",
        c=Task(
            task_id="mutable_default_argument__tally_by_category__true_c",
            pattern_id="mutable_default_argument",
            problem_id="tally_by_category",
            fn_name="tally_by_category",
            buggy_source=(
                "def tally_by_category(item, counts={}):\n"
                "    counts[item] = counts.get(item, 0) + 1\n"
                "    return counts\n"
            ),
            test_source=(
                "def test_first_call():\n"
                "    assert tally_by_category('a') == {'a': 1}\n\n"
                "def test_independent_calls_dont_leak():\n"
                "    r1 = tally_by_category('a')\n"
                "    r2 = tally_by_category('b')\n"
                "    assert r2 == {'b': 1}\n\n"
                "def test_accumulates_within_explicit_dict():\n"
                "    d = {}\n"
                "    tally_by_category('x', d)\n"
                "    tally_by_category('x', d)\n"
                "    assert d == {'x': 2}\n"
            ),
            split="CATEGORY_C",
            problem_tags=["wrong-output", "runtime-bug"],
            capability_tags=["mutable-default-argument", "python-gotcha"],
        ),
        c_note=(
            "Found during backlog audit (2026-08-18, not in the original "
            "flagged pair): skill's example only shows 'val = [] if val is "
            "None else val' (a list). VALIDATED: A passes independently "
            "(counts = {} if None, derived from the dict-typed default in "
            "the buggy source). F ALSO passes (same {}, not the illustrated "
            "[]). Risk did not materialize for this pattern either.\n"
            "SEPARATE issue found + FIXED 2026-08-19: bug_catalog.py's own "
            "tests for this pattern's two OFFICIAL tasks (dedupe_preserve_"
            "order, flatten_list) only ever caught the mutable-default bug "
            "as a side effect of pytest running multiple test functions in "
            "one process (state leaking test-to-test) -- verified with real "
            "isolated pytest runs (file.py::single_test, fresh process): "
            "EVERY individual test function passes the buggy code alone. "
            "Unlike temperature_reached, this needed no arbitrary number to "
            "fix -- added one self-contained test per task (two calls inside "
            "ONE test function, order-independent) to bug_catalog.py itself. "
            "Verified: task_ids unchanged (historical experiment0/2/3 stay "
            "valid records of what the OLD, weaker suite measured), F still "
            "passes both with the current skill (4/4, no regression)."
        ),
    ),
}

# BACKLOG CLOSED (2026-08-18): audited all 9 remaining live skills' procedure_
# text for a concrete illustrative value analogous to floating_point_equality's
# epsilon. 6 of 9 have no such value at all (discrete operator/structure choice,
# not a value to recite) -- low risk by construction. 3 flagged as structurally
# similar (wrong_accumulator_init, key_error_missing_dict_check, and
# mutable_default_argument, found during the audit) were each given ONE
# validated (A-passes-independently) Category C test -- all 3 passed on F too.
# Conclusion: the recitation-instead-of-deriving risk found in
# floating_point_equality does NOT generalize to the rest of the library --
# it appears specific to that pattern's nature (a continuous, domain-dependent
# parameter with no universal correct value), not a general property of
# "skill has an illustrative example." This is a legitimate closure of the
# backlog, not a failed audit -- see the module docstring's CLOSING FRAME.

# Kept for the record, NOT used as evidence: this failed uniformly across
# A/B/F/C (expert-tier A included), meaning its "correct" threshold is very
# likely author-arbitrary rather than derivable from the problem -- same
# defect class as 3 other bugs found this session (fixed epsilon in the
# skill itself, a static denominator in library density, non-cumulative
# build cost). A canary only counts as CATEGORY_C evidence once A is shown
# to pass it through some independent mechanism (see invoice_totals_match,
# the CATEGORY_C task actually registered above). same_destination (the B
# slot above) has the same disease -- see its b_note -- but is left in place
# since B's bar for validity is lower (domain hint allowed, just not a
# number); it's flagged there rather than duplicated here.
INVALID_EXAMPLES: dict[str, Task] = {
    "sensor_readings_agree": Task(
        task_id="floating_point_equality__sensor_readings_agree__true_c",
        pattern_id="floating_point_equality",
        problem_id="sensor_readings_agree",
        fn_name="sensor_readings_agree",
        buggy_source=(
            "def sensor_readings_agree(reading_a, reading_b):\n"
            "    return reading_a == reading_b\n"
        ),
        test_source=(
            "def test_close_enough():\n"
            "    assert sensor_readings_agree(10.02, 10.05) is True\n\n"
            "def test_too_far():\n"
            "    assert sensor_readings_agree(10.0, 10.2) is False\n\n"
            "def test_boundary_pass():\n"
            "    assert sensor_readings_agree(5.0, 5.04) is True\n\n"
            "def test_exact():\n"
            "    assert sensor_readings_agree(1.0, 1.0) is True\n"
        ),
        split="INVALID_C_ATTEMPT",
        problem_tags=["wrong-output", "runtime-bug"],
        capability_tags=["floating-point", "equality-check"],
    ),
    "wavelength_matches": Task(
        task_id="floating_point_equality__wavelength_matches__true_c3",
        pattern_id="floating_point_equality",
        problem_id="wavelength_matches",
        fn_name="wavelength_matches",
        buggy_source=(
            "def wavelength_matches(measured_nm, reference_nm):\n"
            "    return measured_nm == reference_nm\n"
        ),
        test_source=(
            "def test_exact():\n"
            "    assert wavelength_matches(532.0, 532.0) is True\n\n"
            "def test_within_instrument_resolution():\n"
            "    assert wavelength_matches(532.0, 533.5) is True\n\n"
            "def test_outside_resolution():\n"
            "    assert wavelength_matches(532.0, 535.0) is False\n\n"
            "def test_different_spectral_line():\n"
            "    assert wavelength_matches(450.0, 650.0) is False\n\n"
            "def test_zero():\n"
            "    assert wavelength_matches(0.0, 0.0) is True\n"
        ),
        split="INVALID_C_ATTEMPT",
        problem_tags=["wrong-output", "runtime-bug"],
        capability_tags=["floating-point", "equality-check"],
    ),
    # 2026-08-19, added retroactively (prompted by external review): the two
    # domains used to build/test the delegated-arithmetic tier-c rewrite
    # (§5.8-5.9 of the thesis) were graded against 1e-6*magnitude -- the same
    # formula the same investigator wrote into the rule, same session. That
    # is not independent validation; it was never actually run through this
    # module's own canary check. Registered here, in the invalid/
    # underdetermined bucket, rather than left implied-valid in prose only --
    # test_source is intentionally empty: writing a pytest boundary now, with
    # the 1e-6 formula already in mind, would reproduce the exact
    # investigator-degrees-of-freedom risk this bucket exists to flag.
    "instrument_readings_match": Task(
        task_id="floating_point_equality__instrument_readings_match__unvalidated",
        pattern_id="floating_point_equality",
        problem_id="instrument_readings_match",
        fn_name="instrument_readings_match",
        buggy_source=(
            "def instrument_readings_match(reading_a, reading_b):\n"
            "    # readings from this instrument are typically in the range of 200-300 units\n"
            "    return reading_a == reading_b\n"
        ),
        test_source="",
        split="INVALID_C_ATTEMPT",
        problem_tags=["wrong-output", "runtime-bug"],
        capability_tags=["floating-point", "equality-check"],
    ),
    "sensor_calibration_match": Task(
        task_id="floating_point_equality__sensor_calibration_match__unvalidated",
        pattern_id="floating_point_equality",
        problem_id="sensor_calibration_match",
        fn_name="sensor_calibration_match",
        buggy_source=(
            "def sensor_calibration_match(reading_a, reading_b):\n"
            "    # readings from this instrument are typically in the range of 0.001-0.005 units\n"
            "    return reading_a == reading_b\n"
        ),
        test_source="",
        split="INVALID_C_ATTEMPT",
        problem_tags=["wrong-output", "runtime-bug"],
        capability_tags=["floating-point", "equality-check"],
    ),
    # shipment_weight_match DOES have a real canary check, unlike the two
    # above: unaided Expert, no skill, no formula, 3/3 reps -> produced
    # `math.isclose(weight_a, weight_b)` (rel_tol=1e-9 default), nothing
    # resembling 1e-6*magnitude and no engagement with the stated "400-600 kg"
    # range. Confirmed INVALID, not just unconfirmed.
    "shipment_weight_match": Task(
        task_id="floating_point_equality__shipment_weight_match__failed_canary_check",
        pattern_id="floating_point_equality",
        problem_id="shipment_weight_match",
        fn_name="shipment_weight_match",
        buggy_source=(
            "def shipment_weight_match(weight_a, weight_b):\n"
            "    # shipment weights recorded by this scale are typically in the range of 400-600 kilograms\n"
            "    return weight_a == weight_b\n"
        ),
        test_source="",
        split="INVALID_C_ATTEMPT",
        problem_tags=["wrong-output", "runtime-bug"],
        capability_tags=["floating-point", "equality-check"],
    ),
}
# 2026-08-18: 3 of 4 attempted no-hint domains (sensor readings, km distances,
# nm wavelength) failed the A-independently-derives-it validation check --
# only currency (a cent) passed. Read as its own finding: domains with a
# TRULY universal, human-derivable-without-any-number tolerance convention
# seem rare, not as a failure to find better test tasks. Worth remembering
# before assuming "a competent reasoner could obviously infer this" about any
# new domain -- check A first, same as here, rather than assume.
#
# 2026-08-19: the three magnitude-derivation domains above (instrument,
# sensor, shipment) bring the underdetermined-domain count found across this
# investigation to 6 of 8 attempted no-hint/formula-derivation domains -- see
# VALIDATED_C2_EXAMPLES below for the 2nd of 2 that survived scrutiny
# (currency, §5.3, and significant-figures-implied precision at low
# decimal-asymmetry + small nonzero numeric distance, confirmed the same day
# after a dedicated memorization-control round -- see module docstring
# FOLLOW-UP 3).


# 2026-08-19: a genuine SECOND validated CATEGORY_C domain for
# floating_point_equality (first since currency) -- significant-figures-
# implied precision, specifically at LOW decimal-asymmetry (1 vs 2 written
# decimals) with a SMALL NONZERO numeric distance between the two operands.
# Validated across two rounds: the original textbook-looking pair (7.2 vs
# 7.21, 3/4 exact `round(a,1)==round(b,1)`) and, decisively, three
# deliberately non-textbook pairs (13.7/13.68, 241.6/241.58, 89.4/89.37,
# 11/12 exact) -- ruling out memorization of a stock physics example, since
# the novel pairs converged MORE consistently, not less. See module
# docstring FOLLOW-UPS 1-3 for the full elimination of confounds (asymmetry
# vs raw distance) that preceded this. Kept in its own registry rather than
# CanarySet's single `c` slot (already occupied by invoice_totals_match) --
# this is a second, narrower validated sub-condition, not a replacement.
# test_source below reflects the validated round(x,1)==round(y,1) rule,
# using pairs actually tested above; NOT YET run against F/B/C or the
# ablation machinery -- that investment is a separate, deliberate decision.
VALIDATED_C2_EXAMPLES: dict[str, Task] = {
    "component_reading_matches": Task(
        task_id="floating_point_equality__component_reading_matches__validated_c2",
        pattern_id="floating_point_equality",
        problem_id="component_reading_matches",
        fn_name="component_reading_matches",
        buggy_source=(
            "def component_reading_matches(reading_a, reading_b):\n"
            "    # example usage: component_reading_matches(13.7, 13.68)\n"
            "    return reading_a == reading_b\n"
        ),
        test_source=(
            "def test_within_precision():\n"
            "    assert component_reading_matches(13.70, 13.68) is True\n\n"
            "def test_outside_precision():\n"
            "    assert component_reading_matches(13.70, 13.62) is False\n\n"
            "def test_exact():\n"
            "    assert component_reading_matches(13.70, 13.70) is True\n\n"
            "def test_larger_scale_within():\n"
            "    assert component_reading_matches(241.60, 241.58) is True\n\n"
            "def test_larger_scale_outside():\n"
            "    assert component_reading_matches(241.60, 241.50) is False\n"
        ),
        split="CATEGORY_C",
        problem_tags=["wrong-output", "runtime-bug"],
        capability_tags=["floating-point", "equality-check"],
    ),
}


def run_all(experiment_id: str = "canary") -> None:
    expert_adapter = build_adapter("expert")
    small_adapter = build_adapter("small")
    already_done = {(r["task_id"], r["config_name"]) for r in read_all(experiment_id)}

    for cset in CANARY_SETS.values():
        for task in (cset.a, cset.b, cset.c):
            if task is None:
                continue
            for cfg, adapter, use_librarian, use_cheater in (
                ("A", expert_adapter, False, False),
                ("B", small_adapter, False, False),
                ("F", small_adapter, True, False),
                ("C", small_adapter, False, True),
            ):
                if (task.task_id, cfg) in already_done:
                    continue
                record = run_quest(task, experiment_id, cfg, adapter, use_librarian=use_librarian, use_cheater=use_cheater)
                print(f"[canary] {cfg}  {task.split:12s}  {task.task_id}  passed={record.passed}")


def report(experiment_id: str = "canary") -> str:
    records = read_all(experiment_id)
    by_task_cfg = {(r["task_id"], r["config_name"]): r["passed"] for r in records}

    L = []
    L.append(f"# Canary matrix -- {experiment_id}")
    L.append("")
    L.append(
        "A = indizio esplicito (numero/percentuale dichiarati). B = dominio "
        "riconoscibile ma nessun numero (puo' comunque contenere un indizio "
        "residuo, es. un'unita' di misura nel nome -- vedi note per task). "
        "C = nessun indizio di alcun tipo. Una riga C uniforme su A/B/F/C "
        "(tutti falliscono uguale) mostra un task difficile per chiunque, non "
        "che lo skill di F peggiori il baseline -- guarda il delta F-vs-B "
        "sulla stessa riga, non il PASS/FAIL di F da solo."
    )
    L.append("")
    L.append("| pattern | config | A | B | C |")
    L.append("|---|---|---|---|---|")
    for pattern_id, cset in CANARY_SETS.items():
        for cfg in CONFIGS:
            def _cell(task):
                if task is None:
                    return "n/a"
                v = by_task_cfg.get((task.task_id, cfg))
                return "n/d" if v is None else ("PASS" if v else "FAIL")
            L.append(f"| `{pattern_id}` | {cfg} | {_cell(cset.a)} | {_cell(cset.b)} | {_cell(cset.c)} |")
        if cset.b_note:
            L.append(f"\n> B note (`{pattern_id}`): {cset.b_note}\n")
        if cset.c_note:
            L.append(f"> C note (`{pattern_id}`): {cset.c_note}\n")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    experiment_id = sys.argv[1] if len(sys.argv) > 1 else "canary"
    run_all(experiment_id)
    print()
    print(report(experiment_id))
