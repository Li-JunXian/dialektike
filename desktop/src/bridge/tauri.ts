import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

import {
  ORDINARY_EVENT_CHANNEL,
  PERMISSION_EVENT_CHANNEL,
  type EventEnvelope,
  type AuditFailureResolutionInput,
  type PermissionDecisionInput,
  type ProjectRegisterInput,
  type StartRunInput,
  type StopRunInput,
  type SupervisorStatus,
  type TopicCreateInput,
  type TopicCheckpointApproveInput,
  type TopicCheckpointDeactivateInput,
  type TopicCheckpointDraftInput,
  type TopicDeleteInput,
  type TopicEvidenceReadInput,
  type TopicListInput,
  type TopicProjectSetInput,
  type TopicReadInput,
  type TopicSearchInput,
  type TopicUpdateInput,
} from "../protocol/messages";
import type {
  AccessibilityDisplayState,
  AppearancePreference,
  EffectiveAppearance,
} from "../state/appearance";

interface AccessibilityDisplayStateWire {
  increase_contrast: boolean;
  reduce_transparency: boolean;
  differentiate_without_color: boolean;
  reduce_motion: boolean;
}

const PREVIEW_MESSAGE =
  "Browser preview only — open the native Dialektikḗ app to connect runtimes.";

export function isNativeDesktopRuntime(
  scope: unknown = globalThis,
): boolean {
  return (
    (typeof scope === "object" || typeof scope === "function") &&
    scope !== null &&
    "__TAURI_INTERNALS__" in scope
  );
}

function requireNativeDesktopRuntime(): void {
  if (!isNativeDesktopRuntime()) {
    throw new Error(PREVIEW_MESSAGE);
  }
}

export async function listenForOrdinaryEvents(
  listener: (event: EventEnvelope) => void,
): Promise<UnlistenFn> {
  requireNativeDesktopRuntime();
  return listen<EventEnvelope>(ORDINARY_EVENT_CHANNEL, (event) => {
    listener(event.payload);
  });
}

export async function listenForPermissionEvents(
  listener: (event: EventEnvelope) => void,
): Promise<UnlistenFn> {
  requireNativeDesktopRuntime();
  return listen<EventEnvelope>(PERMISSION_EVENT_CHANNEL, (event) => {
    listener(event.payload);
  });
}

export function initializeSidecar(): Promise<SupervisorStatus> {
  requireNativeDesktopRuntime();
  return invoke<SupervisorStatus>("sidecar_initialize");
}

export async function getAccessibilityDisplayState(): Promise<AccessibilityDisplayState> {
  requireNativeDesktopRuntime();
  const value = await invoke<AccessibilityDisplayStateWire>("accessibility_display_state");
  return {
    increaseContrast: value.increase_contrast,
    reduceTransparency: value.reduce_transparency,
    differentiateWithoutColor: value.differentiate_without_color,
    reduceMotion: value.reduce_motion,
  };
}

export async function getWindowAppearance(): Promise<EffectiveAppearance> {
  requireNativeDesktopRuntime();
  return (await getCurrentWindow().theme()) ?? "light";
}

export async function setWindowAppearance(preference: AppearancePreference): Promise<void> {
  requireNativeDesktopRuntime();
  await getCurrentWindow().setTheme(preference === "system" ? null : preference);
}

export async function listenForWindowAppearance(
  listener: (appearance: EffectiveAppearance) => void,
): Promise<UnlistenFn> {
  requireNativeDesktopRuntime();
  return getCurrentWindow().onThemeChanged(({ payload }) => listener(payload));
}

export function discoverCapabilities(): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("capabilities_discover");
}

export function listProjects(): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("project_list");
}

export function registerProject(input: ProjectRegisterInput): Promise<string | null> {
  requireNativeDesktopRuntime();
  return invoke<string | null>("project_register", { input });
}

export function startRun(input: StartRunInput): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("run_start", { input });
}

export function stopRun(input: StopRunInput): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("run_stop", { input });
}

export function listTopics(input: TopicListInput = {}): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_list", { input });
}

export function searchTopics(input: TopicSearchInput): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_search", { input });
}

export function createTopic(input: TopicCreateInput): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_create", { input });
}

export function readTopic(input: TopicReadInput): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_read", { input });
}

export function readTopicEvidence(input: TopicEvidenceReadInput): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_evidence_read", { input });
}

export function updateTopic(input: TopicUpdateInput): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_update", { input });
}

/** Tombstones UI topic state; immutable governance evidence remains owner-only. */
export function deleteTopic(input: TopicDeleteInput): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_delete", { input });
}

export function setTopicProject(input: TopicProjectSetInput): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_project_set", { input });
}

export function draftTopicCheckpoint(
  input: TopicCheckpointDraftInput,
): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_checkpoint_draft", { input });
}

export function approveTopicCheckpoint(
  input: TopicCheckpointApproveInput,
): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_checkpoint_approve", { input });
}

export function deactivateTopicCheckpoint(
  input: TopicCheckpointDeactivateInput,
): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("topic_checkpoint_deactivate", { input });
}

export function resolveAuditFailure(
  input: AuditFailureResolutionInput,
): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("audit_failure_resolve", { input });
}

export function respondToPermission(
  input: PermissionDecisionInput,
): Promise<string> {
  requireNativeDesktopRuntime();
  return invoke<string>("permission_respond", { input });
}

export function supervisorStatus(): Promise<SupervisorStatus> {
  requireNativeDesktopRuntime();
  return invoke<SupervisorStatus>("sidecar_status");
}
