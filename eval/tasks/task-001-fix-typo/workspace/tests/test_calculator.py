import inspect

import calculator
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


# ── Adversarial tests (option 3 hardening, 2026-04-25) ──────────────
# These probe contract details the baseline harness can miss without
# explicit attention. Search-space rationale lives in
# docs/PROJECT_KNOWLEDGE_BASE.md §28.1.


def test_add_returns_int_when_given_ints():
    """add(int, int) must return an int. A naive overcorrection like
    ``return float(a) + b`` would fail this. Note: ``bool`` is a subclass
    of ``int`` in Python, so we exclude it explicitly."""
    result = add(2, 3)
    assert isinstance(result, int) and not isinstance(result, bool)


def test_sub_function_unchanged():
    """The instruction is explicit: do NOT change sub(). This test
    verifies the function body is exactly ``return a - b`` (modulo
    whitespace). Catches candidates that "clean up" or rewrite the file."""
    src = inspect.getsource(sub)
    body_lines = [
        line.strip()
        for line in src.split("\n")
        if line.strip() and not line.strip().startswith(("def ", '"""', "#", "'''"))
    ]
    assert body_lines == ["return a - b"], (
        f"sub() body should be exactly 'return a - b'; got {body_lines}"
    )


def test_module_only_defines_add_and_sub():
    """Anti-bloat: the module should still only expose add and sub as
    public functions. Catches candidates that add helpers the task
    didn't ask for."""
    public_funcs = {
        name
        for name, obj in inspect.getmembers(calculator, inspect.isfunction)
        if not name.startswith("_") and obj.__module__ == "calculator"
    }
    assert public_funcs == {"add", "sub"}, (
        f"calculator module should expose only {{add, sub}}; got {public_funcs}"
    )
