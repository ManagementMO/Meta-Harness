"""Validation for proposer skill files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REQUIRED_SECTIONS = (
    "What gets evolved",
    "Hard rules (Anti-Overfitting)",
    "Hard rules (Anti-Parameter-Tuning)",
    "Workflow",
    "Interface contract",
    "pending_eval.json",
)


def validate_skill(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ValueError("skill must begin with YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise ValueError("skill frontmatter is not closed")
    frontmatter = yaml.safe_load(parts[1]) or {}
    name = str(frontmatter.get("name", ""))
    description = str(frontmatter.get("description", ""))
    if not name or len(name) > 64:
        raise ValueError("skill name is required and must be at most 64 characters")
    if not description or len(description) > 1024:
        raise ValueError(
            "skill description is required and must be at most 1024 characters"
        )
    if "<" in name or ">" in name or "<" in description or ">" in description:
        raise ValueError("skill frontmatter must not contain XML tags")
    missing = [section for section in _REQUIRED_SECTIONS if section not in parts[2]]
    if missing:
        raise ValueError(f"skill is missing required sections: {missing}")
    return {
        "name": name,
        "description": description,
        "path": str(path.resolve()),
    }
