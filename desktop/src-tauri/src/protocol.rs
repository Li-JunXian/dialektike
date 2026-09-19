use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const PROTOCOL: &str = "dialektike.sidecar.v1";
pub const ORDINARY_EVENT_CHANNEL: &str = "dialektike:event";
pub const PERMISSION_EVENT_CHANNEL: &str = "dialektike:permission";
pub const MAX_JSONL_BYTES: usize = 1024 * 1024;
pub const MAX_REASSEMBLED_JSON_BYTES: usize = 64 * 1024 * 1024;
pub const MAX_JSONL_CHUNKS: usize = 512;
pub const TRANSPORT_CHUNK_EVENT: &str = "transport.chunk";
pub const PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT: &str =
    "Participants use this folder as their native working directory. Actions the native runtime auto-permits may modify it without a Dialektikḗ card; those actions remain audited.";

#[derive(Debug, Clone, Serialize)]
pub struct CommandEnvelope {
    pub protocol: &'static str,
    pub id: String,
    pub command: &'static str,
    pub payload: Value,
}

impl CommandEnvelope {
    pub fn new(id: String, command: &'static str, payload: Value) -> Self {
        Self {
            protocol: PROTOCOL,
            id,
            command,
            payload,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EventEnvelope {
    pub protocol: String,
    pub event: String,
    pub payload: Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
}

impl EventEnvelope {
    pub fn desktop(event: impl Into<String>, payload: Value) -> Self {
        Self {
            protocol: PROTOCOL.to_owned(),
            event: event.into(),
            payload,
            request_id: None,
        }
    }

    pub fn parse(line: &str) -> Result<Self, String> {
        if line.len() > MAX_JSONL_BYTES {
            return Err("sidecar JSONL record exceeds the 1 MiB limit".to_owned());
        }
        Self::parse_contents(line)
    }

    pub(crate) fn parse_reassembled(line: &str) -> Result<Self, String> {
        if line.len() > MAX_REASSEMBLED_JSON_BYTES {
            return Err("reassembled sidecar event exceeds the 64 MiB limit".to_owned());
        }
        Self::parse_contents(line)
    }

    fn parse_contents(line: &str) -> Result<Self, String> {
        let envelope: Self = serde_json::from_str(line)
            .map_err(|_| "sidecar stdout was not a valid event envelope".to_owned())?;
        if envelope.protocol != PROTOCOL {
            return Err("sidecar protocol version mismatch".to_owned());
        }
        if envelope.event.trim().is_empty() {
            return Err("sidecar event name is empty".to_owned());
        }
        if !envelope.payload.is_object() {
            return Err("sidecar event payload must be a JSON object".to_owned());
        }
        if envelope.event == "permission.request" {
            validate_permission_request(&envelope.payload)?;
        } else if envelope.event == "topic.evidence.loaded" {
            validate_topic_evidence_loaded(&envelope.payload)?;
        } else if envelope.event == "topic.evidence.unavailable" {
            validate_topic_evidence_unavailable(&envelope.payload)?;
        } else if envelope.event == "project.registered" {
            validate_project_registered(&envelope.payload)?;
        } else if envelope.event == "project.list.result" {
            validate_project_list(&envelope.payload)?;
        }
        Ok(envelope)
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectSummaryWire {
    id: String,
    name: String,
    available: bool,
    registered_at: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectRegisteredWire {
    project: ProjectSummaryWire,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectListWire {
    projects: Vec<ProjectSummaryWire>,
}

fn validate_project_summary(project: &ProjectSummaryWire) -> Result<(), String> {
    if !valid_local_id(&project.id)
        || project.name.is_empty()
        || project.name.len() > 512
        || project.registered_at.as_ref().is_some_and(String::is_empty)
    {
        return Err("project summary has an invalid shape".to_owned());
    }
    let _ = project.available;
    Ok(())
}

fn validate_project_registered(payload: &Value) -> Result<(), String> {
    let value: ProjectRegisteredWire = serde_json::from_value(payload.clone())
        .map_err(|_| "registered project has an invalid shape".to_owned())?;
    validate_project_summary(&value.project)
}

fn validate_project_list(payload: &Value) -> Result<(), String> {
    let value: ProjectListWire = serde_json::from_value(payload.clone())
        .map_err(|_| "project list has an invalid shape".to_owned())?;
    if value.projects.len() > 10_000 {
        return Err("project list is too large".to_owned());
    }
    value.projects.iter().try_for_each(validate_project_summary)
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TopicEvidenceLoaded {
    topic_id: String,
    summary: SavedEvidenceSummary,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TopicEvidenceUnavailable {
    topic_id: String,
    message: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedEvidenceSummary {
    schema_version: u32,
    run_id: String,
    run_status: String,
    environment_gate: SavedEnvironmentGate,
    runtime_gates: Vec<SavedRuntimeGate>,
    rate_limits: SavedRateLimits,
    governance: SavedGovernance,
    raw_capture: SavedRawCapture,
    decision_chain: SavedDecisionChain,
    event_log_readable: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedEnvironmentGate {
    verified: bool,
    policy: Option<String>,
    kept: Vec<String>,
    dropped_count: Option<u64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedRuntimeGate {
    runtime_id: String,
    catalog_verified: bool,
    account_route: String,
    runtime_version: Option<String>,
    turn_revalidated_count: u64,
    model_providers: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedRateLimits {
    observed_event_count: u64,
    by_runtime: HashMap<String, u64>,
    warning_count: u64,
    warnings: Vec<SavedRateWarning>,
    capture_parse_failures: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedRateWarning {
    runtime_id: String,
    message: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedGovernance {
    derived_from_verified_chain: bool,
    permission_decisions: Option<SavedPermissionCounts>,
    audit_counts: Option<HashMap<String, u64>>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedPermissionCounts {
    allow: u64,
    deny: u64,
    total: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedRawCapture {
    file_count: u64,
    total_bytes: u64,
    turns_with_capture: u64,
    by_category: HashMap<String, u64>,
    contents_exposed: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedDecisionChain {
    verified: bool,
    record_count: Option<u64>,
    head_sha256: Option<String>,
    error: Option<String>,
}

fn validate_topic_evidence_loaded(payload: &Value) -> Result<(), String> {
    let loaded: TopicEvidenceLoaded = serde_json::from_value(payload.clone())
        .map_err(|_| "saved topic evidence has an invalid shape".to_owned())?;
    validate_topic_evidence_id(&loaded.topic_id)?;
    let summary = loaded.summary;
    if summary.schema_version != 1
        || summary.run_id.trim().is_empty()
        || summary.run_id.len() > 120
        || !matches!(
            summary.run_status.as_str(),
            "created" | "running" | "paused" | "cancelling" | "cancelled" | "completed" | "failed"
        )
    {
        return Err("saved topic evidence has invalid run metadata".to_owned());
    }
    let environment = summary.environment_gate;
    if environment.kept.len() > 128
        || environment.verified
            != (environment.policy.as_deref() == Some("allowlist")
                && environment.dropped_count.is_some())
    {
        return Err("saved topic evidence has an invalid environment gate".to_owned());
    }
    if summary.runtime_gates.len() > 64
        || summary.runtime_gates.iter().any(|gate| {
            !valid_opaque_id(&gate.runtime_id)
                || gate.account_route.is_empty()
                || gate.model_providers.len() > 64
        })
    {
        return Err("saved topic evidence has invalid runtime gates".to_owned());
    }
    let rates = summary.rate_limits;
    let observed_sum = rates
        .by_runtime
        .values()
        .try_fold(0_u64, |total, count| total.checked_add(*count));
    if rates.warning_count != rates.warnings.len() as u64
        || observed_sum != Some(rates.observed_event_count)
        || rates
            .by_runtime
            .keys()
            .any(|runtime_id| !valid_opaque_id(runtime_id))
        || rates.warnings.len() > 256
        || rates
            .warnings
            .iter()
            .any(|warning| !valid_opaque_id(&warning.runtime_id) || warning.message.is_empty())
    {
        return Err("saved topic evidence has invalid rate-limit counts".to_owned());
    }
    let decision = summary.decision_chain;
    let governance = summary.governance;
    if decision.verified != governance.derived_from_verified_chain {
        return Err("saved topic evidence has inconsistent provenance".to_owned());
    }
    if decision.verified {
        let counts = governance
            .permission_decisions
            .ok_or_else(|| "saved topic evidence lacks permission counts".to_owned())?;
        if counts.allow.checked_add(counts.deny) != Some(counts.total)
            || governance.audit_counts.is_none()
            || decision.record_count.is_none()
            || decision.error.is_some()
            || decision.head_sha256.as_ref().is_some_and(|head| {
                head.len() != 64
                    || !head
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            })
            || (decision.record_count == Some(0)) != decision.head_sha256.is_none()
        {
            return Err("saved topic evidence has invalid verified governance".to_owned());
        }
    } else if governance.permission_decisions.is_some()
        || governance.audit_counts.is_some()
        || decision.record_count.is_some()
        || decision.head_sha256.is_some()
        || decision.error.as_deref().is_none_or(str::is_empty)
    {
        return Err("saved topic evidence exposes unverified governance".to_owned());
    }
    let raw = summary.raw_capture;
    if raw.contents_exposed || raw.by_category.len() > 256 {
        return Err("saved topic evidence exposes raw capture data".to_owned());
    }

    // Read otherwise-unused fields so compile-time drift remains visible while
    // their values stay inert. Python and TypeScript enforce the same schema.
    let _ = (
        environment.dropped_count,
        summary
            .runtime_gates
            .iter()
            .map(|gate| {
                (
                    gate.catalog_verified,
                    gate.runtime_version.as_deref(),
                    gate.turn_revalidated_count,
                )
            })
            .collect::<Vec<_>>(),
        rates.capture_parse_failures,
        summary.event_log_readable,
        raw.file_count,
        raw.total_bytes,
        raw.turns_with_capture,
    );
    Ok(())
}

fn validate_topic_evidence_unavailable(payload: &Value) -> Result<(), String> {
    let unavailable: TopicEvidenceUnavailable = serde_json::from_value(payload.clone())
        .map_err(|_| "unavailable topic evidence has an invalid shape".to_owned())?;
    validate_topic_evidence_id(&unavailable.topic_id)?;
    if unavailable.message.is_empty() || unavailable.message.len() > 256 {
        return Err("unavailable topic evidence has an invalid message".to_owned());
    }
    Ok(())
}

fn validate_topic_evidence_id(topic_id: &str) -> Result<(), String> {
    if topic_id.is_empty()
        || topic_id.len() > 80
        || !topic_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
    {
        return Err("topic evidence has an invalid topic id".to_owned());
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RoleId {
    Executor,
    Auditor,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RequestedSettings {
    pub model: String,
    pub effort: String,
    pub service_tier: String,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub controls: HashMap<String, ControlScalar>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub execution_profile: Option<ExecutionProfileInput>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ControlScalar {
    Text(String),
    Boolean(bool),
    Integer(i64),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionProfileInput {
    pub profile_id: String,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub values: HashMap<String, ControlScalar>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StartParticipant {
    pub participant_id: String,
    pub role: RoleId,
    pub order: u32,
    pub runtime_id: String,
    pub requested: RequestedSettings,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub enum RunMode {
    #[serde(rename = "chat")]
    Chat,
    #[serde(rename = "review")]
    Review,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewTarget {
    pub cycle_id: String,
    pub message_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StartRunInput {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mode: Option<RunMode>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub speaker_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub review_target: Option<ReviewTarget>,
    pub topic_id: String,
    pub prompt: String,
    pub rounds: u32,
    pub participants: Vec<StartParticipant>,
}

impl StartRunInput {
    pub fn validate(&self) -> Result<(), String> {
        if self.review_target.is_none() && self.prompt.trim().is_empty() {
            return Err("prompt must not be empty".to_owned());
        }
        if self.topic_id.trim().is_empty() {
            return Err("topic_id must not be empty".to_owned());
        }
        if self.rounds == 0 {
            return Err("rounds must be a positive integer".to_owned());
        }
        match self.mode {
            Some(RunMode::Chat) => {
                if self.review_target.is_some() {
                    return Err("chat cannot supply a review target".to_owned());
                }
                validate_participants(&self.participants, false, false)?;
                let speaker = self
                    .participants
                    .iter()
                    .find(|p| Some(&p.participant_id) == self.speaker_id.as_ref())
                    .ok_or_else(|| "chat requires a configured speaker_id".to_owned())?;
                if speaker.requested.model.trim().is_empty() {
                    return Err("speaker model must be explicit".to_owned());
                }
                Ok(())
            }
            _ => {
                if self.speaker_id.is_some() {
                    return Err("review cannot supply speaker_id".to_owned());
                }
                if let Some(target) = &self.review_target {
                    if !matches!(self.mode, Some(RunMode::Review))
                        || !valid_local_id(&target.cycle_id)
                        || !valid_review_message_id(&target.message_id, &target.cycle_id)
                    {
                        return Err(
                            "review target requires explicit review mode and opaque ids".to_owned()
                        );
                    }
                    if !self.prompt.is_empty() {
                        return Err(
                            "targeted review resolves its prompt from saved evidence".to_owned()
                        );
                    }
                }
                validate_participants(&self.participants, true, true)
            }
        }
    }
}

fn validate_participants(
    participants: &[StartParticipant],
    require_model: bool,
    require_auditor: bool,
) -> Result<(), String> {
    if require_auditor && participants.len() < 2 {
        return Err("one executor and at least one auditor are required".to_owned());
    }
    let executor_count = participants
        .iter()
        .filter(|participant| matches!(participant.role, RoleId::Executor))
        .count();
    let auditor_count = participants
        .iter()
        .filter(|participant| matches!(participant.role, RoleId::Auditor))
        .count();
    if executor_count != 1 || (require_auditor && auditor_count == 0) {
        return Err("exactly one executor and at least one auditor are required".to_owned());
    }
    let mut participant_ids = HashSet::new();
    let mut runtime_ids = HashSet::new();
    let mut auditor_orders = Vec::new();
    for participant in participants {
        if participant.participant_id.trim().is_empty()
            || !valid_opaque_id(&participant.runtime_id)
            || participant.requested.service_tier.trim().is_empty()
        {
            return Err(
                "participant identity, runtime, and service tier must be explicit".to_owned(),
            );
        }
        let model = participant.requested.model.as_str();
        let effort = participant.requested.effort.as_str();
        if (require_model && model.trim().is_empty())
            || (!model.is_empty() && model.trim().is_empty())
            || (!effort.is_empty() && effort.trim().is_empty())
        {
            return Err("participant model and effort selections are invalid".to_owned());
        }
        if !require_model && model.is_empty() && !effort.is_empty() && effort != "native-default" {
            return Err("a topic cannot select effort before its model".to_owned());
        }
        if participant
            .requested
            .controls
            .keys()
            .any(|key| !valid_opaque_id(key))
        {
            return Err("provider control ids must be valid opaque ids".to_owned());
        }
        if let Some(profile) = &participant.requested.execution_profile {
            if !valid_opaque_id(&profile.profile_id)
                || profile.values.keys().any(|key| !valid_opaque_id(key))
            {
                return Err("execution-profile and value ids must be valid opaque ids".to_owned());
            }
        }
        if !participant_ids.insert(participant.participant_id.as_str()) {
            return Err("participant_id values must be unique".to_owned());
        }
        if !runtime_ids.insert(participant.runtime_id.as_str()) {
            return Err("one runtime/vendor may occupy at most one seat in a topic".to_owned());
        }
        match participant.role {
            RoleId::Executor if participant.order != 0 => {
                return Err("the executor seat order must be zero".to_owned())
            }
            RoleId::Auditor => auditor_orders.push(participant.order),
            RoleId::Executor => {}
        }
    }
    auditor_orders.sort_unstable();
    if auditor_orders != (0..auditor_count as u32).collect::<Vec<_>>() {
        return Err("auditor seat order must be contiguous from zero".to_owned());
    }
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TopicListInput {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub archived: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TopicSearchInput {
    pub query: String,
    #[serde(default = "default_true")]
    pub include_archived: bool,
    #[serde(default = "default_search_limit")]
    pub limit: u32,
}

impl TopicSearchInput {
    pub fn validate(&self) -> Result<(), String> {
        if self.query.trim().is_empty() {
            return Err("search query must not be empty".to_owned());
        }
        if self.limit == 0 || self.limit > 500 {
            return Err("search limit must be between 1 and 500".to_owned());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TopicCreateInput {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub rounds: u32,
    pub participants: Vec<StartParticipant>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub project_id: Option<String>,
}

impl TopicCreateInput {
    pub fn validate(&self) -> Result<(), String> {
        if self
            .title
            .as_ref()
            .is_some_and(|title| title.trim().is_empty())
        {
            return Err("topic title must be omitted or non-empty".to_owned());
        }
        if self.rounds == 0 {
            return Err("rounds must be a positive integer".to_owned());
        }
        if self
            .project_id
            .as_ref()
            .is_some_and(|project_id| !valid_local_id(project_id))
        {
            return Err("project_id must be omitted or valid".to_owned());
        }
        validate_topic_participants(&self.participants)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TopicIdInput {
    pub topic_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TopicCheckpointInput {
    pub topic_id: String,
    pub checkpoint_id: String,
}

impl TopicCheckpointInput {
    pub fn validate(&self) -> Result<(), String> {
        TopicIdInput {
            topic_id: self.topic_id.clone(),
        }
        .validate()?;
        if self.checkpoint_id.trim().is_empty() {
            return Err("checkpoint_id must not be empty".to_owned());
        }
        Ok(())
    }
}

impl TopicIdInput {
    pub fn validate(&self) -> Result<(), String> {
        if self.topic_id.trim().is_empty() {
            return Err("topic_id must not be empty".to_owned());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TopicUpdateInput {
    pub topic_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pinned: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub archived: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rounds: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub participants: Option<Vec<StartParticipant>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectRegisterInput {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    pub acknowledgement: String,
}

impl ProjectRegisterInput {
    pub fn validate(&self) -> Result<(), String> {
        if self
            .name
            .as_ref()
            .is_some_and(|name| name.trim().is_empty())
        {
            return Err("project name must be omitted or non-empty".to_owned());
        }
        if self.acknowledgement != PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT {
            return Err("Live must acknowledge the project working-directory risk".to_owned());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TopicProjectSetInput {
    pub topic_id: String,
    pub project_id: Option<String>,
}

impl TopicProjectSetInput {
    pub fn validate(&self) -> Result<(), String> {
        if !valid_local_id(&self.topic_id) {
            return Err("topic_id must be valid".to_owned());
        }
        if self
            .project_id
            .as_ref()
            .is_some_and(|project_id| !valid_local_id(project_id))
        {
            return Err("project_id must be null or valid".to_owned());
        }
        Ok(())
    }
}

impl TopicUpdateInput {
    pub fn validate(&self) -> Result<(), String> {
        TopicIdInput {
            topic_id: self.topic_id.clone(),
        }
        .validate()?;
        if self
            .title
            .as_ref()
            .is_some_and(|title| title.trim().is_empty())
        {
            return Err("topic title must be omitted or non-empty".to_owned());
        }
        if let Some(participants) = &self.participants {
            validate_topic_participants(participants)?;
        }
        if self.rounds.is_some_and(|rounds| rounds == 0) {
            return Err("rounds must be a positive integer".to_owned());
        }
        Ok(())
    }
}

fn validate_topic_participants(participants: &[StartParticipant]) -> Result<(), String> {
    validate_participants(participants, false, false)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuditFailureResolution {
    RetryFailed,
    ContinueWithoutFailed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AuditFailureResolutionInput {
    pub run_id: String,
    pub failure_id: String,
    pub resolution: AuditFailureResolution,
}

impl AuditFailureResolutionInput {
    pub fn validate(&self) -> Result<(), String> {
        if self.run_id.trim().is_empty() || self.failure_id.trim().is_empty() {
            return Err("run_id and failure_id must not be empty".to_owned());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StopRunInput {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub run_id: Option<String>,
}

impl StopRunInput {
    pub fn validate(&self) -> Result<(), String> {
        if self
            .run_id
            .as_ref()
            .is_some_and(|run_id| run_id.trim().is_empty())
        {
            return Err("run_id must be omitted or non-empty".to_owned());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PermissionDecision {
    AllowOnce,
    Deny,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PermissionDecisionInput {
    pub permission_id: String,
    pub decision: PermissionDecision,
}

impl PermissionDecisionInput {
    pub fn validate(&self) -> Result<(), String> {
        if self.permission_id.trim().is_empty() {
            return Err("permission_id must not be empty".to_owned());
        }
        Ok(())
    }
}

fn validate_permission_request(payload: &Value) -> Result<(), String> {
    let object = payload
        .as_object()
        .ok_or_else(|| "permission payload must be an object".to_owned())?;
    let permission_id = object
        .get("permission_id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let runtime_id = object
        .get("runtime_id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let title = object
        .get("title")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let card = object
        .get("card")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if permission_id.is_empty() || title.is_empty() || card.is_empty() {
        return Err("permission event is missing its id, title, or verbatim card".to_owned());
    }
    if !valid_opaque_id(runtime_id) {
        return Err("permission event has an invalid runtime id".to_owned());
    }
    if !object.get("native_payload").is_some_and(Value::is_object) {
        return Err("permission event is missing its verbatim native payload".to_owned());
    }
    if !object.get("annotations").is_some_and(Value::is_object) {
        return Err("permission event is missing deterministic annotations".to_owned());
    }
    Ok(())
}

fn valid_opaque_id(value: &str) -> bool {
    if value.is_empty() || value.len() > 96 {
        return false;
    }
    let mut bytes = value.bytes();
    if !bytes.next().is_some_and(|byte| byte.is_ascii_lowercase()) {
        return false;
    }
    let mut after_separator = false;
    for byte in bytes {
        if byte == b'.' || byte == b'-' {
            if after_separator {
                return false;
            }
            after_separator = true;
        } else if byte.is_ascii_lowercase() || byte.is_ascii_digit() {
            after_separator = false;
        } else {
            return false;
        }
    }
    !after_separator
}

// Only review targets accept the persisted run-id:turn-id shape.
fn valid_review_message_id(value: &str, cycle_id: &str) -> bool {
    value.rsplit_once(':').is_some_and(|(run, turn)| {
        run == cycle_id
            && valid_local_id(run)
            && !turn.is_empty()
            && turn.len() <= 20
            && turn.bytes().all(|byte| byte.is_ascii_digit())
    })
}

fn valid_local_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 80
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
}

fn default_true() -> bool {
    true
}

fn default_search_limit() -> u32 {
    100
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn rejects_wrong_protocol_and_malformed_permissions() {
        let wrong = json!({
            "protocol": "dialektike.sidecar.v2",
            "event": "sidecar.ready",
            "payload": {}
        });
        assert!(EventEnvelope::parse(&wrong.to_string()).is_err());

        let malformed_permission = json!({
            "protocol": PROTOCOL,
            "event": "permission.request",
            "payload": {
                "permission_id": "permission-1",
                "runtime_id": "codex",
                "title": "Run command"
            }
        });
        assert!(EventEnvelope::parse(&malformed_permission.to_string()).is_err());
    }

    #[test]
    fn accepts_a_verbatim_permission_envelope() {
        let message = json!({
            "protocol": PROTOCOL,
            "event": "permission.request",
            "request_id": "desktop-1",
            "payload": {
                "permission_id": "permission-1",
                "runtime_id": "claude-code",
                "title": "Write",
                "card": "full native card",
                "native_payload": {"tool_use_id": "raw-id", "path": "/tmp/example"},
                "annotations": {"path_confined": false}
            }
        });
        let parsed = EventEnvelope::parse(&message.to_string()).unwrap();
        assert_eq!(parsed.event, "permission.request");
    }

    #[test]
    fn project_events_never_admit_a_filesystem_path() {
        let safe = json!({
            "protocol": PROTOCOL,
            "event": "project.registered",
            "payload": {
                "project": {
                    "id": "project-1",
                    "name": "dialektike",
                    "available": true,
                    "registered_at": "2026-08-21T12:00:00Z"
                }
            }
        });
        assert!(EventEnvelope::parse(&safe.to_string()).is_ok());

        let leaked = json!({
            "protocol": PROTOCOL,
            "event": "project.list.result",
            "payload": {
                "projects": [{
                    "id": "project-1",
                    "name": "dialektike",
                    "available": true,
                    "registered_at": null,
                    "path": "/private/project"
                }]
            }
        });
        assert!(EventEnvelope::parse(&leaked.to_string()).is_err());
    }

    #[test]
    fn webview_project_registration_cannot_supply_a_path() {
        let forged = json!({
            "path": "/private/arbitrary",
            "acknowledgement": PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT
        });
        assert!(serde_json::from_value::<ProjectRegisterInput>(forged).is_err());

        let valid: ProjectRegisterInput = serde_json::from_value(json!({
            "name": "Focused work",
            "acknowledgement": PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT
        }))
        .unwrap();
        assert!(valid.validate().is_ok());
    }

    #[test]
    fn accepts_an_unanticipated_opaque_runtime_permission() {
        let message = json!({
            "protocol": PROTOCOL,
            "event": "permission.request",
            "payload": {
                "permission_id": "permission-synthetic-1",
                "runtime_id": "unexpected.runtime-7",
                "title": "Native approval",
                "card": "full synthetic native card",
                "native_payload": {"operation": "inspect fixture"},
                "annotations": {"provider_contract": "synthetic"}
            }
        });
        let parsed = EventEnvelope::parse(&message.to_string()).unwrap();
        assert_eq!(parsed.event, "permission.request");

        let invalid = json!({
            "protocol": PROTOCOL,
            "event": "permission.request",
            "payload": {
                "permission_id": "permission-synthetic-2",
                "runtime_id": "unexpected_runtime",
                "title": "Native approval",
                "card": "full synthetic native card",
                "native_payload": {"operation": "inspect fixture"},
                "annotations": {}
            }
        });
        assert!(EventEnvelope::parse(&invalid.to_string()).is_err());
    }

    #[test]
    fn validates_saved_topic_evidence_without_forwarding_unreviewed_fields() {
        let summary = json!({
            "schema_version": 1,
            "run_id": "run-1",
            "run_status": "completed",
            "environment_gate": {
                "verified": false,
                "policy": null,
                "kept": [],
                "dropped_count": null
            },
            "runtime_gates": [],
            "rate_limits": {
                "observed_event_count": 0,
                "by_runtime": {},
                "warning_count": 0,
                "warnings": [],
                "capture_parse_failures": 0
            },
            "governance": {
                "derived_from_verified_chain": false,
                "permission_decisions": null,
                "audit_counts": null
            },
            "raw_capture": {
                "file_count": 0,
                "total_bytes": 0,
                "turns_with_capture": 0,
                "by_category": {},
                "contents_exposed": false
            },
            "decision_chain": {
                "verified": false,
                "record_count": null,
                "head_sha256": null,
                "error": "Decision chain failed verification."
            },
            "event_log_readable": true
        });
        let valid = json!({
            "protocol": PROTOCOL,
            "event": "topic.evidence.loaded",
            "request_id": "evidence-1",
            "payload": {"topic_id": "topic-1", "summary": summary}
        });
        assert!(EventEnvelope::parse(&valid.to_string()).is_ok());

        let mut exposed = valid;
        exposed["payload"]["summary"]["raw_capture"]["path"] =
            json!("/private/owner/evidence.json");
        assert!(EventEnvelope::parse(&exposed.to_string()).is_err());

        let unavailable = json!({
            "protocol": PROTOCOL,
            "event": "topic.evidence.unavailable",
            "payload": {
                "topic_id": "topic-1",
                "message": "No saved governance evidence is available for this topic."
            }
        });
        assert!(EventEnvelope::parse(&unavailable.to_string()).is_ok());
    }

    #[test]
    fn validates_one_executor_and_many_distinct_auditors() {
        let input = StartRunInput {
            mode: None,
            speaker_id: None,
            review_target: None,
            topic_id: "topic-1".to_owned(),
            prompt: "Cross-examine this.".to_owned(),
            rounds: 2,
            participants: vec![
                participant("executor", RoleId::Executor, 0, "codex"),
                participant("auditor-1", RoleId::Auditor, 0, "claude-code"),
                participant("auditor-2", RoleId::Auditor, 1, "future-vendor"),
            ],
        };
        assert!(input.validate().is_ok());

        let duplicate = StartRunInput {
            mode: None,
            speaker_id: None,
            review_target: None,
            topic_id: input.topic_id.clone(),
            prompt: input.prompt.clone(),
            rounds: 2,
            participants: vec![
                participant("executor-1", RoleId::Executor, 0, "codex"),
                participant("executor-2", RoleId::Executor, 0, "claude-code"),
            ],
        };
        assert!(duplicate.validate().is_err());
    }

    #[test]
    fn topics_may_store_unconfigured_seats_while_runs_require_a_model() {
        let mut executor = participant("executor", RoleId::Executor, 0, "codex");
        let mut auditor = participant("auditor", RoleId::Auditor, 0, "claude-code");
        executor.requested.model.clear();
        executor.requested.effort.clear();
        auditor.requested.model.clear();
        auditor.requested.effort.clear();

        let topic = TopicCreateInput {
            title: None,
            rounds: 1,
            participants: vec![executor.clone(), auditor.clone()],
            project_id: None,
        };
        assert!(topic.validate().is_ok());

        let update = TopicUpdateInput {
            topic_id: "topic-unconfigured".to_owned(),
            title: None,
            pinned: None,
            archived: None,
            rounds: None,
            participants: Some(vec![executor.clone(), auditor.clone()]),
        };
        assert!(update.validate().is_ok());

        let run = StartRunInput {
            mode: None,
            speaker_id: None,
            review_target: None,
            topic_id: "topic-unconfigured".to_owned(),
            prompt: "Must not run yet".to_owned(),
            rounds: 1,
            participants: vec![executor, auditor],
        };
        assert!(run
            .validate()
            .is_err_and(|error| error.contains("model and effort selections")));
    }

    #[test]
    fn native_boundary_defers_model_specific_effort_requirement_to_the_sidecar() {
        let mut executor = participant("executor", RoleId::Executor, 0, "codex");
        let mut auditor = participant("auditor", RoleId::Auditor, 0, "claude-code");
        executor.requested.effort.clear();
        auditor.requested.effort.clear();

        let run = StartRunInput {
            mode: None,
            speaker_id: None,
            review_target: None,
            topic_id: "topic-effortless".to_owned(),
            prompt: "Use models whose catalogs advertise no effort selector".to_owned(),
            rounds: 1,
            participants: vec![executor.clone(), auditor.clone()],
        };
        assert!(run.validate().is_ok());

        executor.requested.model.clear();
        executor.requested.effort = "high".to_owned();
        let topic = TopicCreateInput {
            title: None,
            rounds: 1,
            participants: vec![executor.clone(), auditor.clone()],
            project_id: None,
        };
        assert!(topic
            .validate()
            .is_err_and(|error| error.contains("before its model")));

        executor.requested.effort = "native-default".to_owned();
        let legacy_topic = TopicCreateInput {
            title: None,
            rounds: 1,
            participants: vec![executor, auditor],
            project_id: None,
        };
        assert!(legacy_topic.validate().is_ok());
    }

    #[test]
    fn validates_synthetic_runtime_controls_without_provider_enumeration() {
        let mut executor = participant(
            "synthetic-executor",
            RoleId::Executor,
            0,
            "unexpected.runtime-7",
        );
        executor.requested.controls.insert(
            "response-style".to_owned(),
            ControlScalar::Text("lucid".to_owned()),
        );
        executor.requested.execution_profile = Some(ExecutionProfileInput {
            profile_id: "governed".to_owned(),
            values: HashMap::from([("network-access".to_owned(), ControlScalar::Boolean(false))]),
        });
        let auditor = participant(
            "synthetic-auditor",
            RoleId::Auditor,
            0,
            "alternate.runtime-8",
        );
        let valid = StartRunInput {
            mode: None,
            speaker_id: None,
            review_target: None,
            topic_id: "topic-synthetic".to_owned(),
            prompt: "Cross-examine this synthetic fixture.".to_owned(),
            rounds: 1,
            participants: vec![executor.clone(), auditor.clone()],
        };
        assert!(valid.validate().is_ok());

        let duplicate_runtime = StartRunInput {
            mode: None,
            speaker_id: None,
            review_target: None,
            topic_id: valid.topic_id.clone(),
            prompt: valid.prompt.clone(),
            rounds: 1,
            participants: vec![
                executor.clone(),
                participant(
                    "duplicate-runtime-auditor",
                    RoleId::Auditor,
                    0,
                    "unexpected.runtime-7",
                ),
            ],
        };
        assert!(duplicate_runtime
            .validate()
            .is_err_and(|error| error.contains("one runtime/vendor")));

        let mut invalid_control = executor;
        invalid_control.requested.controls.clear();
        invalid_control.requested.controls.insert(
            "response_style".to_owned(),
            ControlScalar::Text("lucid".to_owned()),
        );
        let invalid = StartRunInput {
            mode: None,
            speaker_id: None,
            review_target: None,
            topic_id: valid.topic_id,
            prompt: valid.prompt,
            rounds: 1,
            participants: vec![invalid_control, auditor],
        };
        assert!(invalid
            .validate()
            .is_err_and(|error| error.contains("control ids")));
    }

    #[test]
    fn chat_preserves_dormant_seats_and_requires_only_selected_model() {
        let mut reviewer = participant("auditor", RoleId::Auditor, 0, "claude-code");
        reviewer.requested.model.clear();
        reviewer.requested.effort.clear();
        let mut input = StartRunInput {
            mode: Some(RunMode::Chat),
            speaker_id: Some("executor".into()),
            review_target: None,
            topic_id: "topic-1".into(),
            prompt: "Hello".into(),
            rounds: 1,
            participants: vec![
                participant("executor", RoleId::Executor, 0, "codex"),
                reviewer,
            ],
        };
        assert!(input.validate().is_ok());
        assert_eq!(
            serde_json::to_value(&input).unwrap()["participants"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
        input.speaker_id = Some("auditor".into());
        assert!(input.validate().is_err());
        input.speaker_id = Some("missing".into());
        assert!(input.validate().is_err());
        input.speaker_id = Some("executor".into());
        input.participants.pop();
        assert!(input.validate().is_ok());
        assert!(validate_topic_participants(&input.participants).is_ok());
        input.mode = None;
        input.speaker_id = None;
        assert!(input.validate().is_err());
    }

    #[test]
    fn targeted_review_accepts_only_saved_ids_and_explicit_mode() {
        let mut input = StartRunInput {
            mode: Some(RunMode::Review),
            speaker_id: None,
            review_target: Some(ReviewTarget {
                cycle_id: "run-1".into(),
                message_id: "run-1:12".into(),
            }),
            topic_id: "topic-1".into(),
            prompt: String::new(),
            rounds: 1,
            participants: vec![
                participant("executor", RoleId::Executor, 0, "codex"),
                participant("auditor", RoleId::Auditor, 0, "claude-code"),
            ],
        };
        assert!(input.validate().is_ok());
        assert!(!valid_local_id("run-1:12"));
        for invalid in ["run-2:12", "run-1:../file", "run-1:", "run-1:12:3"] {
            input.review_target.as_mut().unwrap().message_id = invalid.into();
            assert!(input.validate().is_err());
        }
        input.review_target.as_mut().unwrap().message_id = "run-1:12".into();
        input.prompt = "model supplied replacement".into();
        assert!(input.validate().is_err());
        input.prompt.clear();
        input.mode = Some(RunMode::Chat);
        assert!(input.validate().is_err());
        input.mode = None;
        assert!(input.validate().is_err());
        let mut wire = serde_json::to_value(&input).unwrap();
        wire["mode"] = serde_json::json!("unknown");
        assert!(serde_json::from_value::<StartRunInput>(wire.clone()).is_err());
        wire["mode"] = serde_json::json!("review");
        wire["review_target"]["text"] = serde_json::json!("untrusted replacement");
        assert!(serde_json::from_value::<StartRunInput>(wire).is_err());
    }

    fn participant(
        participant_id: &str,
        role: RoleId,
        order: u32,
        runtime_id: &str,
    ) -> StartParticipant {
        StartParticipant {
            participant_id: participant_id.to_owned(),
            role,
            order,
            runtime_id: runtime_id.to_owned(),
            requested: RequestedSettings {
                model: "model".to_owned(),
                effort: "effort".to_owned(),
                service_tier: "native-default".to_owned(),
                controls: HashMap::new(),
                execution_profile: None,
            },
        }
    }
}
