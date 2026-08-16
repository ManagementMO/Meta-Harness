"""Immutable candidate materialization, validation, and loading."""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator

from app.meta_harness.artifacts import (
    atomic_create_bytes,
    atomic_write_json,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from app.meta_harness.contracts import (
    CandidateArtifact,
    ComponentKind,
    EvaluationPolicy,
    HarnessComponentRef,
    Provenance,
    SourceArtifact,
)
from app.meta_harness.harness import CodingAgentHarness
from app.meta_harness.runs import validate_artifact_name

_CANDIDATE_ID_RE = re.compile(r"^cand_[0-9a-f]{16}$")
_PROCESS_WRITE_LOCK = threading.RLock()


@contextmanager
def _candidate_write_lock(run_dir: Path) -> Iterator[None]:
    lock_path = run_dir / "candidates" / ".write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    with _PROCESS_WRITE_LOCK:
        try:
            try:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except ImportError:
                pass
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except ImportError:
                pass
            os.close(descriptor)


def _contained_path(roots: list[Path], path: Path) -> Path:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    raise ValueError(f"candidate source escapes allowed roots: {path}")


def resolve_candidate_source(
    repo_root: Path,
    metadata: dict[str, Any],
    *,
    proposal_root: Path | None = None,
) -> tuple[Path, str, str | None]:
    import_path = metadata.get("import_path")
    class_name = metadata.get("class_name")
    source_path = metadata.get("source_path")
    module_path: str | None = None
    allowed_roots = [repo_root]
    if proposal_root is not None:
        allowed_roots.append(proposal_root)
    if import_path:
        module_path, separator, imported_class = str(import_path).partition(":")
        if not separator or not module_path or not imported_class:
            raise ValueError(f"invalid candidate import_path: {import_path!r}")
        class_name = class_name or imported_class
    if source_path:
        raw_path = Path(str(source_path))
        source = raw_path if raw_path.is_absolute() else repo_root / raw_path
        source = _contained_path(allowed_roots, source)
    else:
        if not module_path:
            raise ValueError("candidate requires source_path or import_path")
        spec = importlib.util.find_spec(module_path)
        if spec is None or not spec.origin:
            raise ValueError(f"cannot resolve source for {module_path!r}")
        source = _contained_path(allowed_roots, Path(spec.origin))
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix != ".py":
        raise ValueError(f"candidate source must be a Python module: {source}")
    if not class_name:
        raise ValueError("candidate class_name is required")
    return source, str(class_name), str(import_path) if import_path else None


_COMPONENT_KIND_BY_GROUP = {
    "prompts": ComponentKind.PROMPT,
    "skills": ComponentKind.SKILL,
    "memories": ComponentKind.MEMORY,
    "subagents": ComponentKind.SUBAGENT,
    "control_flow": ComponentKind.CONTROL_FLOW,
    "tool_interfaces": ComponentKind.TOOL_INTERFACE,
}


def _normalize_components(
    components: dict[str, list[str]] | list[HarnessComponentRef] | None,
) -> list[HarnessComponentRef]:
    if components is None:
        return []
    if isinstance(components, list):
        normalized = [HarnessComponentRef.model_validate(value) for value in components]
    else:
        normalized = []
        for group, values in components.items():
            kind = _COMPONENT_KIND_BY_GROUP.get(group)
            if kind is None:
                raise ValueError(f"unknown harness component group: {group}")
            for value in values:
                component_id = str(value)
                digest = None
                match = re.search(r":([0-9a-f]{64})$", component_id)
                if match:
                    digest = match.group(1)
                    component_id = component_id[: match.start()]
                normalized.append(
                    HarnessComponentRef(
                        component_id=component_id,
                        kind=kind,
                        sha256=digest,
                    )
                )
    return sorted(
        normalized,
        key=lambda component: (
            component.kind.value,
            component.component_id,
            component.version or "",
            component.sha256 or "",
        ),
    )


def _candidate_identity(
    *,
    source_sha256: str,
    class_name: str,
    parent_ids: list[str],
    policy: EvaluationPolicy,
    provenance: Provenance,
    components: list[HarnessComponentRef],
) -> str:
    identity = {
        "source_sha256": source_sha256,
        "class_name": class_name,
        "parent_ids": sorted(parent_ids),
        "harness_api_version": 1,
        "inner_model": policy.inner_model,
        "model_provider": policy.model_provider,
        "evaluation_policy_id": policy.policy_id,
        "components": [
            component.model_dump(mode="json") for component in components
        ],
        "git_commit": provenance.git_commit,
        "runtime_sha256": provenance.runtime_sha256,
        "dependency_lock_sha256": provenance.dependency_lock_sha256,
        "authorization_profile": provenance.authorization_profile,
        "proposer_model": (provenance.model_extra or {}).get("proposer_model"),
        "parent_policy": (provenance.model_extra or {}).get("parent_policy"),
    }
    return "cand_" + sha256_bytes(canonical_json_bytes(identity))[:16]


def candidate_dir(run_dir: Path, candidate_id: str) -> Path:
    if not _CANDIDATE_ID_RE.fullmatch(candidate_id):
        raise ValueError(f"invalid candidate id: {candidate_id!r}")
    root = (run_dir / "candidates").resolve()
    target = (root / candidate_id).resolve()
    target.relative_to(root)
    return target


def materialize_candidate(
    *,
    run_dir: Path,
    repo_root: Path,
    metadata: dict[str, Any],
    parent_ids: list[str],
    policy: EvaluationPolicy,
    provenance: Provenance,
    components: dict[str, list[str]] | list[HarnessComponentRef] | None = None,
) -> CandidateArtifact:
    name = validate_artifact_name(str(metadata["name"]), kind="candidate")
    source_path, class_name, _import_path = resolve_candidate_source(
        repo_root,
        metadata,
        proposal_root=run_dir,
    )
    source_bytes = source_path.read_bytes()
    source_sha256 = sha256_bytes(source_bytes)
    component_refs = _normalize_components(components)
    candidate_id = _candidate_identity(
        source_sha256=source_sha256,
        class_name=class_name,
        parent_ids=parent_ids,
        policy=policy,
        provenance=provenance,
        components=component_refs,
    )
    root = candidate_dir(run_dir, candidate_id)
    relative_source = Path("candidates") / candidate_id / "source" / "harness.py"
    immutable_source = run_dir / relative_source
    artifact = CandidateArtifact(
        candidate_id=candidate_id,
        name=name,
        run_id=run_dir.name,
        parent_ids=parent_ids,
        class_name=class_name,
        source=SourceArtifact(
            sha256=source_sha256,
            artifact_path=relative_source.as_posix(),
            media_type="text/x-python",
            size_bytes=len(source_bytes),
        ),
        inner_model=policy.inner_model,
        model_provider=policy.model_provider,
        components=component_refs,
        evaluation_policy_id=policy.policy_id,
        provenance=provenance,
    )
    manifest_path = root / "candidate.json"
    with _candidate_write_lock(run_dir):
        created = atomic_create_bytes(immutable_source, source_bytes)
        if not created and sha256_file(immutable_source) != source_sha256:
            raise ValueError(f"candidate source collision for {candidate_id}")
        if manifest_path.exists():
            existing = CandidateArtifact.model_validate_json(manifest_path.read_text())
            if existing.candidate_id != artifact.candidate_id:
                raise ValueError(f"candidate manifest collision for {candidate_id}")
            artifact = existing
        else:
            atomic_write_json(manifest_path, artifact)
        _update_index(run_dir, artifact)
    return artifact


def _update_index(run_dir: Path, artifact: CandidateArtifact) -> None:
    manifest_path = candidate_dir(run_dir, artifact.candidate_id) / "candidate.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    path = run_dir / "candidates" / "index.json"
    if path.exists():
        value = json.loads(path.read_text())
    else:
        value = {"schema_version": 1, "by_name": {}, "candidate_ids": []}
    by_name = value.setdefault("by_name", {})
    ids = by_name.setdefault(artifact.name, [])
    if artifact.candidate_id not in ids:
        ids.append(artifact.candidate_id)
    candidate_ids = value.setdefault("candidate_ids", [])
    if artifact.candidate_id not in candidate_ids:
        candidate_ids.append(artifact.candidate_id)
    atomic_write_json(path, value)


def load_candidate_artifact(run_dir: Path, candidate_id: str) -> CandidateArtifact:
    manifest_path = candidate_dir(run_dir, candidate_id) / "candidate.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    artifact = CandidateArtifact.model_validate_json(manifest_path.read_text())
    if artifact.candidate_id != candidate_id:
        raise ValueError(f"candidate id mismatch in {manifest_path}")
    source_path = (run_dir / artifact.source.artifact_path).resolve()
    try:
        source_path.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"candidate source escapes run: {source_path}") from exc
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path.stat().st_size != artifact.source.size_bytes:
        raise ValueError(f"candidate source size mismatch: {candidate_id}")
    if sha256_file(source_path) != artifact.source.sha256:
        raise ValueError(f"candidate source hash mismatch: {candidate_id}")
    return artifact


def candidate_search_roots(run_dir: Path) -> list[Path]:
    roots = [run_dir]
    branches_root = run_dir / "branches"
    if branches_root.exists():
        roots.extend(
            path
            for path in sorted(branches_root.iterdir())
            if path.is_dir() and (path / "candidates").is_dir()
        )
    return roots


def locate_candidate(run_dir: Path, name_or_id: str) -> tuple[Path, str]:
    matches: list[tuple[Path, str]] = []
    for root in candidate_search_roots(run_dir):
        if _CANDIDATE_ID_RE.fullmatch(name_or_id):
            if (root / "candidates" / name_or_id / "candidate.json").is_file():
                matches.append((root, name_or_id))
            continue
        path = root / "candidates" / "index.json"
        if not path.exists():
            continue
        ids = json.loads(path.read_text()).get("by_name", {}).get(name_or_id, [])
        matches.extend((root, str(candidate_id)) for candidate_id in ids)
    unique = list(dict.fromkeys(matches))
    if not unique:
        raise KeyError(f"unknown candidate: {name_or_id}")
    if _CANDIDATE_ID_RE.fullmatch(name_or_id):
        return unique[0]
    candidate_ids = {candidate_id for _root, candidate_id in unique}
    if len(candidate_ids) == 1:
        return unique[0]
    if len(unique) > 1:
        raise ValueError(f"candidate name is ambiguous across branches: {name_or_id}")
    return unique[0]


def resolve_candidate_id(run_dir: Path, name_or_id: str) -> str:
    return locate_candidate(run_dir, name_or_id)[1]


def load_candidate_artifact_any(
    run_dir: Path,
    name_or_id: str,
) -> tuple[Path, CandidateArtifact]:
    artifact_root, candidate_id = locate_candidate(run_dir, name_or_id)
    return artifact_root, load_candidate_artifact(artifact_root, candidate_id)


def load_candidate_module(
    run_dir: Path,
    artifact: CandidateArtifact,
    *,
    repo_root: Path,
) -> ModuleType:
    verified = load_candidate_artifact(run_dir, artifact.candidate_id)
    del repo_root
    source_path = run_dir / verified.source.artifact_path
    module_name = f"_meta_harness_candidate_{verified.candidate_id}"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load candidate module {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    previous_bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        sys.dont_write_bytecode = previous_bytecode_setting
    return module


def validate_candidate_source_policy(
    run_dir: Path,
    artifact: CandidateArtifact,
    *,
    forbidden_strings: list[str] | None = None,
) -> None:
    source_path = run_dir / artifact.source.artifact_path
    source = source_path.read_text()
    lowered = source.lower()
    forbidden = ["eval/holdout", "holdout-result"]
    forbidden.extend(value.lower() for value in forbidden_strings or [])
    leaked = sorted({value for value in forbidden if value and value in lowered})
    if leaked:
        raise ValueError(
            "candidate source contains protected task data; matched identifiers "
            f"are intentionally redacted (count={len(leaked)})"
        )
    tree = ast.parse(source, filename=str(source_path))
    protected_modules = {
        "app.meta_harness.candidates",
        "app.meta_harness.evaluator",
        "app.meta_harness.ledger",
        "app.meta_harness.outer",
        "app.meta_harness.reports",
        "app.meta_harness.runtime",
        "app.meta_harness.sandbox",
        "app.meta_harness.tools",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    blocked = sorted(
        module
        for module in imported
        if any(
            module == protected or module.startswith(f"{protected}.")
            for protected in protected_modules
        )
    )
    if blocked:
        raise ValueError(f"candidate imports evaluator-owned modules: {blocked}")


def load_candidate_class(
    run_dir: Path,
    artifact: CandidateArtifact,
    *,
    repo_root: Path,
    research_mode: bool,
    forbidden_strings: list[str] | None = None,
) -> type[CodingAgentHarness]:
    if research_mode:
        validate_candidate_source_policy(
            run_dir,
            artifact,
            forbidden_strings=forbidden_strings,
        )
    module = load_candidate_module(run_dir, artifact, repo_root=repo_root)
    candidate_class = getattr(module, artifact.class_name)
    if not inspect.isclass(candidate_class) or not issubclass(
        candidate_class, CodingAgentHarness
    ):
        raise TypeError(
            f"{artifact.class_name} is not a CodingAgentHarness subclass"
        )
    if research_mode:
        forbidden = {"MODEL", "call_llm"}.intersection(candidate_class.__dict__)
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise TypeError(f"research candidates cannot override: {names}")
    signature = inspect.signature(candidate_class)
    required = [
        parameter.name
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    ]
    if required:
        raise TypeError(f"candidate constructor requires arguments: {required}")
    return candidate_class


def mirror_candidate_artifact(
    source_run_dir: Path,
    destination_run_dir: Path,
    candidate_id: str,
) -> CandidateArtifact:
    artifact = load_candidate_artifact(source_run_dir, candidate_id)
    if source_run_dir.resolve() == destination_run_dir.resolve():
        return artifact
    source_path = source_run_dir / artifact.source.artifact_path
    destination_source = destination_run_dir / artifact.source.artifact_path
    destination_manifest = candidate_dir(destination_run_dir, candidate_id) / "candidate.json"
    with _candidate_write_lock(destination_run_dir):
        created = atomic_create_bytes(destination_source, source_path.read_bytes())
        if not created and sha256_file(destination_source) != artifact.source.sha256:
            raise ValueError(f"candidate mirror collision: {candidate_id}")
        if destination_manifest.exists():
            existing = CandidateArtifact.model_validate_json(
                destination_manifest.read_text()
            )
            if existing != artifact:
                raise ValueError(f"candidate manifest mirror collision: {candidate_id}")
        else:
            atomic_write_json(destination_manifest, artifact)
        _update_index(destination_run_dir, artifact)
    return artifact


def candidate_manifest_path(run_dir: Path, candidate_id: str) -> str:
    return (Path("candidates") / candidate_id / "candidate.json").as_posix()
