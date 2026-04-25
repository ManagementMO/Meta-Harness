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
