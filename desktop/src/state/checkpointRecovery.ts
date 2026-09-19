import type { EventEnvelope } from "../protocol/messages";

export type CheckpointCommandAction = "draft" | "approve" | "deactivate";

export interface PendingCheckpointCommand {
  action: CheckpointCommandAction;
  topicId: string;
  checkpointId?: string;
  commandId: string | null;
}

export type CheckpointEventDisposition =
  | "unrelated"
  | "defer"
  | "progress"
  | "completed"
  | "rejected";

const PROGRESS_EVENTS: Record<CheckpointCommandAction, string[]> = {
  draft: ["command.result", "topic.updated", "topic.checkpoint.started"],
  approve: ["topic.updated"],
  deactivate: ["topic.updated"],
};

const TERMINAL_EVENT: Record<CheckpointCommandAction, string[]> = {
  draft: ["topic.checkpoint.drafted", "topic.checkpoint.failed"],
  approve: ["topic.checkpoint.activated"],
  deactivate: ["topic.checkpoint.deactivated"],
};

export function isCheckpointLifecycleEvent(eventName: string): boolean {
  return eventName.startsWith("topic.checkpoint.");
}

/** A topic projection is safe and useful even while its command id is racing. */
export function shouldProcessDeferredCheckpointEvent(event: EventEnvelope): boolean {
  return event.event === "topic.updated";
}

/** Classifies only events that can belong to the current checkpoint command. */
export function classifyCheckpointEvent(
  pending: PendingCheckpointCommand | null,
  event: EventEnvelope,
): CheckpointEventDisposition {
  if (!pending || !event.request_id) return "unrelated";
  const relevant = event.event === "protocol.error" ||
    PROGRESS_EVENTS[pending.action].includes(event.event) ||
    TERMINAL_EVENT[pending.action].includes(event.event);
  if (!relevant) return "unrelated";
  if (pending.commandId === null) return "defer";
  if (pending.commandId !== event.request_id) return "unrelated";

  if (event.event === "protocol.error") return "rejected";
  if (TERMINAL_EVENT[pending.action].includes(event.event)) {
    const topicId = typeof event.payload.topic_id === "string"
      ? event.payload.topic_id
      : null;
    if (topicId !== null && topicId !== pending.topicId) return "unrelated";
    if (
      pending.action === "approve" &&
      pending.checkpointId &&
      typeof event.payload.checkpoint_id === "string" &&
      event.payload.checkpoint_id !== pending.checkpointId
    ) {
      return "unrelated";
    }
    return "completed";
  }
  return "progress";
}

interface BindCheckpointCommandOptions {
  pending: PendingCheckpointCommand;
  invoke: () => Promise<string>;
  isCurrent: () => boolean;
  drainEarly: (commandId: string) => EventEnvelope[];
  onEvent: (event: EventEnvelope) => void;
  onTransportFailure: (error: unknown) => void;
}

/**
 * Binds Tauri's returned command id to events that may already have arrived.
 * The pending operation remains live after command.result; only its matching
 * terminal lifecycle event (or rejection) may release the UI.
 */
export async function bindCheckpointCommand({
  pending,
  invoke,
  isCurrent,
  drainEarly,
  onEvent,
  onTransportFailure,
}: BindCheckpointCommandOptions): Promise<void> {
  let commandId: string;
  try {
    commandId = await invoke();
  } catch (error) {
    if (isCurrent()) onTransportFailure(error);
    return;
  }
  if (!isCurrent()) return;
  pending.commandId = commandId;
  for (const event of drainEarly(commandId)) {
    if (!isCurrent()) break;
    onEvent(event);
  }
}
