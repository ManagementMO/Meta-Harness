import inspect

import util
from util import process_admins, process_engineers, process_managers


SAMPLE = [
    {"id": 1, "name": " alice ", "email": "ALICE@X.com", "role": "admin", "active": True},
    {"id": 2, "name": "bob",     "email": "bob@x.com",   "role": "manager", "active": True},
    {"id": 3, "name": " carol ", "email": "Carol@x.com", "role": "engineer", "active": True},
    {"id": 4, "name": "dan",     "email": "dan@x.com",   "role": "admin", "active": False},
    {"id": 5, "name": "eve",     "email": "eve@x.com",   "role": "manager", "active": True},
    {"id": 6, "name": " frank ", "email": "Frank@x.com", "role": "engineer", "active": False},
]


def test_process_admins():
    out = process_admins(SAMPLE)
    assert len(out) == 1
    assert out[0]["id"] == 1
    assert out[0]["name"] == "Alice"
    assert out[0]["email"] == "alice@x.com"


def test_process_managers():
    out = process_managers(SAMPLE)
    assert {u["id"] for u in out} == {2, 5}
    assert all(u["email"] == u["email"].lower() for u in out)


def test_process_engineers():
    out = process_engineers(SAMPLE)
    assert len(out) == 1
    assert out[0]["id"] == 3
    assert out[0]["name"] == "Carol"


def test_process_admins_empty_input():
    assert process_admins([]) == []


def test_process_managers_skips_inactive():
    inactive_only = [{"id": 9, "name": "x", "email": "x@x.com", "role": "manager", "active": False}]
    assert process_managers(inactive_only) == []


def test_each_public_function_is_thin_wrapper_after_refactor():
    """Each of the three public functions must be ≤4 non-empty body lines.

    Pre-refactor each is ~12 lines (full filter+normalize implementation).
    Post-refactor each should delegate to a shared helper, dropping to 1-3
    body lines. This is the structural assertion that detects whether the
    refactor actually happened.
    """
    for fn_name in ("process_admins", "process_managers", "process_engineers"):
        fn = getattr(util, fn_name)
        src = inspect.getsource(fn)
        body_lines = [
            line
            for line in src.split("\n")
            if line.strip() and not line.lstrip().startswith(("def ", '"""', "#"))
        ]
        assert len(body_lines) <= 4, (
            f"{fn_name} body has {len(body_lines)} non-empty lines; "
            "expected ≤4 after refactor (delegate to a shared helper)."
        )
