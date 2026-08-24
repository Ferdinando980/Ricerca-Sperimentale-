"""Shared aggregation helpers over log.jsonl/events.jsonl records, extracted
from recap.py (Phase 1 of the library evolution plan, conversation
2026-08-18) so knowledge_map.py can reuse them instead of duplicating them.
Lives in experiment/, not library/, because the existing dependency
direction in this codebase is experiment/ -> library/ (recap.py already
imports library.loader) -- these functions read log/event records, which are
an experiment/ concern, not a library one.

Nothing here is new logic: every function is a straight move from recap.py,
same behavior, just with the leading underscore dropped since they're now
public API shared by more than one caller.
"""

from collections import defaultdict

from ..library.loader import id_to_pattern_map

CONFIGS = ["A", "B", "F", "C"]


def overall(records):
    by = defaultdict(lambda: {"n": 0, "passed": 0, "cost": 0.0, "latency": 0.0})
    for r in records:
        b = by[r["config_name"]]
        b["n"] += 1
        b["passed"] += int(r["passed"])
        b["cost"] += r["cost_usd"]
        b["latency"] += r["latency_ms"]
    return by


def by_config_coverage(records):
    """Accuracy grouped by (config_name, coverage) -- coverage is NONE/
    PARTIAL/FULL for any config that goes through a retrieval step (F via
    librarian.route(), C via cheater/solution_bank.route()) and "N/A" for A/B
    (no retrieval at all). Every LogRecord already carries this (quest_runner
    passes skill_package.coverage into new_record()) -- this just aggregates
    what's already persisted, no new measurement.

    This isolates the question raised in conversation 2026-08-18: is it
    retrieval itself moving F's accuracy, or does the mere presence of the
    Librarian/Cheater mechanism do nothing when it finds nothing (coverage
    NONE)? If F-NONE looks like B and F-FULL beats B, that's a cleaner
    demonstration than "F vs B" alone -- it separates "having the retrieval
    machinery" from "actually retrieving something relevant"."""
    by = defaultdict(lambda: {"n": 0, "passed": 0})
    for r in records:
        cov = r.get("coverage", "N/A")
        b = by[(r["config_name"], cov)]
        b["n"] += 1
        b["passed"] += int(r["passed"])
    return by


def by_config_split(records):
    by = defaultdict(lambda: {"n": 0, "passed": 0, "cost": 0.0, "latency": 0.0})
    for r in records:
        b = by[(r["config_name"], r["split"])]
        b["n"] += 1
        b["passed"] += int(r["passed"])
        b["cost"] += r["cost_usd"]
        b["latency"] += r["latency_ms"]
    return by


def token_accounting(records):
    """Per-config input/output/reasoning token totals -- separate from cost_usd
    (which is $0 whenever GEMINI_*_PER_MTOK isn't set) so token usage stays
    readable even when pricing is unconfigured. reasoning_output_tokens is
    Gemini's "thoughts" token count -- billed, but never inside output_tokens
    (see gemini_adapter.py), so it's kept as its own column rather than
    silently folded into "output"."""
    by = defaultdict(lambda: {"n": 0, "input": 0, "output": 0, "reasoning": 0})
    for r in records:
        b = by[r["config_name"]]
        b["n"] += 1
        b["input"] += r["input_tokens"]
        b["output"] += r["output_tokens"]
        b["reasoning"] += r["reasoning_output_tokens"] or 0
    return by


def librarian_overhead(records):
    """F vs B input-token delta on the SAME task_id -- both run on the Small
    model with the same base prompt, so any difference is the skill text the
    Librarian injected for F, isolated from anything else that varies between
    configs (model, reasoning, task difficulty). Moved here from recap.py
    (2026-08-24) so readme_update.py can reuse the exact same computation
    instead of re-deriving it and risking the two reports disagreeing."""
    input_by_task_cfg = {(r["task_id"], r["config_name"]): r["input_tokens"] for r in records}
    diffs = []
    for (task_id, cfg), inp in input_by_task_cfg.items():
        if cfg != "F":
            continue
        b_inp = input_by_task_cfg.get((task_id, "B"))
        if b_inp is not None:
            diffs.append(inp - b_inp)
    return diffs


def mixed_provider_warnings(records, configs=CONFIGS):
    """Flags configs that used more than one (provider, model) pair within the
    SAME experiment_id -- e.g. a run started on the AI Studio "gemini" provider
    and finished on "gemini_vertex" after a mid-run config change (found
    2026-08-18: experiment2 switched providers at quest 41/104 when Vertex AI
    was set up). Not wrong by itself, but a real confound if these numbers get
    cited formally -- worth surfacing automatically instead of discovering it
    by hand in the logs each time. Shared by recap.py and thesis_doc.py."""
    combos_by_cfg = defaultdict(set)
    for r in records:
        combos_by_cfg[r["config_name"]].add((r["provider"], r["model"]))
    warnings = []
    for cfg in configs:
        combos = combos_by_cfg.get(cfg)
        if combos and len(combos) > 1:
            desc = ", ".join(f"{p}/{m}" for p, m in sorted(combos))
            warnings.append(f"- **{cfg}**: {desc}")
    return warnings


def retrieval_waste_analysis(records):
    """Counterfactual check (2026-08-19, prompted by external review): zero
    new model calls, reuses records already on disk. For every quest where F
    had a skill injected (coverage FULL/PARTIAL), checks whether B (same
    task_id, no skill, same experiment) ALSO passed -- if so, the injected
    skill context didn't change the measured outcome on that quest, and the
    retrieval-overhead tokens spent (F's input_tokens minus B's) bought
    nothing observable by this proxy. Same quest-by-quest discipline applied
    to accuracy all day (§4's canary criterion), applied here to cost.

    Returns a dict: n_injected, n_waste, n_hurt, n_helped, n_neither,
    wasted_tokens, helped_patterns (set of pattern_ids with >=1 real HELPED
    instance -- the only patterns whose skill has ever demonstrated value by
    this measure). Across all 4 real experiments run in this investigation
    (2026-08-19): 75 injected quests, 61 WASTE (81.3%), 3 HURT (all the
    already-known temperature_reached benchmark defect, not a new finding),
    10 HELPED, 1 NEITHER -- and only 2 of 13 patterns (floating_point_
    equality, wrong_string_case_comparison) ever produced a HELPED instance.
    """
    by_task = defaultdict(dict)
    for r in records:
        by_task[r["task_id"]][r["config_name"]] = r

    n_injected = n_waste = n_hurt = n_helped = n_neither = wasted_tokens = 0
    helped_patterns = set()
    for task_id, cfgs in by_task.items():
        f, b = cfgs.get("F"), cfgs.get("B")
        if f is None or b is None or f["coverage"] not in ("FULL", "PARTIAL"):
            continue
        n_injected += 1
        overhead = max(f["input_tokens"] - b["input_tokens"], 0)
        if b["passed"] and f["passed"]:
            n_waste += 1
            wasted_tokens += overhead
        elif b["passed"] and not f["passed"]:
            n_hurt += 1
        elif not b["passed"] and f["passed"]:
            n_helped += 1
            helped_patterns.add(task_id.split("__")[0])
        else:
            n_neither += 1

    return {
        "n_injected": n_injected, "n_waste": n_waste, "n_hurt": n_hurt,
        "n_helped": n_helped, "n_neither": n_neither,
        "wasted_tokens": wasted_tokens, "helped_patterns": helped_patterns,
    }


_KNOWN_BENCHMARK_DEFECTS = {
    "floating_point_equality__temperature_reached__variant": (
        "A/B's recorded PASS on this task does not mean they derived a correct "
        "tolerance: both write `any(r >= target for r in readings)` (no epsilon "
        "at all), which is wrong vs. the true correct_source (fails a reading "
        "just under target within tolerance -- verified 2026-08-19). "
        "bug_catalog.py's own test suite for this task never covers that case, "
        "so this has passed as correct in every run that includes it. See "
        "experiment/canary.py for the investigation."
    ),
}


def benchmark_defect_warnings(records):
    """Flags task_ids present in these records with a KNOWN, verified defect in
    the benchmark itself (task/test authoring, not the config being measured)
    -- so a reader of aggregate accuracy tables doesn't inherit a false reading
    from a PASS/FAIL that doesn't mean what it looks like it means. Keep this
    list to defects that were actually verified (a concrete counter-example
    checked against correct_source), not suspicions."""
    present = {r["task_id"] for r in records} & set(_KNOWN_BENCHMARK_DEFECTS)
    return [(tid, _KNOWN_BENCHMARK_DEFECTS[tid]) for tid in sorted(present)]


_KNOWN_SKILL_FINDINGS = {
    "floating_point_equality": (
        "F's epsilon on a no-hint task is NOT derived from the task's scale -- "
        "causally demonstrated (not just observed), 2026-08-19: manipulating "
        "the skill's tier-c fallback constant (1e-9 -> 2.5e-6 -> 7e-4) changed "
        "F's answer in lockstep, 12/12 runs across 2 unrelated no-hint tasks, "
        "while manipulating the unrelated tier-b (currency) constant changed "
        "nothing (0 leakage, 6/6 runs) -- and the reverse check also held: "
        "changing tier-c did not touch F's tier-b (currency) answer either, "
        "3/3 runs. F correctly selects which tier applies, but performs no "
        "scale-sensitive reasoning within tier-c -- it substitutes that tier's "
        "literal constant verbatim. This is not 'reciting an example' in the "
        "loose sense (no semantic choice between multiple examples in the "
        "text) -- it is mechanical substitution of a single designated slot. "
        "See experiment/canary.py and the skill's own YAML changelog for the "
        "full ablation. Any accuracy number for F on this pattern's no-hint "
        "cases should be read with this in mind, not as evidence of context-"
        "sensitive reasoning.\n"
        "REFINEMENT 2026-08-19 (staged probing + rule-substitution test): the "
        "finding above is about faithfully following THIS skill's literal-"
        "constant instruction, not a capability ceiling. Asking F, outside the "
        "skill text, to (1) name the property that should determine epsilon "
        "and (2) compute epsilon given that property's value handed to it "
        "directly -- F still answered the skill's literal 1e-9 both times, "
        "ignoring the given value entirely: it does not spontaneously invent "
        "a grounding strategy the skill didn't authorize. But rewriting tier-c "
        "ITSELF to require deriving epsilon from a stated magnitude (instead "
        "of a literal constant) made F actually perform the derivation -- "
        "correctly tracking magnitude across a ~1e7 range in two replications "
        "(200-300 units -> ~1e-4; 0.001-0.005 units -> exactly 5e-9), with one "
        "minor arithmetic slip in the first case (used 1e-4 instead of the "
        "correct 2.5e-4). Net picture: F reliably APPLIES whatever rule tier-c "
        "states -- literal substitution if told to substitute, genuine (if "
        "not perfectly precise) scale-derivation if told to derive -- but "
        "does not initiate derivation on its own when the operative rule is a "
        "literal constant. The bottleneck is instruction content, not model "
        "capability.\n"
        "VALIDATION 2026-08-19 (delegated-arithmetic tier-c, not yet live): "
        "the one arithmetic slip in the refinement above (1e-4 instead of "
        "2.5e-4) is a known LLM weakness -- silent token-by-token arithmetic, "
        "not unreliable scale-tracking -- so a tier-c wording was tested that "
        "asks F to extract the stated magnitude into a variable and write "
        "epsilon as an INTERPRETER-EVALUATED EXPRESSION (e.g. `epsilon = 1e-6 "
        "* typical_magnitude`) instead of hand-computing and hardcoding the "
        "final number. Validated on 7 runs across 5 tasks: the two original "
        "magnitude domains (200-300 units, 0.001-0.005 units) now produce a "
        "correct expression with no arithmetic to get wrong; a THIRD domain "
        "never used to write the rule (400-600 kg shipment weights) generalized "
        "correctly on first try (typical_magnitude=500, epsilon=1e-6*500); both "
        "genuinely no-magnitude tasks (sensor_readings_agree x2, "
        "same_destination x1) still correctly fell back to the untouched "
        "literal 1e-9 default, not a hallucinated expression -- selectivity "
        "between 'derive' and 'no basis to derive, use the safe default' held "
        "5/5; and the currency tier-b task was unaffected (still 0.01, 1/1). "
        "Not yet adopted as the live procedure_text -- this is a validated "
        "research result, deployment is a separate, deliberate decision "
        "(consistent with two failed rewrite attempts earlier in this same "
        "investigation). Also note the cost tradeoff this rule trades into: "
        "reasoning through a derivation costs more tokens per call than blind "
        "literal substitution, moving F's per-task cost toward (not to) "
        "Expert's -- see the token-accounting figures elsewhere in this report.\n"
        "CORRECTION 2026-08-19 (the 'third domain' claim above, overclaimed): "
        "'F generalizes to shipment_weight_match' was graded against 1e-6 * "
        "stated_magnitude -- the same formula the same investigator wrote "
        "into the rule, same session. That checks rule-application fidelity, "
        "not whether 1e-6*magnitude is an objectively correct real-world "
        "tolerance. Applying the canary check that already invalidated 3 of "
        "4 CATEGORY_C domains: does unaided Expert independently converge "
        "near the same answer? No -- 3/3 reps, Expert produces "
        "`math.isclose(weight_a, weight_b)` (rel_tol=1e-9 default, essentially "
        "machine-precision equality), nothing near 1e-6*magnitude, no real "
        "engagement with the stated range. shipment_weight_match does NOT "
        "pass canary validation -- it joins the underdetermined bucket, not "
        "the validated-answer bucket. The same caveat applies retroactively "
        "to the two original magnitude domains (instrument, sensor) that "
        "built the rule -- never independently canary-checked either. What "
        "survives: F reliably applies an explicit formula to unseen data "
        "(mechanically verifiable, Category-A-like). What does not survive: "
        "any claim that 1e-6*magnitude is a validated convention -- it is as "
        "author-arbitrary as any other constant flagged in this investigation.\n"
        "RESOLUTION 2026-08-19 (a genuine second CATEGORY_C domain, found and "
        "confirmed with F, the sharpest positive result in this chapter): "
        "unlike shipment_weight_match, significant-figures-implied precision "
        "(low decimal-asymmetry, small nonzero numeric distance -- e.g. 13.7 "
        "vs 13.68) WAS independently validated -- unaided Expert converges on "
        "`round(x,1)==round(y,1)` 11/12 times across 3 deliberately "
        "non-textbook pairs (ruling out memorization of a stock physics "
        "example: novel pairs converged MORE consistently than the original "
        "7.2/7.21, 92% vs 75% -- the opposite of what memorization predicts). "
        "F was then tested with two decimal structures at once (1v2 decimals "
        "-> expected eps 0.05; 2v3 decimals -> expected eps 0.005) crossed "
        "with skill condition: baseline (sig-figs not in tier-b) fell to "
        "tier-c's 1e-9 (3/3) or misfired to currency's 0.01 by loose semantic "
        "association with 'dial' (2/3 on the 2v3 task, a THIRD failure type "
        "this chapter hadn't catalogued -- generalization via surface word "
        "similarity, not blind substitution and not correct derivation) -- "
        "neither correct; a research "
        "variant adding sig-figs as a second tier-b convention got 6/6 "
        "correct, AND -- decisively -- produced DIFFERENT epsilon values per "
        "task (0.05 vs 0.005), each correctly scaled to that task's own "
        "decimal structure, with the reasoning written out. A single "
        "memorized-constant substitution mechanism cannot produce two "
        "different, each-independently-correct numbers -- this is the first "
        "clean resolution of recitation-vs-derivation in this chapter on a "
        "domain confirmed not to be a lucky-scale coincidence (unlike "
        "currency's 0.01, which was never tested against a case requiring a "
        "different magnitude). Not adopted as live procedure_text -- same "
        "deliberate-deployment-decision principle as the delegated-arithmetic "
        "result above. FOLLOW-UP (same day): the 2v3-decimal structure used "
        "in the F test had never itself been independently checked on A "
        "(every prior A-validation used 1v2 decimals) -- lower risk than "
        "shipment_weight_match since the formula (0.5*10^-d) was already "
        "validated, extending it to a new d is not a fresh guess -- but "
        "closed anyway: 4/4 exact on a fresh 2v3 pair, independent of the F "
        "test's own task. See experiment/canary.py FOLLOW-UPS 1-5 for the "
        "full elimination of confounds that preceded this."
    ),
}


def skill_finding_warnings(records, tasks_by_id):
    """Same idea as benchmark_defect_warnings, but for a verified (causally
    demonstrated, not just suspected) finding about a SKILL's behavior rather
    than a defect in the task/test authoring -- keyed by pattern_id since the
    finding applies to the whole pattern's no-hint behavior, not one task_id.
    Only fires for the F config, since the finding is about the Librarian-
    injected skill's mechanism specifically."""
    patterns_seen = {
        pattern_of(r["task_id"], tasks_by_id)
        for r in records if r["config_name"] == "F"
    }
    present = patterns_seen & set(_KNOWN_SKILL_FINDINGS)
    return [(p, _KNOWN_SKILL_FINDINGS[p]) for p in sorted(present)]


def pattern_of(task_id, tasks_by_id):
    t = tasks_by_id.get(task_id)
    return t.pattern_id if t else task_id.split("__")[0]


def skill_usage(events, records):
    passed_by_quest = {(r["task_id"], r["config_name"]): r["passed"] for r in records}
    usage = defaultdict(lambda: {"n": 0, "tokens": [], "quests": []})
    for e in events:
        if e["event_type"] != "RETRIEVAL_RESULT":
            continue
        for skill_id in e["data"].get("skill_ids", []):
            u = usage[skill_id]
            u["n"] += 1
            u["tokens"].append(e["data"].get("skill_context_tokens", 0))
            u["quests"].append((e["task_id"], e["config_name"]))

    result = {}
    for skill_id, u in usage.items():
        passed = sum(1 for q in u["quests"] if passed_by_quest.get(q))
        result[skill_id] = {
            "n": u["n"],
            "avg_tokens": sum(u["tokens"]) / len(u["tokens"]) if u["tokens"] else 0.0,
            "passed": passed,
        }
    return result


def skill_amortization(events, records, build_cost_events=None):
    """Per bug-pattern (not per exact skill_id -- a skill's id changes when the
    Optimizer compresses it, e.g. book_X -> book_X_v2, so joining construction
    cost to usage has to go through pattern_id or an accepted compression's
    build cost would silently stop counting against its own usage). For each
    pattern: total tokens spent by the Optimizer building/compressing it so
    far (any attempt, accepted or not -- real cost either way), against the
    average per-task token saving F gets over A specifically on the tasks
    that pattern's Book(s) were actually used for. saving_per_use <= 0 means
    the Librarian never pays for itself against Expert on this pattern with
    the data seen so far, regardless of how many more times it's used.

    build_cost_events defaults to `events` (this experiment_id only) for
    back-compat, but callers should pass events.read_events_all_experiments()
    instead: the library is shared across every experiment_id, so a pattern
    compressed once (e.g. during experiment0) and merely reused later (e.g.
    during experiment2, not recompressed) must still show its real
    construction cost in experiment2's report, not $0 (found 2026-08-18)."""
    if build_cost_events is None:
        build_cost_events = events
    # live + archived (see library/loader.py) -- an id can be referenced by
    # historical events even after its Book file was moved out of the live
    # library as a confirmed duplicate.
    books_by_id = id_to_pattern_map()

    build_cost = defaultdict(int)
    for e in build_cost_events:
        if e["event_type"] in ("SKILL_COMPRESSION_FINISHED", "SKILL_REVERIFICATION"):
            pattern = books_by_id.get(e["data"].get("skill_id"))
            if pattern:
                build_cost[pattern] += e["data"].get("input_tokens", 0) + e["data"].get("output_tokens", 0)

    tasks_by_pattern = defaultdict(set)
    for e in events:
        if e["event_type"] == "RETRIEVAL_RESULT":
            for skill_id in e["data"].get("skill_ids", []):
                pattern = books_by_id.get(skill_id)
                if pattern:
                    tasks_by_pattern[pattern].add(e["task_id"])

    tok_by_task_cfg = defaultdict(int)
    for r in records:
        tok_by_task_cfg[(r["task_id"], r["config_name"])] = (
            r["input_tokens"] + r["output_tokens"] + (r["reasoning_output_tokens"] or 0)
        )

    rows = []
    for pattern, cost in sorted(build_cost.items()):
        task_ids = tasks_by_pattern.get(pattern, set())
        a_vals = [tok_by_task_cfg[(t, "A")] for t in task_ids if (t, "A") in tok_by_task_cfg]
        f_vals = [tok_by_task_cfg[(t, "F")] for t in task_ids if (t, "F") in tok_by_task_cfg]
        if not a_vals or not f_vals:
            continue
        a_avg = sum(a_vals) / len(a_vals)
        f_avg = sum(f_vals) / len(f_vals)
        saving = a_avg - f_avg
        breakeven = cost / saving if saving > 0 else None
        rows.append({
            "pattern": pattern, "build_cost": cost, "n_tasks": len(task_ids),
            "a_avg": a_avg, "f_avg": f_avg, "saving": saving, "breakeven": breakeven,
        })
    return rows
