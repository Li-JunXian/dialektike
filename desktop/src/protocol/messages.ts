import type {
  CapabilityCatalog,
  ControlScalar,
  EffectiveSettings,
  ProviderDescriptor,
  RoleId,
  RuntimeId,
} from "../state/model";
import { safeHttpUrl } from "../security/safeHttpUrl";
import { isOpaqueId } from "../state/model";

export const SIDECAR_PROTOCOL = "dialektike.sidecar.v1" as const;
export const ORDINARY_EVENT_CHANNEL = "dialektike:event";
export const PERMISSION_EVENT_CHANNEL = "dialektike:permission";
export const PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT =
  "Participants use this folder as their native working directory. Actions the native runtime auto-permits may modify it without a Dialektikḗ card; those actions remain audited.";

export interface CommandEnvelope {
  protocol: typeof SIDECAR_PROTOCOL;
  id: string;
  command:
    | "initialize"
    | "capabilities.discover"
    | "run.start"
    | "run.stop"
    | "project.list"
    | "project.register"
    | "topic.list"
    | "topic.search"
    | "topic.create"
    | "topic.read"
    | "topic.evidence.read"
    | "topic.update"
    | "topic.delete"
    | "topic.project.set"
    | "topic.checkpoint.draft"
    | "topic.checkpoint.approve"
    | "topic.checkpoint.deactivate"
    | "audit.failure.resolve"
    | "permission.respond"
    | "shutdown";
  payload: Record<string, unknown>;
}

export interface EventEnvelope {
  protocol: typeof SIDECAR_PROTOCOL;
  event: string;
  payload: Record<string, unknown>;
  request_id?: string;
}

export interface StartParticipant {
  participant_id: string;
  role: RoleId;
  order: number;
  runtime_id: RuntimeId;
  requested: {
    model: string;
    effort: string;
    service_tier: string;
    controls?: Record<string, ControlScalar>;
    execution_profile?: {
      profile_id: string;
      values: Record<string, ControlScalar>;
    };
  };
}

export interface StartRunInput {
  mode?: "chat" | "review";
  speaker_id?: string;
  review_target?: { cycle_id: string; message_id: string };
  topic_id: string;
  prompt: string;
  rounds: number;
  participants: StartParticipant[];
}

export interface TopicListInput {
  archived?: boolean;
}

export interface TopicSearchInput {
  query: string;
  include_archived?: boolean;
  limit?: number;
}

export interface TopicParticipantInput extends StartParticipant {}

export interface TopicCreateInput {
  title?: string;
  rounds: number;
  participants: TopicParticipantInput[];
  project_id?: string;
}

export interface TopicReadInput {
  topic_id: string;
}

export interface TopicEvidenceReadInput {
  topic_id: string;
}

export interface TopicUpdateInput {
  topic_id: string;
  title?: string;
  pinned?: boolean;
  archived?: boolean;
  rounds?: number;
  participants?: TopicParticipantInput[];
}

export interface TopicDeleteInput {
  topic_id: string;
}

export interface ProjectRegisterInput {
  name?: string;
  acknowledgement: typeof PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT;
}

export interface TopicProjectSetInput {
  topic_id: string;
  project_id: string | null;
}

export interface TopicCheckpointDraftInput {
  topic_id: string;
}

export interface TopicCheckpointApproveInput {
  topic_id: string;
  checkpoint_id: string;
}

export interface TopicCheckpointDeactivateInput {
  topic_id: string;
}

export interface AuditFailureResolutionInput {
  run_id: string;
  failure_id: string;
  resolution: "retry_failed" | "continue_without_failed";
}

export interface StopRunInput {
  run_id?: string;
}

export type PermissionDecision = "allow_once" | "deny";

export interface PermissionDecisionInput {
  permission_id: string;
  decision: PermissionDecision;
}

export interface PermissionRequest {
  permission_id: string;
  runtime_id: RuntimeId;
  request_kind: string;
  title: string;
  card: string;
  native_payload: Record<string, unknown>;
  annotations: Record<string, unknown>;
}

export interface ConversationMessage {
  id: string;
  role: RoleId;
  runtime_id: RuntimeId;
  text: string;
  round: number;
  cycle?: number;
  /**
   * M2 visual contract. Older sidecars omit these fields, so the desktop
   * renderer falls back to the existing round/role ordering without claiming
   * a synthesis phase that was not emitted.
   */
  participant_id?: string;
  cycle_id?: string;
  speaker_id?: string;
  stage?: "answer" | "proposal" | "audit" | "rebuttal" | "synthesis";
  verdict?: "accept" | "challenge" | "insufficient-evidence";
  created_at?: string;
  token_count?: number;
  effective?: EffectiveSettings | null;
  blocks?: StructuredContentBlock[];
  partial?: boolean;
}

export type StructuredContentBlock =
  | { type: "markdown"; text: string }
  | { type: "code"; code: string; language?: string; title?: string }
  | { type: "diff"; diff: string; title?: string }
  | { type: "math"; text: string; display: boolean }
  | { type: "diagram"; source: string; language: string; title?: string }
  | { type: "tool"; title: string; summary?: string; status?: string }
  | { type: "citation"; label: string; url: string }
  | {
      type: "file";
      name: string;
      mimeType?: string;
      size?: number;
      assetId?: string;
    }
  | {
      type: "media";
      mediaType: "image" | "audio" | "video";
      label: string;
      mimeType?: string;
      assetId?: string;
      alt?: string;
    }
  | {
      type: "editor-reference";
      label: string;
      path: string;
      line?: number;
      column?: number;
    }
  | { type: "unknown"; sourceType: string; label: string; text?: string };

export interface LivePromptMessage {
  id: string;
  text: string;
  cycle: number;
  created_at?: string;
}

export interface TopicSummary {
  id: string;
  title: string;
  pinned: boolean;
  archived: boolean;
  created_at?: string;
  updated_at?: string;
  active_run?: boolean;
  projectId: string | null;
}

export interface ProjectSummary {
  id: string;
  name: string;
  available: boolean;
  registeredAt?: string;
}

export interface TopicDetail {
  summary: TopicSummary;
  rounds: number;
  participants: TopicParticipantInput[];
  prompts: LivePromptMessage[];
  messages: ConversationMessage[];
  contextCheckpoints: TopicContextCheckpoint[];
  activeContextCheckpointId: string | null;
}

export interface SearchSnippetSegment {
  text: string;
  highlighted: boolean;
}

export interface TopicSearchOccurrence {
  occurrenceId: string;
  topicId: string;
  topicTitle: string;
  archived: boolean;
  sourceKind: string;
  sourceAnchor: string;
  sourceField: string;
  stage?: string;
  speaker?: string;
  timestamp?: string;
  matchStartUtf8: number;
  matchEndUtf8: number;
  prefixTruncated: boolean;
  suffixTruncated: boolean;
  segments: SearchSnippetSegment[];
}

export interface TopicContextCheckpoint {
  checkpointId: string;
  topicId: string;
  status: "draft" | "active" | "inactive";
  summary: string;
  sourceDigest: string;
  sourceStartAnchor: string;
  sourceEndAnchor: string;
  sourceEntryCount: number;
  beforeUtf8Bytes: number;
  afterUtf8Bytes: number;
  creator: Record<string, unknown>;
  createdAt?: string;
  approvedAt?: string;
}

export type ActivityStage = "answer" | "proposal" | "audit" | "synthesis";
export type ActivityStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "paused";

export interface ParticipantActivity {
  run_id: string;
  participant_id: string;
  runtime_id: RuntimeId;
  stage: ActivityStage;
  status: ActivityStatus;
  round: number;
  cycle: number;
  /** Native summaries are shown only when the trusted sidecar says so. */
  native_summary?: string;
}

export interface PausedAuditFailure {
  run_id: string;
  failure_id: string;
  round: number;
  cycle: number;
  failed: Array<{
    participant_id: string;
    runtime_id: RuntimeId;
    message: string;
  }>;
}

export interface RuntimeGateEvidence {
  runtime_id: RuntimeId;
  catalog_verified: boolean;
  account_route: string;
  runtime_version: string | null;
  turn_revalidated_count: number;
  model_providers: string[];
}

export interface RateLimitEvidence {
  observed_event_count: number;
  by_runtime: Partial<Record<RuntimeId, number>>;
  warning_count: number;
  warnings: Array<{ runtime_id: RuntimeId; message: string }>;
  capture_parse_failures: number;
}

export interface EvidenceSummary {
  schema_version: 1;
  run_id: string;
  run_status: string;
  environment_gate: {
    verified: boolean;
    policy: string | null;
    kept: string[];
    dropped_count: number | null;
  };
  runtime_gates: RuntimeGateEvidence[];
  rate_limits: RateLimitEvidence;
  governance: {
    derived_from_verified_chain: boolean;
    permission_decisions: {
      allow: number;
      deny: number;
      total: number;
    } | null;
    audit_counts: Record<string, number> | null;
  };
  raw_capture: {
    file_count: number;
    total_bytes: number;
    turns_with_capture: number;
    by_category: Record<string, number>;
    contents_exposed: false;
  };
  decision_chain: {
    verified: boolean;
    record_count: number | null;
    head_sha256: string | null;
    error: string | null;
  };
  event_log_readable: boolean;
}

export interface TopicEvidenceLoaded {
  topicId: string;
  summary: EvidenceSummary;
}

export interface TopicEvidenceUnavailable {
  topicId: string;
  message: string;
}

export interface CapabilitiesPayload {
  catalog: CapabilityCatalog;
}

export interface SupervisorStatus {
  running: boolean;
  pid: number | null;
  generation: number | null;
}

export function isEventEnvelope(value: unknown): value is EventEnvelope {
  if (!isRecord(value)) {
    return false;
  }
  return (
    value.protocol === SIDECAR_PROTOCOL &&
    typeof value.event === "string" &&
    value.event.length > 0 &&
    isRecord(value.payload) &&
    (value.request_id === undefined ||
      typeof value.request_id === "string")
  );
}

export function parsePermissionRequest(
  envelope: EventEnvelope,
): PermissionRequest | null {
  if (envelope.event !== "permission.request") {
    return null;
  }
  const payload = envelope.payload;
  if (
    typeof payload.permission_id !== "string" ||
    !payload.permission_id ||
    !isRuntimeId(payload.runtime_id) ||
    (payload.request_kind !== undefined &&
      !isSchemaToken(payload.request_kind)) ||
    typeof payload.title !== "string" ||
    typeof payload.card !== "string" ||
    !isRecord(payload.native_payload) ||
    !isRecord(payload.annotations)
  ) {
    return null;
  }
  return {
    permission_id: payload.permission_id,
    runtime_id: payload.runtime_id,
    request_kind:
      typeof payload.request_kind === "string"
        ? payload.request_kind
        : "native-request",
    title: payload.title,
    card: payload.card,
    native_payload: payload.native_payload,
    annotations: payload.annotations,
  };
}

export function parseCapabilityCatalog(
  value: unknown,
): CapabilityCatalog | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const catalog: CapabilityCatalog = {};
  for (const capabilities of value) {
    if (!isRecord(capabilities) || !isRuntimeId(capabilities.runtime_id)) {
      return null;
    }
    const runtimeId = capabilities.runtime_id;
    if (catalog[runtimeId]) return null;
    const descriptor = parseProviderDescriptor(capabilities.descriptor);
    const availability = parseAvailability(capabilities.availability);
    if (
      !descriptor ||
      descriptor.runtimeId !== runtimeId ||
      !availability ||
      (capabilities.account_route !== null &&
        typeof capabilities.account_route !== "string") ||
      (capabilities.runtime_version !== null &&
        typeof capabilities.runtime_version !== "string") ||
      !Array.isArray(capabilities.models)
    ) {
      return null;
    }
    const models = capabilities.models.map(parseModelCapability);
    if (models.some((model) => model === null)) {
      return null;
    }
    catalog[runtimeId] = {
      runtimeId,
      descriptor,
      availability,
      accountRoute:
        typeof capabilities.account_route === "string"
          ? capabilities.account_route
          : null,
      runtimeVersion:
        typeof capabilities.runtime_version === "string"
          ? capabilities.runtime_version
          : null,
      models: models.filter((model) => model !== null),
    };
  }
  return catalog;
}

export function parseConversationMessage(
  value: unknown,
): ConversationMessage | null {
  if (!isRecord(value)) {
    return null;
  }
  if (
    typeof value.id === "string" &&
    isRoleId(value.role) &&
    isRuntimeId(value.runtime_id) &&
    typeof value.text === "string" &&
    Number.isInteger(value.round) &&
    Number(value.round) >= 1 &&
    (value.partial === undefined || typeof value.partial === "boolean")
  ) {
    const effective = parseEffectiveSettings(value.effective);
    if (value.effective !== undefined && value.effective !== null && !effective) {
      return null;
    }
    const blocks = parseStructuredContentBlocks(value.blocks);
    if (value.blocks !== undefined && !blocks) {
      return null;
    }
    return {
      id: value.id,
      role: value.role,
      runtime_id: value.runtime_id,
      text: value.text,
      round: Number(value.round),
      cycle: isPositiveInteger(value.cycle) ? Number(value.cycle) : undefined,
      participant_id:
        typeof value.participant_id === "string" && value.participant_id
          ? value.participant_id
          : undefined,
      cycle_id: typeof value.cycle_id === "string" ? value.cycle_id : undefined,
      speaker_id: typeof value.speaker_id === "string" ? value.speaker_id : undefined,
      stage: isConversationStage(value.stage) ? value.stage : undefined,
      verdict: isAuditVerdict(value.verdict) ? value.verdict : undefined,
      created_at:
        typeof value.created_at === "string" && value.created_at
          ? value.created_at
          : undefined,
      token_count: isNonnegativeInteger(value.token_count)
        ? Number(value.token_count)
        : undefined,
      effective,
      blocks: blocks ?? undefined,
      partial:
        typeof value.partial === "boolean" ? value.partial : undefined,
    };
  }
  return null;
}

export function parseTopicSummary(value: unknown): TopicSummary | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !value.id ||
    typeof value.title !== "string" ||
    typeof value.pinned !== "boolean" ||
    typeof value.archived !== "boolean"
  ) {
    return null;
  }
  if (
    (value.created_at !== undefined && typeof value.created_at !== "string") ||
    (value.updated_at !== undefined && typeof value.updated_at !== "string") ||
    (value.active_run !== undefined && typeof value.active_run !== "boolean") ||
    (value.project_id !== undefined &&
      value.project_id !== null &&
      (typeof value.project_id !== "string" || !value.project_id))
  ) {
    return null;
  }
  return {
    id: value.id,
    title: value.title,
    pinned: value.pinned,
    archived: value.archived,
    created_at: typeof value.created_at === "string" ? value.created_at : undefined,
    updated_at: typeof value.updated_at === "string" ? value.updated_at : undefined,
    active_run: typeof value.active_run === "boolean" ? value.active_run : undefined,
    projectId: typeof value.project_id === "string" ? value.project_id : null,
  };
}

export function parseProjectSummary(value: unknown): ProjectSummary | null {
  if (
    !isRecord(value) ||
    Object.keys(value).some(
      (key) => !["id", "name", "available", "registered_at"].includes(key),
    ) ||
    typeof value.id !== "string" ||
    !value.id ||
    typeof value.name !== "string" ||
    !value.name ||
    typeof value.available !== "boolean" ||
    (value.registered_at !== undefined &&
      typeof value.registered_at !== "string")
  ) return null;
  return {
    id: value.id,
    name: value.name,
    available: value.available,
    registeredAt:
      typeof value.registered_at === "string" ? value.registered_at : undefined,
  };
}

export function parseProjectSummaries(value: unknown): ProjectSummary[] | null {
  if (!Array.isArray(value)) return null;
  const projects = value.map(parseProjectSummary);
  return projects.some((project) => project === null)
    ? null
    : projects.filter((project): project is ProjectSummary => project !== null);
}

export function parseTopicSummaries(value: unknown): TopicSummary[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const topics = value.map(parseTopicSummary);
  return topics.some((topic) => topic === null)
    ? null
    : topics.filter((topic): topic is TopicSummary => topic !== null);
}

export function parseTopicSearchOccurrences(
  value: unknown,
): TopicSearchOccurrence[] | null {
  if (!Array.isArray(value)) return null;
  const results: TopicSearchOccurrence[] = [];
  for (const item of value) {
    if (
      !isRecord(item) ||
      typeof item.occurrence_id !== "string" ||
      !item.occurrence_id ||
      typeof item.topic_id !== "string" ||
      !item.topic_id ||
      typeof item.topic_title !== "string" ||
      typeof item.archived !== "boolean" ||
      typeof item.source_kind !== "string" ||
      typeof item.source_anchor !== "string" ||
      !item.source_anchor ||
      typeof item.source_field !== "string" ||
      !isNonnegativeInteger(item.match_start_utf8) ||
      !isNonnegativeInteger(item.match_end_utf8) ||
      Number(item.match_end_utf8) < Number(item.match_start_utf8) ||
      typeof item.prefix_truncated !== "boolean" ||
      typeof item.suffix_truncated !== "boolean" ||
      !Array.isArray(item.snippet_segments)
    ) return null;
    const segments = item.snippet_segments.map((segment) =>
      isRecord(segment) &&
      typeof segment.text === "string" &&
      typeof segment.highlighted === "boolean"
        ? { text: segment.text, highlighted: segment.highlighted }
        : null,
    );
    if (segments.some((segment) => segment === null)) return null;
    results.push({
      occurrenceId: item.occurrence_id,
      topicId: item.topic_id,
      topicTitle: item.topic_title,
      archived: item.archived,
      sourceKind: item.source_kind,
      sourceAnchor: item.source_anchor,
      sourceField: item.source_field,
      stage: typeof item.stage === "string" ? item.stage : undefined,
      speaker: typeof item.speaker === "string" ? item.speaker : undefined,
      timestamp:
        typeof item.timestamp === "string" ? item.timestamp : undefined,
      matchStartUtf8: Number(item.match_start_utf8),
      matchEndUtf8: Number(item.match_end_utf8),
      prefixTruncated: item.prefix_truncated,
      suffixTruncated: item.suffix_truncated,
      segments: segments.filter(
        (segment): segment is NonNullable<typeof segment> => segment !== null,
      ),
    });
  }
  return results;
}

export function parseTopicContextCheckpoint(
  value: unknown,
): TopicContextCheckpoint | null {
  if (
    !isRecord(value) ||
    typeof value.checkpoint_id !== "string" ||
    !value.checkpoint_id ||
    typeof value.topic_id !== "string" ||
    !value.topic_id ||
    (value.status !== "draft" &&
      value.status !== "active" &&
      value.status !== "inactive") ||
    typeof value.summary !== "string" ||
    !value.summary ||
    typeof value.source_digest !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.source_digest) ||
    typeof value.source_start_anchor !== "string" ||
    !value.source_start_anchor ||
    typeof value.source_end_anchor !== "string" ||
    !value.source_end_anchor ||
    !isPositiveInteger(value.source_entry_count) ||
    !isNonnegativeInteger(value.before_utf8_bytes) ||
    !isNonnegativeInteger(value.after_utf8_bytes) ||
    !isRecord(value.creator) ||
    (value.created_at !== undefined && typeof value.created_at !== "string") ||
    (value.approved_at !== undefined && typeof value.approved_at !== "string")
  ) return null;
  return {
    checkpointId: value.checkpoint_id,
    topicId: value.topic_id,
    status: value.status,
    summary: value.summary,
    sourceDigest: value.source_digest,
    sourceStartAnchor: value.source_start_anchor,
    sourceEndAnchor: value.source_end_anchor,
    sourceEntryCount: Number(value.source_entry_count),
    beforeUtf8Bytes: Number(value.before_utf8_bytes),
    afterUtf8Bytes: Number(value.after_utf8_bytes),
    creator: { ...value.creator },
    createdAt:
      typeof value.created_at === "string" ? value.created_at : undefined,
    approvedAt:
      typeof value.approved_at === "string" ? value.approved_at : undefined,
  };
}

export function parseLivePrompt(value: unknown): LivePromptMessage | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !value.id ||
    typeof value.text !== "string" ||
    !isPositiveInteger(value.cycle) ||
    (value.created_at !== undefined && typeof value.created_at !== "string")
  ) {
    return null;
  }
  return {
    id: value.id,
    text: value.text,
    cycle: Number(value.cycle),
    created_at: typeof value.created_at === "string" ? value.created_at : undefined,
  };
}

export function parseTopicDetail(value: unknown): TopicDetail | null {
  if (
    !isRecord(value) ||
    !isPositiveInteger(value.rounds) ||
    !Array.isArray(value.participants) ||
    !Array.isArray(value.prompts) ||
    !Array.isArray(value.messages)
  ) {
    return null;
  }
  const summary = parseTopicSummary(value.summary);
  const participants = value.participants.map(parseTopicParticipant);
  const prompts = value.prompts.map(parseLivePrompt);
  const messages = value.messages.map(parseConversationMessage);
  const contextCheckpoints = Array.isArray(value.context_checkpoints)
    ? value.context_checkpoints.map(parseTopicContextCheckpoint)
    : [];
  if (
    !summary ||
    participants.some((participant) => participant === null) ||
    prompts.some((prompt) => prompt === null) ||
    messages.some((message) => message === null) ||
    contextCheckpoints.some((checkpoint) => checkpoint === null) ||
    (value.active_context_checkpoint_id !== undefined &&
      value.active_context_checkpoint_id !== null &&
      typeof value.active_context_checkpoint_id !== "string")
  ) {
    return null;
  }
  return {
    summary,
    rounds: Number(value.rounds),
    participants: participants.filter(
      (participant): participant is TopicParticipantInput => participant !== null,
    ),
    prompts: prompts.filter((prompt): prompt is LivePromptMessage => prompt !== null),
    messages: messages.filter(
      (message): message is ConversationMessage => message !== null,
    ),
    contextCheckpoints: contextCheckpoints.filter(
      (checkpoint): checkpoint is TopicContextCheckpoint => checkpoint !== null,
    ),
    activeContextCheckpointId:
      typeof value.active_context_checkpoint_id === "string"
        ? value.active_context_checkpoint_id
        : null,
  };
}

export function parseParticipantActivity(
  value: unknown,
): ParticipantActivity | null {
  if (
    !isRecord(value) ||
    typeof value.run_id !== "string" ||
    typeof value.participant_id !== "string" ||
    !isRuntimeId(value.runtime_id) ||
    !isActivityStage(value.stage) ||
    !isActivityStatus(value.status) ||
    !isPositiveInteger(value.round) ||
    !isPositiveInteger(value.cycle)
  ) {
    return null;
  }
  const nativeSummary =
    value.trusted === true && typeof value.native_summary === "string"
      ? value.native_summary.trim()
      : "";
  return {
    run_id: value.run_id,
    participant_id: value.participant_id,
    runtime_id: value.runtime_id,
    stage: value.stage,
    status: value.status,
    round: Number(value.round),
    cycle: Number(value.cycle),
    native_summary: nativeSummary || undefined,
  };
}

export function parsePausedAuditFailure(
  value: unknown,
): PausedAuditFailure | null {
  if (
    !isRecord(value) ||
    typeof value.run_id !== "string" ||
    typeof value.failure_id !== "string" ||
    !isPositiveInteger(value.round) ||
    !isPositiveInteger(value.cycle) ||
    !Array.isArray(value.failed)
  ) {
    return null;
  }
  const failed = value.failed.map((item) => {
    if (
      !isRecord(item) ||
      typeof item.participant_id !== "string" ||
      !isRuntimeId(item.runtime_id) ||
      typeof item.message !== "string"
    ) {
      return null;
    }
    return {
      participant_id: item.participant_id,
      runtime_id: item.runtime_id,
      message: item.message,
    };
  });
  if (failed.length < 1 || failed.some((item) => item === null)) {
    return null;
  }
  return {
    run_id: value.run_id,
    failure_id: value.failure_id,
    round: Number(value.round),
    cycle: Number(value.cycle),
    failed: failed.filter((item): item is NonNullable<typeof item> => item !== null),
  };
}

export function parseEvidenceSummary(value: unknown): EvidenceSummary | null {
  if (
    !isRecord(value) ||
    value.schema_version !== 1 ||
    typeof value.run_id !== "string" ||
    !value.run_id ||
    typeof value.run_status !== "string" ||
    !isRecord(value.environment_gate) ||
    !Array.isArray(value.runtime_gates) ||
    !isRecord(value.rate_limits) ||
    !isRecord(value.governance) ||
    !isRecord(value.raw_capture) ||
    !isRecord(value.decision_chain) ||
    typeof value.event_log_readable !== "boolean"
  ) {
    return null;
  }

  const runtimeGates = value.runtime_gates.map(parseRuntimeGate);
  if (runtimeGates.some((gate) => gate === null)) {
    return null;
  }
  const rateLimits = parseRateLimits(value.rate_limits);
  const environmentGate = parseEnvironmentGate(value.environment_gate);
  const governance = parseGovernance(value.governance);
  const rawCapture = parseRawCapture(value.raw_capture);
  const decisionChain = parseDecisionChain(value.decision_chain);
  if (
    !environmentGate ||
    !rateLimits ||
    !governance ||
    !rawCapture ||
    !decisionChain ||
    governance.derived_from_verified_chain !== decisionChain.verified
  ) {
    return null;
  }
  return {
    schema_version: 1,
    run_id: value.run_id,
    run_status: value.run_status,
    environment_gate: environmentGate,
    runtime_gates: runtimeGates.filter(
      (gate): gate is RuntimeGateEvidence => gate !== null,
    ),
    rate_limits: rateLimits,
    governance,
    raw_capture: rawCapture,
    decision_chain: decisionChain,
    event_log_readable: value.event_log_readable,
  };
}

export function parseTopicEvidenceLoaded(
  value: unknown,
): TopicEvidenceLoaded | null {
  if (
    !isRecord(value) ||
    typeof value.topic_id !== "string" ||
    !value.topic_id
  ) {
    return null;
  }
  const summary = parseEvidenceSummary(value.summary);
  return summary ? { topicId: value.topic_id, summary } : null;
}

export function parseTopicEvidenceUnavailable(
  value: unknown,
): TopicEvidenceUnavailable | null {
  if (
    !isRecord(value) ||
    typeof value.topic_id !== "string" ||
    !value.topic_id ||
    typeof value.message !== "string" ||
    !value.message ||
    value.message.length > 256
  ) {
    return null;
  }
  return { topicId: value.topic_id, message: value.message };
}

export function stringField(
  payload: Record<string, unknown>,
  field: string,
): string | null {
  const value = payload[field];
  return typeof value === "string" && value ? value : null;
}

function isRuntimeId(value: unknown): value is RuntimeId {
  return isOpaqueId(value);
}

function isRoleId(value: unknown): value is RoleId {
  return value === "executor" || value === "auditor";
}

function isConversationStage(
  value: unknown,
): value is NonNullable<ConversationMessage["stage"]> {
  return (
    value === "answer" ||
    value === "proposal" ||
    value === "audit" ||
    value === "rebuttal" ||
    value === "synthesis"
  );
}

function isAuditVerdict(
  value: unknown,
): value is NonNullable<ConversationMessage["verdict"]> {
  return (
    value === "accept" ||
    value === "challenge" ||
    value === "insufficient-evidence"
  );
}

function parseEnvironmentGate(
  value: Record<string, unknown>,
): EvidenceSummary["environment_gate"] | null {
  if (
    typeof value.verified !== "boolean" ||
    (value.policy !== null && typeof value.policy !== "string") ||
    !Array.isArray(value.kept) ||
    !value.kept.every(
      (item): item is string => typeof item === "string" && Boolean(item),
    ) ||
    (value.dropped_count !== null &&
      !isNonnegativeInteger(value.dropped_count))
  ) {
    return null;
  }
  if (
    value.verified !==
    (value.policy === "allowlist" && value.dropped_count !== null)
  ) {
    return null;
  }
  return {
    verified: value.verified,
    policy: value.policy,
    kept: [...value.kept],
    dropped_count: value.dropped_count,
  };
}

function parseRuntimeGate(value: unknown): RuntimeGateEvidence | null {
  if (
    !isRecord(value) ||
    !isRuntimeId(value.runtime_id) ||
    typeof value.catalog_verified !== "boolean" ||
    typeof value.account_route !== "string" ||
    (value.runtime_version !== null &&
      typeof value.runtime_version !== "string") ||
    !isNonnegativeInteger(value.turn_revalidated_count) ||
    !Array.isArray(value.model_providers) ||
    !value.model_providers.every(
      (item): item is string => typeof item === "string" && Boolean(item),
    )
  ) {
    return null;
  }
  return {
    runtime_id: value.runtime_id,
    catalog_verified: value.catalog_verified,
    account_route: value.account_route,
    runtime_version: value.runtime_version,
    turn_revalidated_count: value.turn_revalidated_count,
    model_providers: [...value.model_providers],
  };
}

function parseRateLimits(value: Record<string, unknown>): RateLimitEvidence | null {
  if (
    !isNonnegativeInteger(value.observed_event_count) ||
    !isRecord(value.by_runtime) ||
    !isNonnegativeInteger(value.warning_count) ||
    !Array.isArray(value.warnings) ||
    !isNonnegativeInteger(value.capture_parse_failures)
  ) {
    return null;
  }
  const byRuntime: Partial<Record<RuntimeId, number>> = {};
  for (const [runtimeId, count] of Object.entries(value.by_runtime)) {
    if (!isRuntimeId(runtimeId) || !isNonnegativeInteger(count)) {
      return null;
    }
    byRuntime[runtimeId] = count;
  }
  const warnings: RateLimitEvidence["warnings"] = [];
  for (const item of value.warnings) {
    if (
      !isRecord(item) ||
      !isRuntimeId(item.runtime_id) ||
      typeof item.message !== "string"
    ) {
      return null;
    }
    warnings.push({
      runtime_id: item.runtime_id,
      message: item.message,
    });
  }
  if (warnings.length !== value.warning_count) {
    return null;
  }
  return {
    observed_event_count: value.observed_event_count,
    by_runtime: byRuntime,
    warning_count: value.warning_count,
    warnings,
    capture_parse_failures: value.capture_parse_failures,
  };
}

function parseGovernance(value: Record<string, unknown>): EvidenceSummary["governance"] | null {
  if (typeof value.derived_from_verified_chain !== "boolean") {
    return null;
  }
  let permissionDecisions: EvidenceSummary["governance"]["permission_decisions"];
  if (value.permission_decisions === null) {
    permissionDecisions = null;
  } else if (
    isRecord(value.permission_decisions) &&
    isNonnegativeInteger(value.permission_decisions.allow) &&
    isNonnegativeInteger(value.permission_decisions.deny) &&
    isNonnegativeInteger(value.permission_decisions.total) &&
    value.permission_decisions.total ===
      value.permission_decisions.allow + value.permission_decisions.deny
  ) {
    permissionDecisions = {
      allow: value.permission_decisions.allow,
      deny: value.permission_decisions.deny,
      total: value.permission_decisions.total,
    };
  } else {
    return null;
  }
  const auditCounts =
    value.audit_counts === null
      ? null
      : parseCountRecord(value.audit_counts);
  if (value.audit_counts !== null && !auditCounts) {
    return null;
  }
  if (
    value.derived_from_verified_chain !==
    (permissionDecisions !== null && auditCounts !== null)
  ) {
    return null;
  }
  return {
    derived_from_verified_chain: value.derived_from_verified_chain,
    permission_decisions: permissionDecisions,
    audit_counts: auditCounts,
  };
}

function parseRawCapture(value: Record<string, unknown>): EvidenceSummary["raw_capture"] | null {
  const categories = parseCountRecord(value.by_category);
  if (
    !isNonnegativeInteger(value.file_count) ||
    !isNonnegativeInteger(value.total_bytes) ||
    !isNonnegativeInteger(value.turns_with_capture) ||
    !categories ||
    value.contents_exposed !== false
  ) {
    return null;
  }
  return {
    file_count: value.file_count,
    total_bytes: value.total_bytes,
    turns_with_capture: value.turns_with_capture,
    by_category: categories,
    contents_exposed: false,
  };
}

function parseDecisionChain(value: Record<string, unknown>): EvidenceSummary["decision_chain"] | null {
  if (
    typeof value.verified !== "boolean" ||
    (value.record_count !== null &&
      !isNonnegativeInteger(value.record_count)) ||
    (value.head_sha256 !== null &&
      (typeof value.head_sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(value.head_sha256))) ||
    (value.error !== null && typeof value.error !== "string")
  ) {
    return null;
  }
  if (
    value.verified !== (value.record_count !== null) ||
    (value.verified && value.error !== null) ||
    (!value.verified && value.error === null)
  ) {
    return null;
  }
  return {
    verified: value.verified,
    record_count: value.record_count,
    head_sha256: value.head_sha256,
    error: value.error,
  };
}

function parseCountRecord(value: unknown): Record<string, number> | null {
  if (!isRecord(value)) {
    return null;
  }
  const parsed: Record<string, number> = {};
  for (const [key, count] of Object.entries(value)) {
    if (!key || !isNonnegativeInteger(count)) {
      return null;
    }
    parsed[key] = count;
  }
  return parsed;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 1;
}

function parseTopicParticipant(value: unknown): TopicParticipantInput | null {
  if (
    !isRecord(value) ||
    typeof value.participant_id !== "string" ||
    !value.participant_id ||
    !isRoleId(value.role) ||
    !isRuntimeId(value.runtime_id) ||
    !isNonnegativeInteger(value.order) ||
    !isRecord(value.requested) ||
    typeof value.requested.model !== "string" ||
    typeof value.requested.effort !== "string" ||
    typeof value.requested.service_tier !== "string"
  ) {
    return null;
  }
  const controls =
    value.requested.controls === undefined
      ? undefined
      : parseControlScalarRecord(value.requested.controls);
  if (value.requested.controls !== undefined && !controls) return null;
  let executionProfile: StartParticipant["requested"]["execution_profile"];
  if (value.requested.execution_profile !== undefined) {
    if (
      !isRecord(value.requested.execution_profile) ||
      !isOpaqueId(value.requested.execution_profile.profile_id)
    ) return null;
    const values = parseControlScalarRecord(value.requested.execution_profile.values);
    if (!values) return null;
    executionProfile = {
      profile_id: value.requested.execution_profile.profile_id,
      values,
    };
  }
  return {
    participant_id: value.participant_id,
    role: value.role,
    order: Number(value.order),
    runtime_id: value.runtime_id,
    requested: {
      model: value.requested.model,
      effort: value.requested.effort,
      service_tier: value.requested.service_tier,
      controls: controls ?? undefined,
      execution_profile: executionProfile,
    },
  };
}

function parseStructuredContentBlocks(
  value: unknown,
): StructuredContentBlock[] | null {
  if (value === undefined) {
    return [];
  }
  if (!Array.isArray(value)) {
    return null;
  }
  const parsed: StructuredContentBlock[] = [];
  for (const block of value) {
    if (!isRecord(block) || typeof block.type !== "string") {
      return null;
    }
    if (block.type === "markdown" && typeof block.text === "string") {
      parsed.push({ type: "markdown", text: block.text });
    } else if (block.type === "code" && typeof block.code === "string") {
      parsed.push({
        type: "code",
        code: block.code,
        language: typeof block.language === "string" ? block.language : undefined,
        title: typeof block.title === "string" ? block.title : undefined,
      });
    } else if (block.type === "diff" && typeof block.diff === "string") {
      parsed.push({
        type: "diff",
        diff: block.diff,
        title: typeof block.title === "string" ? block.title : undefined,
      });
    } else if (block.type === "math" && typeof block.text === "string") {
      parsed.push({
        type: "math",
        text: block.text,
        display: block.display !== false,
      });
    } else if (
      block.type === "diagram" &&
      typeof block.source === "string" &&
      typeof block.language === "string"
    ) {
      parsed.push({
        type: "diagram",
        source: block.source,
        language: block.language,
        title: typeof block.title === "string" ? block.title : undefined,
      });
    } else if (block.type === "tool" && typeof block.title === "string") {
      parsed.push({
        type: "tool",
        title: block.title,
        summary: typeof block.summary === "string" ? block.summary : undefined,
        status: typeof block.status === "string" ? block.status : undefined,
      });
    } else if (
      block.type === "citation" &&
      typeof block.label === "string" &&
      typeof block.url === "string" &&
      isSafeLink(block.url)
    ) {
      parsed.push({ type: "citation", label: block.label, url: block.url });
    } else if (block.type === "file" && typeof block.name === "string") {
      if (
        block.size !== undefined &&
        !isNonnegativeInteger(block.size)
      ) return null;
      if (block.asset_id !== undefined && !isSafeAssetId(block.asset_id)) return null;
      parsed.push({
        type: "file",
        name: block.name,
        mimeType: typeof block.mime_type === "string" ? block.mime_type : undefined,
        size: typeof block.size === "number" ? block.size : undefined,
        assetId: typeof block.asset_id === "string" ? block.asset_id : undefined,
      });
    } else if (
      (block.type === "image" || block.type === "audio" || block.type === "video") &&
      typeof block.label === "string"
    ) {
      if (block.asset_id !== undefined && !isSafeAssetId(block.asset_id)) return null;
      parsed.push({
        type: "media",
        mediaType: block.type,
        label: block.label,
        mimeType: typeof block.mime_type === "string" ? block.mime_type : undefined,
        assetId: typeof block.asset_id === "string" ? block.asset_id : undefined,
        alt: typeof block.alt === "string" ? block.alt : undefined,
      });
    } else if (
      block.type === "editor_reference" &&
      typeof block.label === "string" &&
      typeof block.path === "string"
    ) {
      if (
        (block.line !== undefined && !isPositiveInteger(block.line)) ||
        (block.column !== undefined && !isPositiveInteger(block.column))
      ) return null;
      parsed.push({
        type: "editor-reference",
        label: block.label,
        path: block.path,
        line: typeof block.line === "number" ? block.line : undefined,
        column: typeof block.column === "number" ? block.column : undefined,
      });
    } else if (block.type === "unknown") {
      const text = firstString(block, ["text", "summary", "title", "label"]);
      parsed.push({
        type: "unknown",
        sourceType: typeof block.provider_type === "string" ? safeTypeLabel(block.provider_type) : "unknown",
        label: typeof block.title === "string" ? block.title : "Unsupported provider content",
        text,
      });
    } else {
      const text = firstString(block, ["text", "summary", "title", "label", "code", "diff"]);
      parsed.push({
        type: "unknown",
        sourceType: safeTypeLabel(block.type),
        label: "Unsupported provider content",
        text,
      });
    }
  }
  return parsed;
}

function firstString(
  value: Record<string, unknown>,
  keys: string[],
): string | undefined {
  for (const key of keys) {
    if (typeof value[key] === "string") return value[key];
  }
  return undefined;
}

function safeTypeLabel(value: string): string {
  const clean = value.replace(/[^A-Za-z0-9._-]/g, "").slice(0, 64);
  return clean || "unknown";
}

function isSafeAssetId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= 256 &&
    /^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value)
  );
}

function isSafeLink(value: string): boolean {
  return safeHttpUrl(value) !== undefined;
}

function isActivityStage(value: unknown): value is ActivityStage {
  return value === "answer" || value === "proposal" || value === "audit" || value === "synthesis";
}

function isActivityStatus(value: unknown): value is ActivityStatus {
  return (
    value === "pending" ||
    value === "running" ||
    value === "completed" ||
    value === "failed" ||
    value === "paused"
  );
}

function parseProviderDescriptor(value: unknown): ProviderDescriptor | null {
  if (!isRecord(value) || value.schema_version !== 1 || !isPositiveInteger(value.descriptor_version)) {
    return null;
  }
  const display = value.display;
  const authentication = value.authentication;
  const versionEvidence = value.version_evidence;
  const defaults = value.default_selection;
  const connect = value.connect;
  if (
    !isRuntimeId(value.runtime_id) ||
    !isOpaqueId(value.vendor_id) ||
    !isOpaqueId(value.agent_system_id) ||
    !isOpaqueId(value.relay_provider_id) ||
    !isRecord(display) ||
    !nonemptyStrings(display, ["name", "short_name", "mark", "icon_token", "accent_token"]) ||
    !isEvidenceDeclaration(authentication) ||
    !isEvidenceDeclaration(versionEvidence) ||
    !isRecord(defaults) ||
    !nullableString(defaults.model) ||
    !nullableString(defaults.effort) ||
    !nullableString(defaults.service_tier) ||
    !isOpaqueId(defaults.execution_profile) ||
    !Array.isArray(value.control_schema) ||
    !Array.isArray(value.supported_content_types) ||
    !value.supported_content_types.every(isOpaqueId) ||
    !Array.isArray(value.execution_profiles) ||
    !Array.isArray(value.runtime_facilities) ||
    !Array.isArray(value.permission_presentations) ||
    !isRecord(connect) ||
    !nonemptyStrings(connect, ["label", "help_text", "action"])
  ) {
    return null;
  }
  const controls = value.control_schema.map(parseControlDefinition);
  const executionProfiles = value.execution_profiles.map(parseExecutionProfile);
  const facilities = value.runtime_facilities.map(parseRuntimeFacility);
  const permissionPresentations = value.permission_presentations.map(
    parsePermissionPresentation,
  );
  if (
    controls.some((item) => item === null) ||
    executionProfiles.some((item) => item === null) ||
    facilities.some((item) => item === null) ||
    permissionPresentations.some((item) => item === null)
  ) {
    return null;
  }
  if (new Set(controls.map((item) => item?.controlId)).size !== controls.length) {
    return null;
  }
  return {
    schemaVersion: 1,
    descriptorVersion: Number(value.descriptor_version),
    runtimeId: value.runtime_id,
    vendorId: value.vendor_id,
    agentSystemId: value.agent_system_id,
    relayProviderId: value.relay_provider_id,
    display: {
      name: String(display.name),
      shortName: String(display.short_name),
      mark: String(display.mark),
      iconToken: String(display.icon_token),
      accentToken: String(display.accent_token),
    },
    authentication: evidenceDeclaration(authentication),
    versionEvidence: evidenceDeclaration(versionEvidence),
    defaultSelection: {
      model: typeof defaults.model === "string" ? defaults.model : null,
      effort: typeof defaults.effort === "string" ? defaults.effort : null,
      serviceTier:
        typeof defaults.service_tier === "string"
          ? defaults.service_tier
          : null,
      executionProfile: defaults.execution_profile,
    },
    controlSchema: controls.filter(
      (item): item is NonNullable<typeof item> => item !== null,
    ),
    supportedContentTypes: [...value.supported_content_types],
    executionProfiles: executionProfiles.filter(
      (item): item is NonNullable<typeof item> => item !== null,
    ),
    runtimeFacilities: facilities.filter(
      (item): item is NonNullable<typeof item> => item !== null,
    ),
    permissionPresentations: permissionPresentations.filter(
      (item): item is NonNullable<typeof item> => item !== null,
    ),
    connect: {
      label: String(connect.label),
      helpText: String(connect.help_text),
      action: String(connect.action),
    },
  };
}

function parseControlDefinition(value: unknown): ProviderDescriptor["controlSchema"][number] | null {
  if (
    !isRecord(value) ||
    !isOpaqueId(value.control_id) ||
    typeof value.label !== "string" ||
    !value.label ||
    !isControlGroup(value.group) ||
    !isControlKind(value.kind) ||
    typeof value.description !== "string" ||
    typeof value.authority !== "string" ||
    !value.authority ||
    !isNullableControlScalar(value.default) ||
    !Array.isArray(value.options) ||
    !nullableNumber(value.min_value) ||
    !nullableNumber(value.max_value)
  ) {
    return null;
  }
  const options = value.options.map((option) => {
    if (
      !isRecord(option) ||
      !isControlScalar(option.value) ||
      typeof option.label !== "string" ||
      !option.label
    ) return null;
    const availability = parseAvailability(option.availability);
    return availability
      ? { value: option.value, label: option.label, availability }
      : null;
  });
  if (options.some((item) => item === null)) return null;
  return {
    controlId: value.control_id,
    label: value.label,
    group: value.group,
    kind: value.kind,
    description: value.description,
    authority: value.authority,
    defaultValue: value.default as ControlScalar | null,
    options: options.filter((item): item is NonNullable<typeof item> => item !== null),
    minValue: typeof value.min_value === "number" ? value.min_value : null,
    maxValue: typeof value.max_value === "number" ? value.max_value : null,
  };
}

function parseExecutionProfile(value: unknown): ProviderDescriptor["executionProfiles"][number] | null {
  if (
    !isRecord(value) ||
    !isOpaqueId(value.profile_id) ||
    typeof value.label !== "string" ||
    !value.label ||
    typeof value.description !== "string"
  ) {
    return null;
  }
  const availability = parseAvailability(value.availability);
  const values = parseControlScalarRecord(value.values);
  if (!availability || !values) return null;
  return {
    profileId: value.profile_id,
    label: value.label,
    description: value.description,
    availability,
    values,
  };
}

function parseRuntimeFacility(value: unknown): ProviderDescriptor["runtimeFacilities"][number] | null {
  if (
    !isRecord(value) ||
    !isOpaqueId(value.facility_id) ||
    !nonemptyStrings(value, ["label", "description", "observability", "management"])
  ) {
    return null;
  }
  return {
    facilityId: value.facility_id,
    label: String(value.label),
    description: String(value.description),
    observability: String(value.observability),
    management: String(value.management),
  };
}

function parsePermissionPresentation(value: unknown): ProviderDescriptor["permissionPresentations"][number] | null {
  if (
    !isRecord(value) ||
    !isSchemaToken(value.request_kind) ||
    !nonemptyStrings(value, ["title", "layout"]) ||
    !Array.isArray(value.fields)
  ) {
    return null;
  }
  const fields = value.fields.map((field) => {
    if (
      !isRecord(field) ||
      !isOpaqueId(field.field_id) ||
      !nonemptyStrings(field, ["label", "pointer", "format"])
    ) return null;
    return {
      fieldId: field.field_id,
      label: String(field.label),
      pointer: String(field.pointer),
      format: String(field.format),
    };
  });
  if (fields.some((field) => field === null)) return null;
  return {
    requestKind: value.request_kind,
    title: String(value.title),
    layout: String(value.layout),
    fields: fields.filter((field): field is NonNullable<typeof field> => field !== null),
  };
}

function parseAvailability(value: unknown) {
  if (!isRecord(value) || typeof value.available !== "boolean") return null;
  if (value.available) return { available: true } as const;
  return typeof value.reason === "string" && value.reason
    ? ({ available: false, reason: value.reason } as const)
    : null;
}

function parseControlScalarRecord(value: unknown): Record<string, ControlScalar> | null {
  if (!isRecord(value)) return null;
  const parsed: Record<string, ControlScalar> = {};
  for (const [key, item] of Object.entries(value)) {
    if (!isOpaqueId(key) || !isControlScalar(item)) return null;
    parsed[key] = item;
  }
  return parsed;
}

function isControlScalar(value: unknown): value is ControlScalar {
  return (
    typeof value === "string" ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isInteger(value))
  );
}

function isSchemaToken(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= 128 &&
    /^[A-Za-z][A-Za-z0-9_.:/-]*$/.test(value)
  );
}

function isNullableControlScalar(value: unknown): boolean {
  return value === null || isControlScalar(value);
}

function isControlGroup(value: unknown): value is ProviderDescriptor["controlSchema"][number]["group"] {
  return value === "model" || value === "turn" || value === "execution" || value === "runtime";
}

function isControlKind(value: unknown): value is ProviderDescriptor["controlSchema"][number]["kind"] {
  return value === "select" || value === "boolean" || value === "integer" || value === "status";
}

function nullableString(value: unknown): boolean {
  return value === null || (typeof value === "string" && Boolean(value));
}

function nullableNumber(value: unknown): boolean {
  return value === null || (typeof value === "number" && Number.isInteger(value));
}

function nonemptyStrings(value: Record<string, unknown>, keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === "string" && Boolean(value[key]));
}

function isEvidenceDeclaration(value: unknown): value is Record<string, unknown> {
  return isRecord(value) && nonemptyStrings(value, ["label", "authority", "not_observable_label"]);
}

function evidenceDeclaration(value: Record<string, unknown>) {
  return {
    label: String(value.label),
    authority: String(value.authority),
    notObservableLabel: String(value.not_observable_label),
  };
}

function parseModelCapability(value: unknown) {
  const option = parseCapabilityOption(value);
  if (
    !option ||
    !isRecord(value) ||
    typeof value.explicit_selectable !== "boolean" ||
    !Array.isArray(value.efforts) ||
    !Array.isArray(value.service_tiers)
  ) {
    return null;
  }
  const efforts = value.efforts.map(parseCapabilityOption);
  const serviceTiers = value.service_tiers.map(parseCapabilityOption);
  if (
    efforts.some((effort) => effort === null) ||
    serviceTiers.some((tier) => tier === null)
  ) {
    return null;
  }
  return {
    ...option,
    description:
      typeof value.description === "string" && value.description
        ? value.description
        : undefined,
    explicitSelectable: value.explicit_selectable,
    efforts: efforts.filter((effort) => effort !== null),
    serviceTiers: serviceTiers.filter((tier) => tier !== null),
  };
}

function parseCapabilityOption(value: unknown): {
  id: string;
  label: string;
  availability:
    | { available: true }
    | { available: false; reason: string };
} | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.label !== "string" ||
    !isRecord(value.availability) ||
    typeof value.availability.available !== "boolean"
  ) {
    return null;
  }
  if (value.availability.available) {
    return {
      id: value.id,
      label: value.label,
      availability: { available: true },
    };
  }
  if (
    typeof value.availability.reason !== "string" ||
    !value.availability.reason
  ) {
    return null;
  }
  return {
    id: value.id,
    label: value.label,
    availability: {
      available: false,
      reason: value.availability.reason,
    },
  };
}

function parseEffectiveSettings(
  value: unknown,
): EffectiveSettings | null {
  if (value === undefined || value === null) {
    return null;
  }
  if (
    !isRecord(value) ||
    typeof value.model !== "string" ||
    (value.effort !== null &&
      value.effort !== undefined &&
      typeof value.effort !== "string") ||
    (value.service_tier !== null &&
      value.service_tier !== undefined &&
      typeof value.service_tier !== "string") ||
    typeof value.authority !== "string" ||
    !value.authority.trim()
  ) {
    return null;
  }
  let controls: EffectiveSettings["controls"];
  if (value.controls !== undefined) {
    if (!isRecord(value.controls)) return null;
    controls = {};
    for (const [controlId, entry] of Object.entries(value.controls)) {
      if (
        !isOpaqueId(controlId) ||
        !isRecord(entry) ||
        !isNullableControlScalar(entry.value) ||
        typeof entry.authority !== "string" ||
        !entry.authority ||
        typeof entry.observable !== "boolean"
      ) return null;
      controls[controlId] = {
        value: entry.value as ControlScalar | null,
        authority: entry.authority,
        observable: entry.observable,
      };
    }
  }
  let executionProfile: EffectiveSettings["executionProfile"];
  if (value.execution_profile !== undefined) {
    if (
      !isRecord(value.execution_profile) ||
      !isOpaqueId(value.execution_profile.profile_id) ||
      typeof value.execution_profile.authority !== "string" ||
      !value.execution_profile.authority
    ) return null;
    executionProfile = {
      profileId: value.execution_profile.profile_id,
      authority: value.execution_profile.authority,
    };
  }
  return {
    model: value.model,
    effort:
      typeof value.effort === "string" ? value.effort : null,
    serviceTier:
      typeof value.service_tier === "string"
        ? value.service_tier
        : null,
    authority: value.authority,
    controls,
    executionProfile,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}
