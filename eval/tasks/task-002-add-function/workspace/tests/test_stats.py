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
