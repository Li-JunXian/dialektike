mod accessibility;
mod commands;
mod project_picker;
mod protocol;
mod supervisor;

use tauri::Manager;

use commands::{
    accessibility_display_state, audit_failure_resolve, capabilities_discover, permission_respond,
    project_list, project_register, run_start, run_stop, sidecar_initialize, sidecar_status,
    topic_checkpoint_approve, topic_checkpoint_deactivate, topic_checkpoint_draft, topic_create,
    topic_delete, topic_evidence_read, topic_list, topic_project_set, topic_read, topic_search,
    topic_update,
};
use supervisor::Supervisor;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(Supervisor::new())
        .invoke_handler(tauri::generate_handler![
            accessibility_display_state,
            sidecar_initialize,
            sidecar_status,
            capabilities_discover,
            project_list,
            project_register,
            topic_list,
            topic_search,
            topic_create,
            topic_read,
            topic_evidence_read,
            topic_update,
            topic_delete,
            topic_project_set,
            topic_checkpoint_draft,
            topic_checkpoint_approve,
            topic_checkpoint_deactivate,
            run_start,
            run_stop,
            permission_respond,
            audit_failure_resolve
        ])
        .build(tauri::generate_context!())
        .expect("failed to build the Dialektikḗ desktop application");

    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let supervisor = app_handle.state::<Supervisor>();
            let _ = supervisor.shutdown();
        }
    });
}
