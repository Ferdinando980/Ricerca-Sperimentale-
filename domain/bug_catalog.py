"""Seed content for MVP-0/1: reference implementations, bug patterns, and hand-authored
buggy variants. See §J of the Cognitive RPG design review for the KNOWN/VARIANT/NOVEL
split logic -- this file supplies the raw material; task_generator.py assigns the split
by cross-referencing which patterns have a Book in the library.

This is a small seed set (18 problems, 13 patterns, 39 task instances as of
2026-08-19's experiment4 -- 2 patterns added 2026-08-18 as legitimate
coverage gaps, see library/sections.py's GENERATION_ELIGIBLE; 13 more added
2026-08-19 reusing existing problem_ids to raise n per pattern, see the
comment above that block), still not the 150-300 task benchmark the review
recommends for a fully-powered real experiment, but no longer the original
flat n=2 per pattern either.
"""

BASE_PROBLEMS = {
    "is_palindrome": {
        "fn_name": "is_palindrome",
        "correct_source": '''def is_palindrome(s):
    s = s.lower()
    return s == s[::-1]
''',
        "test_source": '''def test_basic():
    assert is_palindrome("racecar") is True

def test_case_insensitive():
    assert is_palindrome("RaceCar") is True

def test_false():
    assert is_palindrome("hello") is False

def test_empty():
    assert is_palindrome("") is True
''',
    },
    "binary_search": {
        "fn_name": "binary_search",
        "correct_source": '''def binary_search(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''',
        "test_source": '''def test_found_middle():
    assert binary_search([1, 3, 5, 7, 9], 5) == 2

def test_found_edges():
    assert binary_search([1, 3, 5, 7, 9], 1) == 0
    assert binary_search([1, 3, 5, 7, 9], 9) == 4

def test_not_found():
    assert binary_search([1, 3, 5, 7, 9], 4) == -1

def test_empty():
    assert binary_search([], 1) == -1
''',
    },
    "flatten_list": {
        "fn_name": "flatten_list",
        "correct_source": '''def flatten_list(nested):
    result = []
    for item in nested:
        if isinstance(item, list):
            result.extend(item)
        else:
            result.append(item)
    return result
''',
        "test_source": '''def test_mixed():
    assert flatten_list([1, [2, 3], 4, [5]]) == [1, 2, 3, 4, 5]

def test_no_nesting():
    assert flatten_list([1, 2, 3]) == [1, 2, 3]

def test_empty():
    assert flatten_list([]) == []

def test_independent_calls_dont_share_state():
    # Added 2026-08-19: same reasoning as dedupe_preserve_order's version of
    # this test -- the 3 tests above only caught the mutable-default bug as a
    # side effect of pytest's sequential execution, not by design; each
    # passes the buggy version alone in isolation. This one is self-contained.
    first = flatten_list([1, 2])
    second = flatten_list([3, 4])
    assert second == [3, 4]
''',
    },
    "dedupe_preserve_order": {
        "fn_name": "dedupe_preserve_order",
        "correct_source": '''def dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
''',
        "test_source": '''def test_dedupe():
    assert dedupe_preserve_order([3, 1, 3, 2, 1]) == [3, 1, 2]

def test_no_dupes():
    assert dedupe_preserve_order([1, 2, 3]) == [1, 2, 3]

def test_empty():
    assert dedupe_preserve_order([]) == []

def test_independent_calls_dont_share_state():
    # Added 2026-08-19: the 3 tests above only ever caught the classic
    # mutable-default-argument bug as a side effect of pytest running them
    # in sequence within one process (state leaking test-to-test) -- verified
    # each one individually PASSES the buggy version when run in isolation
    # (pytest file.py::test_name alone, fresh process). This test is self-
    # contained -- both calls happen inside the same test function, so it
    # catches the bug regardless of test execution order.
    first = dedupe_preserve_order([1, 2, 3])
    second = dedupe_preserve_order([4, 5])
    assert second == [4, 5]
''',
    },
    "merge_intervals": {
        "fn_name": "merge_intervals",
        "correct_source": '''def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda iv: iv[0])
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return merged
''',
        "test_source": '''def test_overlapping():
    assert merge_intervals([[1, 3], [2, 6], [8, 10]]) == [[1, 6], [8, 10]]

def test_touching():
    assert merge_intervals([[1, 4], [4, 5]]) == [[1, 5]]

def test_disjoint():
    assert merge_intervals([[1, 2], [4, 5]]) == [[1, 2], [4, 5]]

def test_empty():
    assert merge_intervals([]) == []

def test_out_of_start_order():
    assert merge_intervals([[5, 6], [1, 10]]) == [[1, 10]]
''',
    },
    "run_length_encode": {
        "fn_name": "run_length_encode",
        "correct_source": '''def run_length_encode(s):
    if not s:
        return ""
    result = []
    count = 1
    for i in range(1, len(s)):
        if s[i] == s[i - 1]:
            count += 1
        else:
            result.append(s[i - 1] + str(count))
            count = 1
    result.append(s[-1] + str(count))
    return "".join(result)
''',
        "test_source": '''def test_basic():
    assert run_length_encode("aaabbc") == "a3b2c1"

def test_single_char():
    assert run_length_encode("aaaa") == "a4"

def test_no_repeats():
    assert run_length_encode("abc") == "a1b1c1"

def test_empty():
    assert run_length_encode("") == ""
''',
    },
    "rolling_average": {
        "fn_name": "rolling_average",
        "correct_source": '''def rolling_average(nums, window):
    result = []
    for i in range(len(nums) - window + 1):
        chunk = nums[i:i + window]
        result.append(sum(chunk) / window)
    return result
''',
        "test_source": '''def test_basic():
    assert rolling_average([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]

def test_window_equals_length():
    assert rolling_average([2, 4, 6], 3) == [4.0]

def test_window_one():
    assert rolling_average([1, 2, 3], 1) == [1.0, 2.0, 3.0]
''',
    },
    "count_vowels": {
        "fn_name": "count_vowels",
        "correct_source": '''def count_vowels(s):
    vowels = set("aeiouAEIOU")
    count = 0
    for ch in s:
        if ch in vowels:
            count += 1
    return count
''',
        "test_source": '''def test_basic():
    assert count_vowels("hello world") == 3

def test_none():
    assert count_vowels("xyz") == 0

def test_empty():
    assert count_vowels("") == 0

def test_mixed_case():
    assert count_vowels("AEIOUaeiou") == 10
''',
    },
    "reverse_words": {
        "fn_name": "reverse_words",
        "correct_source": '''def reverse_words(s):
    words = s.split()
    result = []
    for w in reversed(words):
        result.append(w)
    return " ".join(result)
''',
        "test_source": '''def test_basic():
    assert reverse_words("the quick fox") == "fox quick the"

def test_single_word():
    assert reverse_words("hello") == "hello"

def test_empty():
    assert reverse_words("") == ""
''',
    },
    "sum_digits": {
        "fn_name": "sum_digits",
        "correct_source": '''def sum_digits(n):
    total = 0
    n = abs(n)
    while n > 0:
        total += n % 10
        n //= 10
    return total
''',
        "test_source": '''def test_basic():
    assert sum_digits(1234) == 10

def test_zero():
    assert sum_digits(0) == 0

def test_negative():
    assert sum_digits(-56) == 11
''',
    },
    "is_valid_password": {
        "fn_name": "is_valid_password",
        "correct_source": '''def is_valid_password(s):
    return (
        len(s) >= 8
        and any(c.isdigit() for c in s)
        and any(c.isupper() for c in s)
    )
''',
        "test_source": '''def test_valid():
    assert is_valid_password("Abcdefg1") is True

def test_no_upper():
    assert is_valid_password("abcdefg1") is False

def test_no_digit():
    assert is_valid_password("Abcdefgh") is False

def test_too_short():
    assert is_valid_password("Ab1") is False
''',
    },
    "is_leap_year": {
        "fn_name": "is_leap_year",
        "correct_source": '''def is_leap_year(year):
    return (year % 4 == 0 and year % 100 != 0) or (year % 100 == 0 and year % 400 == 0)
''',
        "test_source": '''def test_divisible_by_400():
    assert is_leap_year(2000) is True

def test_divisible_by_100_not_400():
    assert is_leap_year(1900) is False

def test_divisible_by_4_only():
    assert is_leap_year(2024) is True

def test_not_divisible_by_4():
    assert is_leap_year(2023) is False
''',
    },
    "average_matches_target": {
        "fn_name": "average_matches_target",
        "correct_source": '''def average_matches_target(nums, target):
    return abs(sum(nums) / len(nums) - target) < 1e-9
''',
        "test_source": '''def test_exact():
    assert average_matches_target([1, 2, 3], 2) is True

def test_not_matching():
    assert average_matches_target([1, 2, 4], 2) is False

def test_float_division():
    assert average_matches_target([1, 2], 1.5) is True

def test_float_rounding_error():
    assert average_matches_target([0.1, 0.1, 0.1], 0.1) is True
''',
    },
    "temperature_reached": {
        "fn_name": "temperature_reached",
        "correct_source": '''def temperature_reached(readings, target):
    return any(abs(r - target) < 0.01 for r in readings)
''',
        "test_source": '''def test_within_tolerance():
    assert temperature_reached([98.6, 100.005], 100.0) is True

def test_not_reached():
    assert temperature_reached([98.6, 99.1], 100.0) is False

def test_empty():
    assert temperature_reached([], 100.0) is False
''',
    },
    # Added 2026-08-18 to unlock Phase 6 (Skill Generator) of the library
    # evolution plan: a legitimate coverage gap requires patterns that
    # actually have NO Book yet AND aren't the 3 permanently-excluded NOVEL
    # control patterns above. These 2 are new, real, distinct patterns.
    "count_word_frequency": {
        "fn_name": "count_word_frequency",
        "correct_source": '''def count_word_frequency(words):
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    return counts
''',
        "test_source": '''def test_basic():
    assert count_word_frequency(["a", "b", "a"]) == {"a": 2, "b": 1}

def test_empty():
    assert count_word_frequency([]) == {}

def test_single():
    assert count_word_frequency(["x"]) == {"x": 1}

def test_all_same():
    assert count_word_frequency(["a", "a", "a"]) == {"a": 3}
''',
    },
    "sum_scores_by_player": {
        "fn_name": "sum_scores_by_player",
        "correct_source": '''def sum_scores_by_player(events):
    totals = {}
    for player, score in events:
        totals[player] = totals.get(player, 0) + score
    return totals
''',
        "test_source": '''def test_basic():
    assert sum_scores_by_player([("a", 10), ("b", 5), ("a", 3)]) == {"a": 13, "b": 5}

def test_empty():
    assert sum_scores_by_player([]) == {}

def test_negative_scores():
    assert sum_scores_by_player([("a", -5), ("a", 10)]) == {"a": 5}
''',
    },
    "find_matching_tag": {
        "fn_name": "find_matching_tag",
        "correct_source": '''def find_matching_tag(tags, query):
    query_lower = query.lower()
    for tag in tags:
        if tag.lower() == query_lower:
            return tag
    return None
''',
        "test_source": '''def test_exact_case():
    assert find_matching_tag(["Python", "Java"], "Python") == "Python"

def test_different_case():
    assert find_matching_tag(["Python", "Java"], "python") == "Python"

def test_no_match():
    assert find_matching_tag(["Python", "Java"], "Ruby") is None

def test_mixed_case_tags():
    assert find_matching_tag(["PyThOn"], "python") == "PyThOn"
''',
    },
    "is_valid_username": {
        "fn_name": "is_valid_username",
        "correct_source": '''def is_valid_username(name, reserved_list):
    name_lower = name.lower()
    return not any(r.lower() == name_lower for r in reserved_list)
''',
        "test_source": '''def test_not_reserved():
    assert is_valid_username("alice", ["admin", "root"]) is True

def test_reserved_exact():
    assert is_valid_username("admin", ["admin", "root"]) is False

def test_reserved_different_case():
    assert is_valid_username("Admin", ["admin", "root"]) is False

def test_reserved_case_in_list():
    assert is_valid_username("root", ["Admin", "Root"]) is False
''',
    },
}

BUG_PATTERNS = {
    "off_by_one": {
        "capability_tags": ["off-by-one", "loop-bounds"],
        "description": "Loop or range boundary is one element short or one element too many.",
    },
    "wrong_comparison_operator": {
        "capability_tags": ["comparison-operator", "boundary-condition"],
        "description": "A comparison uses the wrong operator (< vs <=, == vs !=), silently changing which boundary case is included.",
    },
    "mutable_default_argument": {
        "capability_tags": ["mutable-default-argument", "python-gotcha"],
        "description": "A list/dict/set default argument is created once at function-definition time and silently accumulates state across calls.",
    },
    "integer_division_truncation": {
        "capability_tags": ["integer-division", "type-error"],
        "description": "/ and // are swapped, either silently truncating a result that should be fractional or producing a float where an int index was required.",
    },
    "inverted_boolean_logic": {
        "capability_tags": ["boolean-logic", "and-or-confusion"],
        "description": "and/or are swapped in a compound condition, inverting which cases are accepted.",
    },
    "floating_point_equality": {
        "capability_tags": ["floating-point", "equality-check"],
        "description": "Floats are compared with == (or exact membership) instead of a tolerance, so a mathematically-correct-but-not-bit-exact value is rejected.",
    },
    "wrong_accumulator_init": {
        "capability_tags": ["accumulator-init", "loop-state"],
        "description": "An accumulator is seeded with the wrong initial value or type, so every result is offset or contains a spurious leading element.",
    },
    "index_out_of_range_boundary": {
        "capability_tags": ["index-boundary", "slicing"],
        "description": "An index or slice bound is computed one element past (or short of) a valid boundary.",
    },
    # NOVEL -- deliberately undocumented in any Book. Do not add a Book for these.
    "variable_shadowing": {
        "capability_tags": ["variable-shadowing", "scoping"],
        "description": "An inner loop reuses an outer loop's variable name, silently corrupting the outer loop's state.",
    },
    "incorrect_sort_key_or_order": {
        "capability_tags": ["sorting", "ordering"],
        "description": "A sort uses the wrong key, or an unwanted sort is introduced where original order must be preserved.",
    },
    "wrong_return_in_loop": {
        "capability_tags": ["premature-return", "control-flow"],
        "description": "A return statement sits inside a loop body instead of after it, so only the first iteration's partial result is ever returned.",
    },
    # Legitimate coverage gaps (added 2026-08-18, unlike the 3 above these
    # ARE eligible for a Book -- see library/sections.py's
    # GENERATION_ELIGIBLE). No Book exists for them yet; that's the point.
    "key_error_missing_dict_check": {
        "capability_tags": ["missing-key-check", "dict-access"],
        "description": "A dict is updated with counts[key] += 1 (or similar) without first checking/initializing the key, raising KeyError on the first occurrence instead of using .get(key, default) or setdefault.",
    },
    "wrong_string_case_comparison": {
        "capability_tags": ["case-sensitivity", "string-comparison"],
        "description": "Two strings are compared directly (== or 'in') without normalizing case first, so semantically-matching values with different casing are wrongly treated as distinct.",
    },
}

# Each entry: (pattern_id, problem_id, role, buggy_source). role is "known_example"
# (the problem a Book, if any, uses as its worked example) or "variant" (a different
# problem, same pattern). task_generator.py derives the KNOWN/VARIANT/NOVEL split by
# checking which pattern_ids have a Book in the library -- see library/books/*.yaml.
TASK_TEMPLATES = [
    ("off_by_one", "binary_search", "known_example", '''def binary_search(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
'''),
    ("off_by_one", "rolling_average", "variant", '''def rolling_average(nums, window):
    result = []
    for i in range(len(nums) - window):
        chunk = nums[i:i + window]
        result.append(sum(chunk) / window)
    return result
'''),
    ("wrong_comparison_operator", "merge_intervals", "known_example", '''def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda iv: iv[0])
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        last = merged[-1]
        if start < last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return merged
'''),
    ("wrong_comparison_operator", "run_length_encode", "variant", '''def run_length_encode(s):
    if not s:
        return ""
    result = []
    count = 1
    for i in range(1, len(s)):
        if s[i] != s[i - 1]:
            count += 1
        else:
            result.append(s[i - 1] + str(count))
            count = 1
    result.append(s[-1] + str(count))
    return "".join(result)
'''),
    ("mutable_default_argument", "dedupe_preserve_order", "known_example", '''def dedupe_preserve_order(items, seen=set(), result=[]):
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
'''),
    ("mutable_default_argument", "flatten_list", "variant", '''def flatten_list(nested, result=[]):
    for item in nested:
        if isinstance(item, list):
            result.extend(item)
        else:
            result.append(item)
    return result
'''),
    ("integer_division_truncation", "rolling_average", "known_example", '''def rolling_average(nums, window):
    result = []
    for i in range(len(nums) - window + 1):
        chunk = nums[i:i + window]
        result.append(sum(chunk) // window)
    return result
'''),
    ("integer_division_truncation", "binary_search", "variant", '''def binary_search(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) / 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
'''),
    ("inverted_boolean_logic", "is_leap_year", "known_example", '''def is_leap_year(year):
    return (year % 4 == 0 and year % 100 != 0) and (year % 100 == 0 and year % 400 == 0)
'''),
    ("inverted_boolean_logic", "is_valid_password", "variant", '''def is_valid_password(s):
    return (
        len(s) >= 8
        or any(c.isdigit() for c in s)
        or any(c.isupper() for c in s)
    )
'''),
    ("floating_point_equality", "average_matches_target", "known_example", '''def average_matches_target(nums, target):
    return sum(nums) / len(nums) == target
'''),
    ("floating_point_equality", "temperature_reached", "variant", '''def temperature_reached(readings, target):
    return target in readings
'''),
    ("wrong_accumulator_init", "count_vowels", "known_example", '''def count_vowels(s):
    vowels = set("aeiouAEIOU")
    count = 1
    for ch in s:
        if ch in vowels:
            count += 1
    return count
'''),
    ("wrong_accumulator_init", "reverse_words", "variant", '''def reverse_words(s):
    words = s.split()
    result = [""]
    for w in reversed(words):
        result.append(w)
    return " ".join(result)
'''),
    ("index_out_of_range_boundary", "run_length_encode", "known_example", '''def run_length_encode(s):
    if not s:
        return ""
    result = []
    count = 1
    for i in range(1, len(s) - 1):
        if s[i] == s[i - 1]:
            count += 1
        else:
            result.append(s[i - 1] + str(count))
            count = 1
    result.append(s[-1] + str(count))
    return "".join(result)
'''),
    ("index_out_of_range_boundary", "binary_search", "variant", '''def binary_search(arr, target):
    lo, hi = 0, len(arr)
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
'''),
    # NOVEL -- these patterns have no Book. See BUG_PATTERNS above.
    ("variable_shadowing", "rolling_average", "novel_a", '''def rolling_average(nums, window):
    result = []
    for i in range(len(nums) - window + 1):
        total = 0
        for i in range(window):
            total += nums[i]
        result.append(total / window)
    return result
'''),
    ("variable_shadowing", "reverse_words", "novel_b", '''def reverse_words(s):
    words = s.split()
    result = []
    for w in reversed(words):
        for w in [w.upper()]:
            result.append(w)
    return " ".join(result)
'''),
    ("incorrect_sort_key_or_order", "merge_intervals", "novel_a", '''def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda iv: iv[1])
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return merged
'''),
    ("incorrect_sort_key_or_order", "dedupe_preserve_order", "novel_b", '''def dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return sorted(result)
'''),
    ("wrong_return_in_loop", "dedupe_preserve_order", "novel_a", '''def dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
        return result
'''),
    ("wrong_return_in_loop", "flatten_list", "novel_b", '''def flatten_list(nested):
    result = []
    for item in nested:
        if isinstance(item, list):
            result.extend(item)
        else:
            result.append(item)
        return result
'''),
    ("key_error_missing_dict_check", "count_word_frequency", "known_example", '''def count_word_frequency(words):
    counts = {}
    for w in words:
        counts[w] += 1
    return counts
'''),
    ("key_error_missing_dict_check", "sum_scores_by_player", "variant", '''def sum_scores_by_player(events):
    totals = {}
    for player, score in events:
        totals[player] += score
    return totals
'''),
    ("wrong_string_case_comparison", "find_matching_tag", "known_example", '''def find_matching_tag(tags, query):
    for tag in tags:
        if tag == query:
            return tag
    return None
'''),
    ("wrong_string_case_comparison", "is_valid_username", "variant", '''def is_valid_username(name, reserved_list):
    return name not in reserved_list
'''),

    # ---- 2026-08-19, experiment4 (raised n per pattern) -----------------
    # 13 new instances, reusing EXISTING problem_ids (test_source untouched)
    # with a new pattern's bug injected -- addresses the "expand here before
    # running Experiment 0 for real" note at the top of this file. Each was
    # pre-verified against the real pytest verifier (correct_source passes
    # in full, buggy_source fails at least one test) before being added here
    # -- see scratchpad/verify_new_templates.py from that session. role
    # "variant2"/"variant3" (not "known_example") so task_generator.py's
    # existing KNOWN/VARIANT/NOVEL logic classifies these as VARIANT
    # automatically, no code changes needed there.
    ("off_by_one", "run_length_encode", "variant2", '''def run_length_encode(s):
    if not s:
        return ""
    result = []
    count = 1
    for i in range(1, len(s) - 1):
        if s[i] == s[i - 1]:
            count += 1
        else:
            result.append(s[i - 1] + str(count))
            count = 1
    result.append(s[-1] + str(count))
    return "".join(result)
'''),
    ("off_by_one", "merge_intervals", "variant2", '''def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda iv: iv[0])
    merged = [list(intervals[0])]
    for start, end in intervals[2:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return merged
'''),
    ("wrong_comparison_operator", "binary_search", "variant2", '''def binary_search(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
'''),
    ("wrong_comparison_operator", "is_valid_password", "variant2", '''def is_valid_password(s):
    return (
        len(s) > 8
        and any(c.isdigit() for c in s)
        and any(c.isupper() for c in s)
    )
'''),
    ("integer_division_truncation", "sum_digits", "variant2", '''def sum_digits(n):
    total = 0
    n = abs(n)
    while n > 0:
        total += n % 10
        n /= 10
    return total
'''),
    ("inverted_boolean_logic", "is_valid_username", "variant2", '''def is_valid_username(name, reserved_list):
    name_lower = name.lower()
    return any(r.lower() == name_lower for r in reserved_list)
'''),
    ("wrong_accumulator_init", "count_word_frequency", "variant2", '''def count_word_frequency(words):
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 1) + 1
    return counts
'''),
    ("wrong_accumulator_init", "sum_scores_by_player", "variant2", '''def sum_scores_by_player(events):
    totals = {}
    for player, score in events:
        totals[player] = totals.get(player, 1) + score
    return totals
'''),
    ("index_out_of_range_boundary", "merge_intervals", "variant2", '''def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda iv: iv[0])
    merged = [list(intervals[0])]
    for start, end in intervals[1:-1]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return merged
'''),
    ("wrong_return_in_loop", "count_word_frequency", "variant3", '''def count_word_frequency(words):
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
        return counts
'''),
    ("wrong_return_in_loop", "sum_scores_by_player", "variant3", '''def sum_scores_by_player(events):
    totals = {}
    for player, score in events:
        totals[player] = totals.get(player, 0) + score
        return totals
'''),
    ("wrong_string_case_comparison", "is_palindrome", "variant2", '''def is_palindrome(s):
    return s == s[::-1]
'''),
    ("wrong_string_case_comparison", "count_vowels", "variant2", '''def count_vowels(s):
    vowels = set("aeiou")
    count = 0
    for ch in s:
        if ch in vowels:
            count += 1
    return count
'''),
]
