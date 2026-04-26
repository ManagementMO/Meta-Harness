from parser import parse_ages


def test_parse_basic():
    assert parse_ages("12, 34, 56") == [12, 34, 56]


def test_parse_single():
    assert parse_ages("42") == [42]


def test_parse_empty_returns_empty():
    """Currently crashes — int('') raises ValueError."""
    assert parse_ages("") == []


def test_parse_skips_invalid():
    """Currently crashes — int('bad') raises ValueError."""
    assert parse_ages("12, bad, 34") == [12, 34]


def test_parse_skips_only_invalid():
    assert parse_ages("a, b, c") == []


def test_parse_with_spaces():
    assert parse_ages("  10  ,  20  ") == [10, 20]


# ── Adversarial tests (option 3 hardening, 2026-04-25) ──────────────
# Search-space rationale lives in docs/PROJECT_KNOWLEDGE_BASE.md §28.4.


def test_parse_negative_integers():
    """Negative integers should round-trip. ``int('-5')`` works fine —
    catches implementations that filter on ``s.isdigit()`` (which is
    False for negative numbers because of the sign character)."""
    assert parse_ages("-5, -10, 5") == [-5, -10, 5]


def test_parse_only_whitespace_returns_empty():
    """Pure-whitespace input must return []. The whitespace, after
    stripping, becomes the empty string — which int() rejects with
    ValueError. The function must catch that case."""
    assert parse_ages("   ") == []
    assert parse_ages(" \t \n ") == []


def test_parse_decimals_skipped_not_converted():
    """A common mistake is to use float() instead of int() to be
    "lenient". This test catches that — '1.5' must NOT round-trip as
    a float; it should be skipped because the spec says ages are ints.
    """
    result = parse_ages("1.5, 2, 3.0")
    assert result == [2], (
        f"Expected [2] (decimals skipped); got {result}. "
        "Use int() not float() to parse — decimals are not valid ages."
    )
