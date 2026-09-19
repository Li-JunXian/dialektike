"""Immutable domain contracts for Dialektikḗ's M2 dialogue engine.

This module deliberately contains no provider transport, persistence, CLI, or
GUI code.  Provider adapters and presentation layers exchange these values so
that participant identity, role, model selection, and execution policy cannot
silently collapse into one another (governance 0003).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any, Protocol, TypeAlias, runtime_checkable

from dialektike.content import (
    CONTENT_BLOCK_SCHEMA_VERSION,
    CONTENT_TYPES,
    MEDIA_TYPES,
    ContentPolicy,
    content_blocks_text,
    normalize_content_block,
)
from dialektike.workspaces import ProjectWorkspaceIdentity


_OPAQUE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_MAX_OPAQUE_ID_LENGTH = 96


OpaqueId: TypeAlias = str
ControlScalar: TypeAlias = str | bool | int


def opaque_id(value: object, label: str = "identifier") -> str:
    """Return one validated, otherwise opaque provider-controlled identifier.

    Shared code constrains identifiers for safe persistence and presentation but
    never enumerates which providers, vendors, or agent systems may exist.
    Legacy ``str`` enums remain accepted because they are strings at the wire.
    """

    text = value.value if isinstance(value, Enum) else value
    if (
        not isinstance(text, str)
        or len(text) > _MAX_OPAQUE_ID_LENGTH
        or _OPAQUE_ID.fullmatch(text) is None
    ):
        raise ValueError(
            f"{label} must be a lowercase opaque id using letters, digits, dots, "
            "or hyphens"
        )
    return text


class Vendor(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class AgentSystem(str, Enum):
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


@dataclass(frozen=True, slots=True)
class ControlValue:
    """One inert value selected through a provider-declared control schema."""

    control_id: OpaqueId
    value: ControlScalar

    def __post_init__(self) -> None:
        opaque_id(self.control_id, "control id")
        if isinstance(self.value, str) and not self.value.strip():
            raise ValueError("string control values must not be empty")
        if isinstance(self.value, bool):
            return
        if isinstance(self.value, int):
            return
        if not isinstance(self.value, str):
            raise ValueError("control values must be strings, booleans, or integers")


class Role(str, Enum):
    EXECUTOR = "executor"
    AUDITOR = "auditor"


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class TurnStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TurnStage(str, Enum):
    """The protocol purpose of a model turn, independent of its role."""

    ANSWER = "answer"
    PROPOSAL = "proposal"
    AUDIT = "audit"
    SYNTHESIS = "synthesis"


@dataclass(frozen=True, slots=True)
class StructuredContentBlock:
    """One ordered, inert provider-authored response block.

    The original M2 fields and their order remain unchanged so serialized
    Markdown/code/diff/tool/citation records stay replay-compatible. New R0
    shapes use :class:`ExtendedStructuredContentBlock`, a subclass whose extra
    fields are serialized only when a new shape actually needs them.
    """

    type: str
    text: str | None = None
    code: str | None = None
    diff: str | None = None
    language: str | None = None
    title: str | None = None
    summary: str | None = None
    status: str | None = None
    label: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        required = {
            "markdown": self.text,
            "code": self.code,
            "diff": self.diff,
            "math": self.text,
            "diagram": getattr(self, "source", None),
            "tool": self.title,
            "citation": self.label,
            "file": getattr(self, "name", None),
            "image": self.label,
            "audio": self.label,
            "video": self.label,
            "editor_reference": self.label,
            "unknown": self.text,
        }
        if self.type not in CONTENT_TYPES or self.type not in required:
            raise ValueError(f"unsupported structured content block {self.type!r}")
        value = required[self.type]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{self.type} block requires non-empty content")
        if self.type == "diagram":
            language = self.language
            if not isinstance(language, str) or not language.strip():
                raise ValueError("diagram block requires a language")
        if self.type == "citation":
            checked = normalize_content_block(
                {"type": "citation", "label": self.label, "url": self.url},
                declared_types=("citation",),
            )
            if checked["type"] != "citation":
                raise ValueError("citation block requires an http(s) URL")
        if self.type in MEDIA_TYPES:
            asset_id = getattr(self, "asset_id", None)
            if not isinstance(asset_id, str):
                raise ValueError("media block requires a trusted asset identifier")
            try:
                ContentPolicy(trusted_asset_ids=frozenset({asset_id}))
            except ValueError as exc:
                raise ValueError(
                    "media block requires a safe trusted asset identifier"
                ) from exc
            if self.url is not None or getattr(self, "path", None) is not None:
                raise ValueError("media blocks cannot contain a URL or path")
        if self.type == "file" and (
            self.url is not None
            or getattr(self, "path", None) is not None
            or getattr(self, "asset_id", None) is not None
        ):
            raise ValueError("file blocks are inert metadata")
        if self.type == "editor_reference":
            path = getattr(self, "path", None)
            if not isinstance(path, str) or not path.strip():
                raise ValueError("editor reference block requires a path")
            if self.url is not None:
                raise ValueError("editor reference blocks cannot contain a URL")

    @classmethod
    def markdown(cls, text: str) -> "StructuredContentBlock":
        """Build one exact authored Markdown block through the safe mapper."""

        block = cls.from_mapped(
            {"type": "markdown", "text": text},
            declared_types=("markdown",),
        )
        if block.type != "markdown":
            raise ValueError("markdown block requires non-empty content")
        return block

    @classmethod
    def from_mapped(
        cls,
        raw: Mapping[str, Any],
        *,
        declared_types: Collection[str] | None = None,
        policy: ContentPolicy | None = None,
    ) -> "StructuredContentBlock":
        """Normalize an adapter-mapped object into an inert domain value.

        ``raw`` is already provider-neutral adapter output, never an arbitrary
        provider wire object. Unsupported, undeclared, or policy-blocked input
        becomes a readable ``unknown`` block through ``dialektike.content``.
        """

        normalized = normalize_content_block(
            raw,
            declared_types=declared_types,
            policy=policy,
        )
        common: dict[str, Any] = {
            "type": normalized["type"],
            "text": normalized.get("text"),
            "code": normalized.get("code"),
            "diff": normalized.get("diff"),
            "language": normalized.get("language"),
            "title": normalized.get("title"),
            "summary": normalized.get("summary"),
            "status": normalized.get("status"),
            "label": normalized.get("label"),
            "url": normalized.get("url"),
        }
        if normalized["type"] in {
            "math",
            "diagram",
            "file",
            "image",
            "audio",
            "video",
            "editor_reference",
            "unknown",
        }:
            return ExtendedStructuredContentBlock(
                **common,
                schema_version=normalized.get(
                    "schema_version", CONTENT_BLOCK_SCHEMA_VERSION
                ),
                display=normalized.get("display"),
                source=normalized.get("source"),
                name=normalized.get("name"),
                mime_type=normalized.get("mime_type"),
                size=normalized.get("size"),
                asset_id=normalized.get("asset_id"),
                alt=normalized.get("alt"),
                path=normalized.get("path"),
                line=normalized.get("line"),
                column=normalized.get("column"),
                provider_type=normalized.get("provider_type"),
                reason=normalized.get("reason"),
                presentation=normalized.get("presentation"),
            )
        return cls(**common)


@dataclass(frozen=True, slots=True)
class ExtendedStructuredContentBlock(StructuredContentBlock):
    """Additional inert R0 fields without changing legacy block serialization."""

    schema_version: int = CONTENT_BLOCK_SCHEMA_VERSION
    display: bool | None = None
    source: str | None = None
    name: str | None = None
    mime_type: str | None = None
    size: int | None = None
    asset_id: str | None = None
    alt: str | None = None
    path: str | None = None
    line: int | None = None
    column: int | None = None
    provider_type: str | None = None
    reason: str | None = None
    presentation: str | None = None

    def __post_init__(self) -> None:
        super(ExtendedStructuredContentBlock, self).__post_init__()
        if (
            isinstance(self.schema_version, bool)
            or self.schema_version != CONTENT_BLOCK_SCHEMA_VERSION
        ):
            raise ValueError("unsupported structured content schema version")
        if self.display is not None and not isinstance(self.display, bool):
            raise ValueError("math display must be a boolean")
        if self.size is not None and (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or self.size < 0
        ):
            raise ValueError("file size must be a non-negative integer")
        for field_name in ("line", "column"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise ValueError(
                    f"editor reference {field_name} must be a positive integer"
                )
        expected_presentation = {
            "file": "inert-metadata",
            "editor_reference": "inert-reference",
            "unknown": "inert-text",
        }.get(self.type)
        if (
            expected_presentation is not None
            and self.presentation != expected_presentation
        ):
            raise ValueError(
                f"{self.type} block requires {expected_presentation!r} presentation"
            )


class AuditorFailureAction(str, Enum):
    """Live's two admissible resolutions for failed independent audits."""

    RETRY_FAILED = "retry_failed"
    CONTINUE_WITHOUT_FAILED = "continue_without_failed"


@dataclass(frozen=True, slots=True)
class ServiceTier:
    """One speed/service tier advertised by a provider runtime."""

    tier_id: str
    display_name: str
    description: str = ""
    available: bool = True
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.tier_id.strip():
            raise ValueError("service tier id must not be empty")
        if not self.display_name.strip():
            raise ValueError("service tier display name must not be empty")
        if self.available and self.unavailable_reason is not None:
            raise ValueError("available service tier cannot have an unavailable reason")
        if not self.available and (
            self.unavailable_reason is None
            or not self.unavailable_reason.strip()
        ):
            raise ValueError("unavailable service tier requires a reason")


@dataclass(frozen=True, slots=True)
class ModelCapability:
    """A runtime-advertised (or runtime-validated) model capability."""

    model_id: str
    display_name: str
    resolved_model_id: str | None = None
    efforts: tuple[str, ...] = ()
    service_tiers: tuple[ServiceTier, ...] = ()
    is_default: bool = False
    explicit_selectable: bool = True
    authority: str = "runtime"
    available: bool = True
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model id must not be empty")
        if not self.display_name.strip():
            raise ValueError("model display name must not be empty")
        if self.resolved_model_id is not None and not self.resolved_model_id.strip():
            raise ValueError("resolved model id must be None or a non-empty string")
        if len(set(self.efforts)) != len(self.efforts):
            raise ValueError(f"duplicate efforts for model {self.model_id!r}")
        tier_ids = [tier.tier_id for tier in self.service_tiers]
        if len(set(tier_ids)) != len(tier_ids):
            raise ValueError(f"duplicate service tiers for model {self.model_id!r}")
        if not self.authority.strip():
            raise ValueError("capability authority must not be empty")
        if self.available and self.unavailable_reason is not None:
            raise ValueError("available model cannot have an unavailable reason")
        if not self.available and (
            self.unavailable_reason is None
            or not self.unavailable_reason.strip()
        ):
            raise ValueError("unavailable model requires a reason")


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    adapter_id: str
    vendor: Vendor | OpaqueId
    agent_system: AgentSystem | OpaqueId
    models: tuple[ModelCapability, ...]
    runtime_version: str | None = None
    account_route: str | None = None

    def __post_init__(self) -> None:
        runtime_id = opaque_id(self.adapter_id, "adapter id")
        opaque_id(self.vendor, "vendor id")
        opaque_id(self.agent_system, "agent-system id")
        ids = [model.model_id for model in self.models]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate model ids for adapter {self.adapter_id!r}")
        if sum(model.is_default for model in self.models) > 1:
            raise ValueError(f"adapter {runtime_id!r} declares multiple defaults")

    @property
    def runtime_id(self) -> str:
        return opaque_id(self.adapter_id, "adapter id")

    @property
    def vendor_id(self) -> str:
        return opaque_id(self.vendor, "vendor id")

    @property
    def agent_system_id(self) -> str:
        return opaque_id(self.agent_system, "agent-system id")


@dataclass(frozen=True, slots=True)
class ModelSelection:
    """A model/effort/tier selection at one point in its lifecycle.

    ``None`` means "use the runtime's native default"; it never means that a
    GUI or orchestrator may invent a value.
    """

    model_id: str | None = None
    effort: str | None = None
    service_tier: str | None = None
    features: tuple[str, ...] = ()
    controls: tuple[ControlValue, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("model_id", self.model_id),
            ("effort", self.effort),
            ("service_tier", self.service_tier),
        ):
            if value is not None and not value.strip():
                raise ValueError(f"{name} must be None or a non-empty string")
        if any(not feature.strip() for feature in self.features):
            raise ValueError("feature names must not be empty")
        if len(set(self.features)) != len(self.features):
            raise ValueError("duplicate model features")
        control_ids = [item.control_id for item in self.controls]
        if len(set(control_ids)) != len(control_ids):
            raise ValueError("duplicate provider control values")


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Requested configuration plus separately evidenced effective values."""

    requested: ModelSelection
    effective: ModelSelection | None = None
    effective_authority: str | None = None

    def __post_init__(self) -> None:
        if (self.effective is None) != (self.effective_authority is None):
            raise ValueError(
                "effective selection and effective authority must be supplied together"
            )
        if self.effective_authority is not None and not self.effective_authority.strip():
            raise ValueError("effective authority must not be empty")

    def resolved(
        self, effective: ModelSelection, authority: str
    ) -> "ModelProfile":
        """Return a new profile; never mutate or overwrite the request."""

        return ModelProfile(
            requested=self.requested,
            effective=effective,
            effective_authority=authority,
        )


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """Execution policy is intentionally independent of ModelProfile."""

    profile_id: str = "inherit-native"
    values: tuple[ControlValue, ...] = ()

    def __post_init__(self) -> None:
        opaque_id(self.profile_id, "execution profile id")
        control_ids = [item.control_id for item in self.values]
        if len(set(control_ids)) != len(control_ids):
            raise ValueError("duplicate execution-profile control values")


@dataclass(frozen=True, slots=True)
class Participant:
    participant_id: str
    vendor: Vendor | OpaqueId
    agent_system: AgentSystem | OpaqueId
    adapter_id: str
    auth_route: str
    model_profile: ModelProfile
    execution_profile: ExecutionProfile = field(default_factory=ExecutionProfile)

    def __post_init__(self) -> None:
        if not self.participant_id.strip():
            raise ValueError("participant_id must not be empty")
        opaque_id(self.adapter_id, "adapter id")
        opaque_id(self.vendor, "vendor id")
        opaque_id(self.agent_system, "agent-system id")
        if not self.auth_route.strip():
            raise ValueError("auth_route must not be empty")

    @property
    def runtime_id(self) -> str:
        return opaque_id(self.adapter_id, "adapter id")

    @property
    def vendor_id(self) -> str:
        return opaque_id(self.vendor, "vendor id")

    @property
    def agent_system_id(self) -> str:
        return opaque_id(self.agent_system, "agent-system id")


@dataclass(frozen=True, slots=True, init=False)
class RoundAssignment:
    round_number: int
    executor_id: str
    auditor_ids: tuple[str, ...]

    def __init__(
        self,
        round_number: int,
        executor_id: str,
        auditor_id: str | None = None,
        *,
        auditor_ids: tuple[str, ...] | None = None,
    ) -> None:
        """Create a review-round assignment.

        ``auditor_id`` remains accepted for the M2 single-auditor wire format;
        new callers should supply the ordered ``auditor_ids`` tuple.  Keeping
        the compatibility input here lets the protocol engine evolve without
        silently changing already-persisted M2 configuration documents.
        """

        if auditor_id is not None and auditor_ids is not None:
            raise ValueError("supply auditor_id or auditor_ids, not both")
        chosen = auditor_ids if auditor_ids is not None else (auditor_id,)
        object.__setattr__(self, "round_number", round_number)
        object.__setattr__(self, "executor_id", executor_id)
        object.__setattr__(
            self,
            "auditor_ids",
            tuple(item for item in chosen if item is not None),
        )
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.round_number < 1:
            raise ValueError("round numbers start at 1")
        if not self.executor_id.strip():
            raise ValueError("round executor id must not be empty")
        if not self.auditor_ids:
            raise ValueError("a review round requires at least one auditor")
        if any(not item.strip() for item in self.auditor_ids):
            raise ValueError("round auditor ids must not be empty")
        if len(set(self.auditor_ids)) != len(self.auditor_ids):
            raise ValueError("round auditor ids must be unique")
        if self.executor_id in self.auditor_ids:
            raise ValueError("executor and auditors must be different participants")

    @property
    def auditor_id(self) -> str:
        """Compatibility view for code that still supports one auditor only."""

        if len(self.auditor_ids) != 1:
            raise ValueError("this review round has more than one auditor")
        return self.auditor_ids[0]


@dataclass(frozen=True, slots=True)
class RunConfig:
    prompt: str
    participants: tuple[Participant, ...]
    assignments: tuple[RoundAssignment, ...]
    mode: str = "review"
    speaker_id: str | None = None
    review_answer: str | None = None

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("run prompt must not be empty")
        if self.mode not in {"chat", "review"}:
            raise ValueError("run mode must be 'chat' or 'review'")
        if self.review_answer is not None and (
            not isinstance(self.review_answer, str) or not self.review_answer.strip()
        ):
            raise ValueError("review answer must be nonempty text")
        if self.mode == "chat":
            if len(self.participants) != 1:
                raise ValueError("chat requires exactly one participant")
            if self.assignments:
                raise ValueError("chat cannot have review assignments")
            if self.speaker_id != self.participants[0].participant_id:
                raise ValueError("chat speaker_id must identify its sole participant")
            if self.review_answer is not None:
                raise ValueError("chat cannot supply a review answer")
            return
        if self.speaker_id is not None:
            raise ValueError("review uses round assignments, not speaker_id")
        if len(self.participants) < 2:
            raise ValueError("a dialectic run requires at least two participants")
        if not self.assignments:
            raise ValueError("a dialectic run requires at least one round")
        expected = tuple(range(1, len(self.assignments) + 1))
        actual = tuple(item.round_number for item in self.assignments)
        if actual != expected:
            raise ValueError(
                f"round assignments must be contiguous and ordered: {actual!r}"
            )
        executors = {item.executor_id for item in self.assignments}
        if len(executors) != 1:
            raise ValueError("a run must keep exactly one executor across all rounds")
        auditor_orders = {item.auditor_ids for item in self.assignments}
        if len(auditor_orders) != 1:
            raise ValueError(
                "auditor membership and ordering must remain stable across rounds"
            )

    @classmethod
    def fixed_roles(
        cls,
        *,
        prompt: str,
        participants: tuple[Participant, ...],
        executor_id: str,
        auditor_id: str | None = None,
        auditor_ids: tuple[str, ...] | None = None,
        rounds: int,
        review_answer: str | None = None,
    ) -> "RunConfig":
        if rounds < 1:
            raise ValueError("round count must be at least 1")
        return cls(
            prompt=prompt,
            participants=participants,
            review_answer=review_answer,
            assignments=tuple(
                RoundAssignment(
                    number,
                    executor_id,
                    auditor_id,
                    auditor_ids=auditor_ids,
                )
                for number in range(1, rounds + 1)
            ),
        )


@dataclass(frozen=True, slots=True)
class TurnPaths:
    """Run-scoped filesystem locations supplied to, never chosen by, adapters."""

    run_path: str
    raw_dir: str
    workspace_dir: str
    decisions_path: str
    workspace_source: str = "generated"
    workspace_identity: ProjectWorkspaceIdentity | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("run_path", self.run_path),
            ("raw_dir", self.raw_dir),
            ("workspace_dir", self.workspace_dir),
            ("decisions_path", self.decisions_path),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        if self.workspace_source not in {"generated", "project"}:
            raise ValueError("workspace_source must be 'generated' or 'project'")
        if self.workspace_source == "project" and self.workspace_identity is None:
            raise ValueError("project workspace paths require a bound identity")
        if self.workspace_source == "generated" and self.workspace_identity is not None:
            raise ValueError("generated workspace paths cannot carry a project identity")


@dataclass(frozen=True, slots=True)
class TurnRequest:
    run_id: str
    round_number: int
    turn_number: int
    role: Role
    participant: Participant
    original_prompt: str
    input_text: str
    paths: TurnPaths
    stage: TurnStage
    attempt_number: int = 1
    fresh_session: bool = True

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("turn attempt numbers start at 1")
        if self.stage is TurnStage.AUDIT and self.role is not Role.AUDITOR:
            raise ValueError("audit turns require the auditor role")
        if self.stage in {TurnStage.ANSWER, TurnStage.PROPOSAL, TurnStage.SYNTHESIS} and (
            self.role is not Role.EXECUTOR
        ):
            raise ValueError("answer, proposal and synthesis turns require the executor role")


@dataclass(frozen=True, slots=True)
class TurnResult:
    text: str
    model_profile: ModelProfile
    account_route: str
    runtime_version: str | None = None
    evidence: tuple[tuple[str, str], ...] = ()
    blocks: tuple[StructuredContentBlock, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("turn result text must not be empty")
        if self.model_profile.effective is None:
            raise ValueError("turn result requires authoritative effective model data")
        if not self.account_route.strip():
            raise ValueError("turn result account route must not be empty")
        keys = [key for key, _ in self.evidence]
        if len(set(keys)) != len(keys):
            raise ValueError("turn result evidence keys must be unique")
        if self.blocks and content_blocks_text(
            asdict(block) for block in self.blocks
        ) != self.text:
            raise ValueError(
                "ordered content blocks must reproduce the authoritative text"
            )


@dataclass(frozen=True, slots=True)
class TurnRecord:
    round_number: int
    turn_number: int
    role: Role
    participant_id: str
    adapter_id: str
    status: TurnStatus
    input_text: str
    stage: TurnStage | None = None
    attempt_number: int = 1
    text: str = ""
    blocks: tuple[StructuredContentBlock, ...] = ()
    evidence: tuple[tuple[str, str], ...] = ()
    model_profile: ModelProfile | None = None
    account_route: str | None = None
    runtime_version: str | None = None
    failure: str | None = None

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("turn attempt numbers start at 1")
        if self.stage is TurnStage.AUDIT and self.role is not Role.AUDITOR:
            raise ValueError("audit records require the auditor role")
        if self.stage in {TurnStage.ANSWER, TurnStage.PROPOSAL, TurnStage.SYNTHESIS} and (
            self.role is not Role.EXECUTOR
        ):
            raise ValueError("proposal and synthesis records require the executor role")
        keys = [key for key, _ in self.evidence]
        if len(set(keys)) != len(keys):
            raise ValueError("turn record evidence keys must be unique")
        if self.blocks and content_blocks_text(
            asdict(block) for block in self.blocks
        ) != self.text:
            raise ValueError(
                "ordered content blocks must reproduce the authoritative text"
            )


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run_id: str
    status: RunStatus
    turns: tuple[TurnRecord, ...]
    run_path: str
    stop_reason: str | None = None
    failure: str | None = None
    display_failure: str | None = None


@runtime_checkable
class CancellationSignal(Protocol):
    @property
    def cancelled(self) -> bool:
        ...

    @property
    def reason(self) -> str | None:
        ...

    async def wait(self) -> None:
        ...


@runtime_checkable
class ProviderAdapter(Protocol):
    """Provider boundary used equally by live adapters and deterministic fakes."""

    adapter_id: str
    relay_provider_id: str

    async def discover_capabilities(self) -> AdapterCapabilities:
        ...

    async def run_turn(
        self, request: TurnRequest, cancellation: CancellationSignal
    ) -> TurnResult:
        ...

    async def interrupt(self) -> None:
        ...

    async def close(self) -> None:
        ...
