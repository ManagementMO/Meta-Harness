"""Regression tests for the Claude proposer subprocess wrapper."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from app.meta_harness import proposer


REPO_ROOT = Path(__file__).resolve().parents[2]


class _Pipe:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""

    def close(self) -> None:
        pass


class _Proc:
    def __init__(self, env: dict[str, str], cwd: str) -> None:
        self.env = env
        self.cwd = cwd
        self.returncode = 0
        self.stdout = _Pipe([
            json.dumps({
                "type": "result",
                "session_id": "session-1",
                "total_cost_usd": 0.01,
            }) + "\n"
        ])
        self.stderr = _Pipe([])

    def poll(self) -> int | None:
        return 0 if not self.stdout._lines else None

    def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = 124


def test_claude_propose_preserves_anthropic_api_key_for_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_popen(cmd, stdout, stderr, stdin, text, encoding, errors, cwd, env):
        del cmd, stdout, stderr, stdin, text, encoding, errors
        captured["api_key"] = env.get("ANTHROPIC_API_KEY", "")
        return _Proc(env, cwd)

    monkeypatch.setattr(proposer.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    run_dir = REPO_ROOT / "runs" / f"test-proposer-{tmp_path.name}"
    run_dir.mkdir()
    try:
        (run_dir / "pending_eval.json").write_text(
            json.dumps({
                "name": "candidate",
                "import_path": "agents.candidate:CandidateHarness",
                "hypothesis": "test",
                "mechanism_axis": "test",
            })
        )
        skill = tmp_path / "SKILL.md"
        skill.write_text("skill")

        payload = proposer.claude_propose(
            run_dir=run_dir,
            iteration=1,
            parent_name=None,
            repo_root=REPO_ROOT,
            skill_path=skill,
        )

        assert captured["api_key"] == "test-key"
        assert payload["name"] == "candidate"
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_bounded_evidence_ignores_holdout_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    parent_dir = run_dir / "candidates" / "cand_parent"
    (parent_dir / "traces").mkdir(parents=True)
    (run_dir / "holdout-result.json").write_text('{"secret": "holdout"}')
    (run_dir / "evolution_summary.jsonl").write_text('{"candidate": "baseline"}\n')
    (parent_dir / "traces" / "summary.md").write_text("search evidence")

    evidence = proposer._bounded_evidence(
        run_dir=run_dir,
        parent_candidate_dir=parent_dir,
    )

    serialized = json.dumps(evidence)
    assert "search evidence" in serialized
    assert "holdout" not in serialized
    assert "secret" not in serialized


def test_gemini_propose_writes_validated_run_scoped_candidate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from google import genai

    proposal = proposer.GeminiProposalResponse(
        name="gemini-candidate",
        class_name="GeminiCandidateHarness",
        source_code=(
            "from app.meta_harness.harness import CodingAgentHarness\n\n"
            "class GeminiCandidateHarness(CodingAgentHarness):\n"
            "    MAX_VERIFY_RETRIES = 2\n"
        ),
        hypothesis="Bounded retries reduce wasted verification turns.",
        axis="exploitation",
        expected_score_delta=0.05,
    )
    response = SimpleNamespace(
        parsed=proposal,
        text=proposal.model_dump_json(),
        model_version="gemini-3.7-flash",
        response_id="response-1",
        usage_metadata=SimpleNamespace(
            prompt_token_count=100,
            candidates_token_count=20,
            thoughts_token_count=10,
            cached_content_token_count=0,
        ),
    )

    class FakeModels:
        def generate_content(self, **kwargs):
            assert kwargs["model"] == "gemini-3.7-flash"
            return response

    monkeypatch.setattr(
        genai,
        "Client",
        lambda **_kwargs: SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(proposer, "reserve_google_request", lambda _model: 0.0)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    run_dir = tmp_path / "run"
    parent_dir = run_dir / "candidates" / "cand_parent"
    parent_dir.mkdir(parents=True)
    parent_source = tmp_path / "parent.py"
    parent_source.write_text(
        "from app.meta_harness.harness import CodingAgentHarness\n\n"
        "class ParentHarness(CodingAgentHarness):\n"
        "    pass\n"
    )
    skill = tmp_path / "SKILL.md"
    skill.write_text("skill")

    payload = proposer.gemini_propose(
        run_dir=run_dir,
        iteration=1,
        parent_name="parent",
        repo_root=tmp_path,
        skill_path=skill,
        parent_source_path=parent_source,
        parent_candidate_dir=parent_dir,
        model="gemini-3.7-flash",
        seed=101,
    )

    candidate = payload["candidates"][0]
    assert candidate["name"] == "gemini-candidate"
    assert candidate["class_name"] == "GeminiCandidateHarness"
    assert (tmp_path / candidate["source_path"]).is_file()
    session = json.loads(
        (run_dir / "proposer-sessions" / "iter-1" / "session.json").read_text()
    )
    assert session["token_usage_measurement_status"] == "measured"
    assert session["random_seed"] == 101
    assert "test-key" not in json.dumps(session)
