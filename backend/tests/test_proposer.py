"""Regression tests for the Claude proposer subprocess wrapper."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

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
