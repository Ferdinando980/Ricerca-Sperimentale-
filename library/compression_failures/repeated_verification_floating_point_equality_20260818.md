# Repeated verification: floating_point_equality compressibility

Investigative follow-up to two rejected compressions in `experiment1`
(`book_floating_point_equality` and `book_floating_point_equality_v2`, both
rejected 1/2 vs 2/2 by the optimizer). Question: is a single compress+verify
sample enough to call a skill "hard to compress", or is that noise?

Method: for each Book, repeated **compress (1 call) + verify original on both
known tasks (2 calls) + verify the fresh compression on both tasks (2 calls)**
6 times, model = `gemini-3.1-flash-lite` (same as produced the original
rejection). Tasks: `floating_point_equality__average_matches_target__known_example`,
`floating_point_equality__temperature_reached__variant`.

## book_floating_point_equality (v3 -- the manually-fixed version)

| rep | originale | compresso | parole compresso |
|---|---|---|---|
| 1 | 2/2 | 2/2 | 107 |
| 2 | 2/2 | 2/2 | 117 |
| 3 | 2/2 | 2/2 | 118 |
| 4 | 2/2 | 1/2 (fail: temperature_reached) | 122 |
| 5 | 2/2 | 1/2 (fail: temperature_reached) | 97 |
| 6 | 2/2 | 2/2 | 104 |

**Totale: originale 12/12 (100%), compresso 10/12 (83%).**

The original never fails across 6 reps. The compressed version fails on
exactly one task, `temperature_reached`, in 2 of 6 attempts -- never on
`average_matches_target`. That's the task whose fix requires the more
elaborate part of the procedure (the concrete "sensor reading tolerance"
example with numbers, added when this Book was hand-fixed on 2026-08-18).
A real, partial, task-specific information loss under compression -- not
random noise (it's concentrated on one task every time it happens) and not
a total failure either (4 of 6 compressions preserve it fine).

## book_floating_point_equality_v2 (v2 -- pre-fix compressed Book)

| rep | originale | compresso |
|---|---|---|
| 1 | 1/2 (fail: temperature_reached) | 1/2 (fail: temperature_reached) |
| 2 | 1/2 (fail: temperature_reached) | 1/2 (fail: temperature_reached) |
| 3 | 1/2 (fail: temperature_reached) | 1/2 (fail: temperature_reached) |
| 4 | 1/2 (fail: temperature_reached) | 1/2 (fail: temperature_reached) |
| 5 | 1/2 (fail: temperature_reached) | 1/2 (fail: temperature_reached) |
| 6 | 1/2 (fail: temperature_reached) | 1/2 (fail: temperature_reached) |

**Totale: originale 6/12 (50%), compresso 6/12 (50%) -- identici.**

No compression effect here at all: the original itself deterministically
fails `temperature_reached` in all 6 reps (it never had the epsilon-tolerance
guidance that v3 added). This retroactively confirms the original diagnosis
(epsilon too tight, not a `min()`-on-empty crash) with 6 independent samples
instead of 1, and confirms compression was never the variable in play for
this specific Book version.

## Reading

- One sample is not enough to call a compression "systematically worse" --
  book_floating_point_equality's compression looked like a clean reject
  (1/2 vs 2/2) on the single sample the optimizer took, but 6 reps show it's
  really 83% vs 100%, i.e. a real but partial effect, not a hard wall.
- The failure is concentrated on the task requiring the more elaborate,
  example-heavy part of the procedure -- consistent with the hypothesis that
  multi-step / nuanced numerical-reasoning guidance compresses less reliably
  than a single canonical pattern-match rule. Only one pattern tested so far;
  this is a first data point toward the "compressibility taxonomy" idea, not
  a conclusion.
