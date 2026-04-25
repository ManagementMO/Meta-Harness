"""Tests for Pareto frontier with dominated_by_names (INTERFACES.md §2.2)."""

from __future__ import annotations

from app.meta_harness.frontier import (
    best_candidate,
    build_frontier_val,
    compute_pareto,
    dominates,
    pareto_names,
)


def test_dominates_strict_better_on_both():
    a = {"name": "a", "accuracy": 0.9, "avg_tokens": 10000}
    b = {"name": "b", "accuracy": 0.7, "avg_tokens": 12000}
    assert dominates(a, b)
    assert not dominates(b, a)


def test_dominates_equal_on_one_axis():
    a = {"name": "a", "accuracy": 0.8, "avg_tokens": 10000}
    b = {"name": "b", "accuracy": 0.8, "avg_tokens": 12000}
    # a is equal on accuracy, strictly better on tokens → dominates b
    assert dominates(a, b)
    assert not dominates(b, a)


def test_dominates_neither_when_tradeoff():
    a = {"name": "a", "accuracy": 0.9, "avg_tokens": 30000}  # high acc, more tokens
    b = {"name": "b", "accuracy": 0.7, "avg_tokens": 10000}  # low acc, fewer tokens
    assert not dominates(a, b)
    assert not dominates(b, a)


def test_compute_pareto_marks_dominated():
    cands = [
        {"name": "high-acc", "accuracy": 0.9, "avg_tokens": 25000},
        {"name": "cheap", "accuracy": 0.7, "avg_tokens": 10000},
        {"name": "dominated", "accuracy": 0.6, "avg_tokens": 30000},
    ]
    annotated = compute_pareto(cands)
    by_name = {c["name"]: c["dominated_by_names"] for c in annotated}
    assert by_name["high-acc"] == []
    assert by_name["cheap"] == []
    # 'dominated' is dominated by both — both have ≥ accuracy and ≤ tokens.
    assert set(by_name["dominated"]) == {"high-acc", "cheap"}


def test_pareto_names_filters_to_undominated():
    cands = compute_pareto(
        [
            {"name": "a", "accuracy": 0.9, "avg_tokens": 25000},
            {"name": "b", "accuracy": 0.6, "avg_tokens": 30000},
        ]
    )
    assert pareto_names(cands) == ["a"]


def test_best_candidate_breaks_ties_with_lower_tokens():
    cands = [
        {"name": "expensive", "accuracy": 0.85, "avg_tokens": 30000},
        {"name": "efficient", "accuracy": 0.85, "avg_tokens": 20000},
    ]
    best = best_candidate(cands)
    assert best is not None
    assert best["name"] == "efficient"


def test_build_frontier_val_full_shape():
    cands = [
        {"name": "a", "accuracy": 0.8, "avg_tokens": 24000},
        {"name": "b", "accuracy": 0.7, "avg_tokens": 30000},
    ]
    per_task = {"task-001": {"best_candidate": "a", "pass_rate": 0.95}}
    frontier = build_frontier_val(iteration=2, candidates=cands, per_task_bests=per_task)
    assert frontier["iteration"] == 2
    assert "candidates" in frontier
    assert all("dominated_by_names" in c for c in frontier["candidates"])
    assert frontier["_pareto_names"] == ["a"]
    assert frontier["_best"]["name"] == "a"
    assert frontier["per_task"] == per_task
