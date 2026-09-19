/** Historical evidence responses may update only the topic that requested them. */
export function isEvidenceForActiveTopic(
  activeTopicId: string | null,
  eventTopicId: string | null,
): boolean {
  return Boolean(activeTopicId && eventTopicId && activeTopicId === eventTopicId);
}

export interface PendingEvidenceRead {
  topicId: string;
  commandId: string | null;
}

export type EvidenceResponseDisposition = "defer" | "accept" | "ignore";

/** Correlates saved-evidence events across the invoke/event race. */
export function classifyEvidenceResponse(
  pending: PendingEvidenceRead | null,
  requestId: string | undefined,
  eventTopicId: string | null,
  protocolError = false,
): EvidenceResponseDisposition {
  if (!pending || !requestId) return "ignore";
  if (!protocolError && eventTopicId !== pending.topicId) return "ignore";
  if (pending.commandId === null) return "defer";
  return requestId === pending.commandId ? "accept" : "ignore";
}
