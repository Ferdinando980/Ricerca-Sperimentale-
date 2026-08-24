"""Section taxonomy for the Skill Library (Phase 1 of the library evolution
plan, conversation 2026-08-18: PROJECT -> SECTION -> SKILL hierarchy). Pure
data, read by knowledge_map.py -- does not touch Book, the loader, or any
YAML file on disk.

Deliberately hand-curated, not clustered/embedded: at 13 total bug patterns,
any statistical grouping would be overfitting by construction (the same
"need 50-100 data points before a taxonomy is trustworthy" problem raised in
conversation about compressibility patterns, one level up). Each assignment
below is grounded in the pattern's real capability_tags from
domain/bug_catalog.py -- not an invented category name -- with a comment
explaining why. Revisit with real clustering only once the catalog is much
bigger.

Keyed by pattern_id, not by Book.id/version: every Book version for a given
pattern_id (original, compressed, re-compressed...) shares one section by
definition. Putting this on Book instead would risk exactly the kind of
disagreement the on-disk version proliferation already shows (e.g.
book_index_out_of_range_boundary_v2.yaml vs ..._v2_v3.yaml) -- a dict has
one answer, always.
"""

SECTIONS: dict[str, dict] = {
    "boundary_conditions": {
        "title": "Boundary Conditions",
        "rationale": (
            "Patterns whose capability_tags name an explicit boundary/edge: "
            "off-by-one, loop-bounds, comparison-operator, boundary-condition, "
            "index-boundary, slicing, premature-return, control-flow."
        ),
    },
    "numerical_computing": {
        "title": "Numerical Computing",
        "rationale": (
            "Patterns whose capability_tags are about numeric value semantics "
            "rather than control flow: floating-point, equality-check, "
            "integer-division, type-error."
        ),
    },
    "loop_state": {
        "title": "Loop State & Accumulation",
        "rationale": (
            "Patterns whose capability_tags concern state carried across loop "
            "iterations: accumulator-init, loop-state."
        ),
    },
    "language_semantics": {
        "title": "Python Language Semantics",
        "rationale": (
            "Patterns whose capability_tags are Python-specific gotchas or "
            "scoping rules, not algorithmic: mutable-default-argument, "
            "python-gotcha, variable-shadowing, scoping."
        ),
    },
    "boolean_logic": {
        "title": "Boolean Logic",
        "rationale": "capability_tags: boolean-logic, and-or-confusion.",
    },
    "data_ordering": {
        "title": "Data Ordering",
        "rationale": "capability_tags: sorting, ordering.",
    },
    "data_structures": {
        "title": "Data Structures",
        "rationale": "capability_tags: missing-key-check, dict-access. Added 2026-08-18.",
    },
    "string_processing": {
        "title": "String & Text Processing",
        "rationale": "capability_tags: case-sensitivity, string-comparison. Added 2026-08-18.",
    },
}

# pattern_id -> section_id. All 11 patterns from domain/bug_catalog.py,
# including the 3 permanently-NOVEL ones (they still need a section to
# report EMPTY coverage against).
PATTERN_SECTION: dict[str, str] = {
    "off_by_one": "boundary_conditions",
    "wrong_comparison_operator": "boundary_conditions",
    "index_out_of_range_boundary": "boundary_conditions",
    "wrong_return_in_loop": "boundary_conditions",
    "floating_point_equality": "numerical_computing",
    "integer_division_truncation": "numerical_computing",
    "wrong_accumulator_init": "loop_state",
    "mutable_default_argument": "language_semantics",
    "variable_shadowing": "language_semantics",
    "inverted_boolean_logic": "boolean_logic",
    "incorrect_sort_key_or_order": "data_ordering",
    "key_error_missing_dict_check": "data_structures",
    "wrong_string_case_comparison": "string_processing",
}

# pattern_id -> False for the 3 patterns that must NEVER get an
# auto-generated Book: they're the experiment's permanent NOVEL control
# group by explicit original design (domain/bug_catalog.py comment: "Do not
# add a Book for these"). A comment doesn't stop code -- this makes the
# constraint checkable, for whenever a Skill Generator phase exists.
# Not read anywhere yet in Phase 1; recorded now because this is the module
# that will own it, not because anything needs it today.
GENERATION_ELIGIBLE: dict[str, bool] = {
    pattern_id: pattern_id not in ("variable_shadowing", "incorrect_sort_key_or_order", "wrong_return_in_loop")
    for pattern_id in PATTERN_SECTION
}


def section_of(pattern_id: str) -> str | None:
    return PATTERN_SECTION.get(pattern_id)


def patterns_in_section(section_id: str) -> list[str]:
    return [p for p, s in PATTERN_SECTION.items() if s == section_id]


def all_sections() -> list[str]:
    return list(SECTIONS.keys())
