"""Versioned contracts for candidates, evaluation, evidence, and lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1
HARNESS_API_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MeasurementStatus(str, Enum):
    MEASURED = "measured"
    UNKNOWN = "unknown"
    SYNTHETIC = "synthetic"
    NOT_APPLICABLE = "not_applicable"


class RunMode(str, Enum):
    RESEARCH = "research"
    AUTONOMOUS = "autonomous"


class ProposalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source_path: str | None = None
    class_name: str | None = None
    import_path: str | None = None
    parent: str | None = None
    hypothesis: str = ""
    axis: Literal["exploration", "exploitation"] = "exploration"
    expected_score_delta: float | None = Field(default=None, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def validate_source(self) -> "ProposalCandidate":
        if not self.source_path and not self.import_path:
            raise ValueError("proposal requires source_path or import_path")
        if self.source_path and not self.class_name and not self.import_path:
            raise ValueError("source_path proposals require class_name")
        return self


class PendingEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    iteration: int = Field(ge=1)
    candidates: list[ProposalCandidate] = Field(min_length=1)


class CandidateStatus(str, Enum):
    MATERIALIZED = "materialized"
    INVALID = "invalid"
    PENDING = "pending"
    EVALUATED = "evaluated"
    FRONTIER = "frontier"
    REJECTED = "rejected"
    BEST = "best"


class FailureCategory(str, Enum):
    AGENT = "agent_failure"
    CANDIDATE = "candidate_failure"
    EVALUATOR = "evaluator_failure"
    MODEL = "model_failure"
    POLICY = "policy_denial"
    SANDBOX = "sandbox_failure"
    TIMEOUT = "timeout"
    VERIFICATION = "verification_failure"
    UNKNOWN = "unknown"


class MetricValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int | float | None = None
    status: MeasurementStatus = MeasurementStatus.UNKNOWN
    unit: str | None = None
    source: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> MetricValue:
        if self.status in {MeasurementStatus.MEASURED, MeasurementStatus.SYNTHETIC}:
            if self.value is None:
                raise ValueError(f"{self.status.value} metrics require a value")
        elif self.value is not None:
            raise ValueError(f"{self.status.value} metrics must not carry a value")
        return self

    @classmethod
    def measured(
        cls,
        value: int | float,
        *,
        unit: str | None = None,
        source: str | None = None,
    ) -> MetricValue:
        return cls(
            value=value,
            status=MeasurementStatus.MEASURED,
            unit=unit,
            source=source,
        )

    @classmethod
    def synthetic(
        cls,
        value: int | float,
        *,
        unit: str | None = None,
        source: str | None = None,
    ) -> MetricValue:
        return cls(
            value=value,
            status=MeasurementStatus.SYNTHETIC,
            unit=unit,
            source=source,
        )

    @classmethod
    def unknown(
        cls,
        *,
        unit: str | None = None,
        source: str | None = None,
    ) -> MetricValue:
        return cls(
            value=None,
            status=MeasurementStatus.UNKNOWN,
            unit=unit,
            source=source,
        )

    @classmethod
    def not_applicable(cls, *, source: str | None = None) -> MetricValue:
        return cls(
            value=None,
            status=MeasurementStatus.NOT_APPLICABLE,
            source=source,
        )


class UsageMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="tokens")
    )
    output_tokens: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="tokens")
    )
    cached_tokens: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="tokens")
    )
    estimated_cost_usd: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="usd")
    )
    billed_cost_usd: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="usd")
    )
    wall_seconds: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="seconds")
    )
    model_calls: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="calls")
    )
    tool_calls: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="calls")
    )
    act_turns: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="turns")
    )
    verification_retries: MetricValue = Field(
        default_factory=lambda: MetricValue.unknown(unit="retries")
    )


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str
    artifact_path: str
    media_type: str = "application/octet-stream"
    size_bytes: int = Field(ge=0)


class SourceArtifact(ArtifactRef):
    kind: Literal["python_module"] = "python_module"


class ComponentKind(str, Enum):
    PROMPT = "prompt"
    SKILL = "skill"
    MEMORY = "memory"
    SUBAGENT = "subagent"
    CONTROL_FLOW = "control_flow"
    TOOL_INTERFACE = "tool_interface"


class HarnessComponentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str
    kind: ComponentKind
    version: str | None = None
    sha256: str | None = None
    scope: Literal["attempt", "run", "project", "global"] = "run"


class Provenance(BaseModel):
    model_config = ConfigDict(extra="allow")

    git_commit: str | None = None
    git_dirty: bool | None = None
    runtime_sha256: str | None = None
    dependency_lock_sha256: str | None = None
    proposer_session_id: str | None = None
    authorization_profile: str
    created_at: str = Field(default_factory=utc_now)


class EvaluationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    policy_id: str
    mode: RunMode = RunMode.RESEARCH
    task_visibility: Literal["search", "holdout"] = "search"
    sandbox_profile: str = "local-process-v1"
    runtime_adapter: str = "python-pytest-v1"
    execution_backend: str = "fixed-langgraph-v1"
    inner_model: str
    model_provider: str = "anthropic"
    trials: int = Field(default=1, ge=1)
    workers: int = Field(default=1, ge=1)
    allow_global_memory: bool = False
    allow_recursive_children: bool = False
    synthetic: bool = False


class CandidateArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    candidate_id: str
    name: str
    run_id: str
    parent_ids: list[str] = Field(default_factory=list)
    class_name: str
    source: SourceArtifact
    harness_api_version: int = HARNESS_API_VERSION
    inner_model: str
    model_provider: str = "anthropic"
    components: list[HarnessComponentRef] = Field(default_factory=list)
    evaluation_policy_id: str
    provenance: Provenance
    created_at: str = Field(default_factory=utc_now)


class CandidateRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_id: str
    name: str
    artifact_path: str
    parent_ids: list[str] = Field(default_factory=list)
    parent: str | None = None
    hypothesis: str = ""
    axis: Literal["exploration", "exploitation"] = "exploitation"
    expected_score_delta: float | None = None
    iteration: int = 0
    status: CandidateStatus = CandidateStatus.MATERIALIZED
    scores: dict[str, Any] | None = None
    delta: float | None = None
    import_path: str | None = None
    cost_usd: float | None = None
    validation_error: str | None = None


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    tier: str
    instruction: str
    test_command: str
    expected_files_changed: list[str] = Field(default_factory=list)
    runtime_adapter: str = "python-pytest-v1"
    visibility: Literal["search", "holdout"] = "search"
    source_path: str
    sha256: str


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    candidate_id: str
    candidate_manifest_sha256: str
    task_id: str
    task_sha256: str
    attempt_id: str
    passed: bool
    score: float
    failure_category: FailureCategory | None = None
    test_summary: dict[str, Any]
    lint_summary: dict[str, Any]
    scope_summary: dict[str, Any]
    usage: UsageMetrics
    retry_count: int = Field(ge=0)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    evaluator_version: str
    sandbox_profile: str
    runtime_adapter: str
    execution_backend: str
    synthetic: bool = False
    started_at: str
    finished_at: str


class TaskAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pass_rate: float
    trials: list[bool]
    scores: list[float]
    attempt_ids: list[str]


class CandidateEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    candidate_id: str
    candidate_name: str
    candidate_manifest_sha256: str
    policy_id: str
    evaluator_version: str
    sandbox_profile: str
    runtime_adapter: str
    execution_backend: str
    task_hashes: dict[str, str]
    n_tasks: int
    n_trials_per_task: int
    accuracy: MetricValue
    per_task: dict[str, TaskAggregate]
    usage: UsageMetrics
    task_results: list[TaskResult]
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    synthetic: bool = False
    started_at: str
    finished_at: str


class ArtifactRetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_candidate_source: bool = True
    keep_evaluation_results: bool = True
    keep_raw_traces: bool = True
    keep_content_addressed_artifacts: bool = True
    cleanup_mode: Literal["manual", "never"] = "manual"


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = SCHEMA_VERSION
    run_id: str
    mode: RunMode
    status: str
    git_commit: str | None = None
    git_dirty: bool | None = None
    runtime_sha256: str | None = None
    dependency_lock_sha256: str | None = None
    policy: EvaluationPolicy
    parent_policy: str = "best_accuracy"
    search_task_ids: list[str]
    holdout_visible: bool = False
    persistence_backend: str
    artifact_retention: ArtifactRetentionPolicy = Field(
        default_factory=ArtifactRetentionPolicy
    )
    synthetic: bool = False
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class LedgerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    event_id: str
    event_type: str
    run_id: str
    entity_type: str
    entity_id: str
    thread_id: str | None = None
    attempt_id: str | None = None
    idempotency_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class RefinementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    refinement_id: str
    kind: Literal["prompt", "memory", "skill", "subagent", "control_flow", "tool_interface"]
    scope: Literal["attempt", "run", "project", "global"]
    target: str
    parent_version: str | None = None
    proposed_version: str
    rationale: str
    evidence: list[dict[str, str]]
    expected_outcome: str
    before_hash: str | None = None
    after_hash: str
    before_artifact: ArtifactRef | None = None
    after_artifact: ArtifactRef
    applied_path: str | None = None
    status: Literal["proposed", "applied", "rejected", "rolled_back"] = "proposed"
    rollback_of: str | None = None
    created_at: str = Field(default_factory=utc_now)
    applied_at: str | None = None
    rolled_back_at: str | None = None
