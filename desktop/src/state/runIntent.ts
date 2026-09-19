import type { StartParticipant, StartRunInput } from "../protocol/messages";

/** Every ordinary invocation is chat; review is a per-action choice, never sticky. */
export function buildRunInput(
  topicId: string, prompt: string, rounds: number, participants: StartParticipant[],
  mode: "chat" | "review" = "chat", reviewTarget?: StartRunInput["review_target"],
): StartRunInput {
  return {
    topic_id: topicId, prompt: reviewTarget ? "" : prompt, rounds, participants, mode,
    ...(mode === "chat" ? { speaker_id: participants.find((seat) => seat.role === "executor")?.participant_id } : {}),
    ...(mode === "review" && reviewTarget ? { review_target: reviewTarget } : {}),
  };
}
