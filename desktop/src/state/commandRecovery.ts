import type {
  EventEnvelope,
  PermissionRequest,
  TopicSummary,
} from "../protocol/messages";

export type TopicMutationSuccessEvent = "topic.updated" | "topic.deleted";

export interface PendingTopicMutation {
  commandId: string | null;
  successEvent: TopicMutationSuccessEvent;
  rollback: () => void;
}

export type TopicMutationEventDisposition =
  | "unrelated"
  | "defer"
  | "succeeded"
  | "rejected";

export function classifyTopicMutationEvent(
  pending: Pick<PendingTopicMutation, "commandId" | "successEvent">,
  event: EventEnvelope,
): TopicMutationEventDisposition {
  if (
    !event.request_id ||
    (event.event !== pending.successEvent && event.event !== "protocol.error")
  ) {
    return "unrelated";
  }
  if (pending.commandId === null) return "defer";
  if (pending.commandId !== event.request_id) return "unrelated";
  return event.event === "protocol.error" ? "rejected" : "succeeded";
}

export function restoreUpdatedTopic(
  topics: TopicSummary[],
  topicId: string,
  previous: TopicSummary | undefined,
): TopicSummary[] {
  if (!previous) return topics;
  return topics.map((topic) => topic.id === topicId ? previous : topic);
}

export function restoreDeletedTopic(
  topics: TopicSummary[],
  removed: TopicSummary | undefined,
  removedIndex: number,
): TopicSummary[] {
  if (!removed || topics.some((topic) => topic.id === removed.id)) return topics;
  const restored = [...topics];
  restored.splice(Math.max(0, Math.min(removedIndex, restored.length)), 0, removed);
  return restored;
}

export function dismissPermissionRequest(
  queue: PermissionRequest[],
  permissionId: string,
): PermissionRequest[] {
  return queue.filter((permission) => permission.permission_id !== permissionId);
}
