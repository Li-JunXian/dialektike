use serde::Serialize;

#[derive(Debug, Clone, Copy, Default, Serialize)]
#[serde(rename_all = "snake_case")]
pub struct AccessibilityDisplayState {
    pub increase_contrast: bool,
    pub reduce_transparency: bool,
    pub differentiate_without_color: bool,
    pub reduce_motion: bool,
}

#[cfg(target_os = "macos")]
pub fn current_accessibility_display_state() -> AccessibilityDisplayState {
    use objc2_app_kit::NSWorkspace;

    let workspace = NSWorkspace::sharedWorkspace();
    AccessibilityDisplayState {
        increase_contrast: workspace.accessibilityDisplayShouldIncreaseContrast(),
        reduce_transparency: workspace.accessibilityDisplayShouldReduceTransparency(),
        differentiate_without_color: workspace
            .accessibilityDisplayShouldDifferentiateWithoutColor(),
        reduce_motion: workspace.accessibilityDisplayShouldReduceMotion(),
    }
}

#[cfg(not(target_os = "macos"))]
pub fn current_accessibility_display_state() -> AccessibilityDisplayState {
    AccessibilityDisplayState::default()
}
