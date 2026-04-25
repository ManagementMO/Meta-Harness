"""Pareto-frontier computation on (accuracy × tokens).

INTERFACES.md §2.2 frontier_val.json shape:
- ``candidates``: list of ``{name, accuracy, avg_tokens, dominated_by_names}``
- ``_pareto_names``: convenience subset where ``dominated_by_names == []``
- ``_best``: highest-accuracy candidate (ties broken by lower tokens)
- ``per_task``: per-task best candidate + pass_rate

Domination rule (maximize accuracy, minimize tokens): ``A`` dominates
``B`` iff ``A.accuracy >= B.accuracy`` AND ``A.avg_tokens <= B.avg_tokens``
AND at least one of those is strict.
"""

from __future__ import annotations

from typing import Any


def dominates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Return True iff candidate ``a`` dominates ``b`` on (accuracy, tokens)."""
    a_acc, a_tok = a["accuracy"], a["avg_tokens"]
    b_acc, b_tok = b["accuracy"], b["avg_tokens"]
    if a_acc < b_acc or a_tok > b_tok:
        return False
    return a_acc > b_acc or a_tok < b_tok


def compute_pareto(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Annotate each candidate with ``dominated_by_names``. Returns the
    same list, with each entry mutated to include the field."""
    for c in candidates:
        c["dominated_by_names"] = [
            other["name"]
            for other in candidates
            if other["name"] != c["name"] and dominates(other, c)
        ]
    return candidates


def pareto_names(candidates: list[dict[str, Any]]) -> list[str]:
    """Names of candidates with ``dominated_by_names == []``."""
    return [c["name"] for c in candidates if not c.get("dominated_by_names")]


def best_candidate(
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Highest-accuracy candidate; ties broken by lowest avg_tokens."""
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c["accuracy"], -c["avg_tokens"]))


def build_frontier_val(
    iteration: int,
    candidates: list[dict[str, Any]],
    per_task_bests: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the full frontier_val.json shape."""
    annotated = compute_pareto(list(candidates))
    return {
        "iteration": iteration,
        "candidates": annotated,
        "_pareto_names": pareto_names(annotated),
        "_best": best_candidate(annotated),
        "per_task": per_task_bests,
    }
