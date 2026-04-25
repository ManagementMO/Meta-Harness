from calculator import add, sub


def test_add_basic():
    assert add(2, 3) == 5


def test_add_zero():
    assert add(0, 0) == 0


def test_add_negative():
    assert add(-1, 1) == 0


def test_sub_basic():
    assert sub(5, 3) == 2


def test_sub_self():
    assert sub(7, 7) == 0
