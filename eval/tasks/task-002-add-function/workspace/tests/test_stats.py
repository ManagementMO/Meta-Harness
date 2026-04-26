import pytest

from stats import mean, median  # noqa: F401 — median doesn't exist yet, that's the task


def test_mean_basic():
    assert mean([1, 2, 3]) == 2


def test_mean_empty_raises():
    with pytest.raises(ValueError):
        mean([])


def test_median_odd_length():
    assert median([1, 2, 3]) == 2


def test_median_even_length():
    assert median([1, 2, 3, 4]) == 2.5


def test_median_single_element():
    assert median([5]) == 5


def test_median_empty_raises():
    with pytest.raises(ValueError):
        median([])


def test_median_unsorted():
    assert median([3, 1, 2]) == 2


def test_median_negative():
    assert median([-3, -1, -2]) == -2


# ── Adversarial tests (option 3 hardening, 2026-04-25) ──────────────
# Search-space rationale lives in docs/PROJECT_KNOWLEDGE_BASE.md §28.2.


def test_median_does_not_mutate_input():
    """median() must not modify its argument. The natural Python
    implementation ``values.sort()`` mutates; the correct one uses
    ``sorted(values)``. This is a real-world contract for stats helpers."""
    xs = [3, 1, 2]
    median(xs)
    assert xs == [3, 1, 2], (
        f"median() mutated its input; expected [3, 1, 2], got {xs}. "
        "Use sorted(values) instead of values.sort()."
    )


def test_median_with_duplicates():
    """Duplicates must be counted, not deduped. Catches implementations
    that defensively call set(values) somewhere."""
    assert median([1, 1, 1, 2]) == 1.0
    assert median([2, 2, 3, 3]) == 2.5


def test_median_two_element_average():
    """Sanity: two-element list returns the average, not the first."""
    assert median([1, 3]) == 2.0
    assert median([10, 20]) == 15.0
