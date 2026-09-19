import type { ConversationMessage } from "../protocol/messages";

interface ContextCheckpointEligibilityInput {
  activeTopic: boolean;
  archivedTopic: boolean;
  protocolReady: boolean;
  previewMode: boolean;
  runActive: boolean;
  checkpointBusy: boolean;
  topicBusy: boolean;
  messages: ConversationMessage[];
}

/** Returns the precise reason Live cannot create a new checkpoint draft. */
export function contextCheckpointUnavailableReason({
  activeTopic,
  archivedTopic,
  protocolReady,
  previewMode,
  runActive,
  checkpointBusy,
  topicBusy,
  messages,
}: ContextCheckpointEligibilityInput): string | null {
  if (!activeTopic) return "Create or select a topic before creating a context checkpoint.";
  if (archivedTopic) return "Unarchive this topic before creating a context checkpoint.";
  if (previewMode) return "Context checkpoints are available in the native Dialektikḗ app.";
  if (!protocolReady) return "The local governance core is offline. Retry it before creating a context checkpoint.";
  if (topicBusy) return "Wait for the topic change to finish before creating a context checkpoint.";
  if (checkpointBusy) return "A context checkpoint is already being prepared.";
  if (runActive) return "Wait for the active dialectic run to finish before creating a context checkpoint.";
  const hasCompletedAnswer = messages.some(
    (message) => (message.stage === "synthesis" || message.stage === "answer") && message.partial !== true,
  );
  if (!hasCompletedAnswer) {
    return "Available after a completed answer or Synthesis for this topic.";
  }
  return null;
}
