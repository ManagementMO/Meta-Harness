import pytest

from stack import Stack


def test_new_stack_is_empty():
    s = Stack()
    assert s.is_empty() is True
    assert len(s) == 0


def test_push_then_peek_does_not_pop():
    s = Stack()
    s.push(1)
    s.push(2)
    assert s.peek() == 2
    assert len(s) == 2


def test_lifo_order():
    s = Stack()
    s.push("a")
    s.push("b")
    s.push("c")
    assert s.pop() == "c"
    assert s.pop() == "b"
    assert s.pop() == "a"
    assert s.is_empty() is True


def test_pop_empty_raises():
    s = Stack()
    with pytest.raises(IndexError):
        s.pop()


def test_peek_empty_raises():
    s = Stack()
    with pytest.raises(IndexError):
        s.peek()


def test_len_tracks_size():
    s = Stack()
    assert len(s) == 0
    for i in range(5):
        s.push(i)
    assert len(s) == 5
    s.pop()
    assert len(s) == 4
