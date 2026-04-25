"""Backend pytest config: load .env at session start.

Lets ``test_inner.py``'s live LLM test pick up ``ANTHROPIC_API_KEY``
without the user having to export it in their shell.
"""

from pathlib import Path

from dotenv import load_dotenv


def pytest_configure(config):  # noqa: ARG001 — pytest hook signature
    repo_root = Path(__file__).resolve().parents[1]
    env_file = repo_root / ".env"
    if env_file.exists():
        load_dotenv(env_file)
