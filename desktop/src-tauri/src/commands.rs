use serde_json::{json, to_value};
use tauri::{AppHandle, State};

use crate::{
    accessibility::{current_accessibility_display_state, AccessibilityDisplayState},
    project_picker::pick_project_directory,
    protocol::{
        AuditFailureResolutionInput, PermissionDecisionInput, ProjectRegisterInput, StartRunInput,
        StopRunInput, TopicCheckpointInput, TopicCreateInput, TopicIdInput, TopicListInput,
        TopicProjectSetInput, TopicSearchInput, TopicUpdateInput,
    },
    supervisor::{Supervisor, SupervisorStatus},
};

#[tauri::command]
pub fn project_list(supervisor: State<'_, Supervisor>) -> Result<String, String> {
    supervisor.send_command("project.list", json!({}))
}

#[tauri::command]
pub fn project_register(
    input: ProjectRegisterInput,
    supervisor: State<'_, Supervisor>,
) -> Result<Option<String>, String> {
    input.validate()?;
    let Some(path) = pick_project_directory()? else {
        return Ok(None);
    };
    supervisor
        .send_command(
            "project.register",
            json!({
                "path": path,
                "name": input.name,
                "acknowledgement": input.acknowledgement,
            }),
        )
        .map(Some)
}

#[tauri::command]
pub fn accessibility_display_state() -> AccessibilityDisplayState {
    current_accessibility_display_state()
}

#[tauri::command]
pub fn sidecar_initialize(
    app: AppHandle,
    supervisor: State<'_, Supervisor>,
) -> Result<SupervisorStatus, String> {
    supervisor.ensure_initialized(&app)
}

#[tauri::command]
pub fn sidecar_status(supervisor: State<'_, Supervisor>) -> Result<SupervisorStatus, String> {
    supervisor.status()
}

#[tauri::command]
pub fn capabilities_discover(supervisor: State<'_, Supervisor>) -> Result<String, String> {
    supervisor.send_command("capabilities.discover", json!({}))
}

#[tauri::command]
pub fn topic_list(
    input: TopicListInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    supervisor.send_command(
        "topic.list",
        to_value(input).map_err(|error| format!("failed to encode topic query: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_search(
    input: TopicSearchInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.search",
        to_value(input).map_err(|error| format!("failed to encode topic search: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_create(
    input: TopicCreateInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.create",
        to_value(input).map_err(|error| format!("failed to encode topic request: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_read(
    input: TopicIdInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.read",
        to_value(input).map_err(|error| format!("failed to encode topic request: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_evidence_read(
    input: TopicIdInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.evidence.read",
        to_value(input).map_err(|error| format!("failed to encode evidence request: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_update(
    input: TopicUpdateInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.update",
        to_value(input).map_err(|error| format!("failed to encode topic update: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_delete(
    input: TopicIdInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.delete",
        to_value(input).map_err(|error| format!("failed to encode topic request: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_project_set(
    input: TopicProjectSetInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.project.set",
        to_value(input).map_err(|error| format!("failed to encode project link: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_checkpoint_draft(
    input: TopicIdInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.checkpoint.draft",
        to_value(input).map_err(|error| format!("failed to encode checkpoint request: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_checkpoint_approve(
    input: TopicCheckpointInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.checkpoint.approve",
        to_value(input)
            .map_err(|error| format!("failed to encode checkpoint approval: {error}"))?,
    )
}

#[tauri::command]
pub fn topic_checkpoint_deactivate(
    input: TopicIdInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "topic.checkpoint.deactivate",
        to_value(input)
            .map_err(|error| format!("failed to encode checkpoint deactivation: {error}"))?,
    )
}

#[tauri::command]
pub fn run_start(
    input: StartRunInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "run.start",
        to_value(input).map_err(|error| format!("failed to encode run request: {error}"))?,
    )
}

#[tauri::command]
pub fn run_stop(input: StopRunInput, supervisor: State<'_, Supervisor>) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "run.stop",
        to_value(input).map_err(|error| format!("failed to encode stop request: {error}"))?,
    )
}

#[tauri::command]
pub fn permission_respond(
    input: PermissionDecisionInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "permission.respond",
        to_value(input)
            .map_err(|error| format!("failed to encode permission decision: {error}"))?,
    )
}

#[tauri::command]
pub fn audit_failure_resolve(
    input: AuditFailureResolutionInput,
    supervisor: State<'_, Supervisor>,
) -> Result<String, String> {
    input.validate()?;
    supervisor.send_command(
        "audit.failure.resolve",
        to_value(input).map_err(|error| format!("failed to encode audit resolution: {error}"))?,
    )
}
