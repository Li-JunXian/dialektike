import { describe, expect, it } from "vitest";
import { buildRunInput } from "./runIntent";
import { createDefaultParticipantConfiguration, validateParticipantSelection, validateRunConfiguration } from "./model";
import type { StartParticipant } from "../protocol/messages";

const seats: StartParticipant[] = [
  { participant_id: "speaker", role: "executor", order: 0, runtime_id: "codex", requested: { model: "chosen", effort: "high", service_tier: "native-default" } },
  { participant_id: "reviewer", role: "auditor", order: 0, runtime_id: "claude-code", requested: { model: "", effort: "", service_tier: "native-default", controls: { preserved: true } } },
];

describe("per-action chat contract", () => {
  it("sends only the selected speaker id while retaining every seat setting", () => {
    const chat = buildRunInput("topic", "Hello", 2, seats);
    expect(chat.mode).toBe("chat");
    expect(chat.speaker_id).toBe("speaker");
    expect(chat.participants).toEqual(seats);
    expect(chat.review_target).toBeUndefined();
  });
  it("uses opaque review ids without replacement text, then returns to chat", () => {
    const target = { cycle_id: "run-1", message_id: "run-1:1" };
    expect(buildRunInput("topic", "unsent draft", 1, seats, "review", target)).toEqual({ topic_id: "topic", prompt: "", rounds: 1, participants: seats, mode: "review", review_target: target });
    expect(buildRunInput("topic", "Next", 1, seats).mode).toBe("chat");
    expect(buildRunInput("topic", "Legacy proposal", 1, seats, "review").prompt).toBe("Legacy proposal");
  });
  it("speaker validation does not collect dormant reviewer issues", () => {
    const configuration = createDefaultParticipantConfiguration();
    const issues = validateParticipantSelection(configuration.executor, {});
    expect(issues).toHaveLength(1);
    expect(issues[0].message).toContain(configuration.executor.runtimeId);
    expect(validateRunConfiguration({ participants: configuration, rounds: 1 }, {})).toHaveLength(2);
  });
});
