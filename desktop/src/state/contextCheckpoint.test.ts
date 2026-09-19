import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../protocol/messages";
import { contextCheckpointUnavailableReason } from "./contextCheckpoint";

const completeSynthesis = {
  id: "message-synthesis",
  participant_id: "executor",
  role: "executor",
  runtime_id: "codex",
  stage: "synthesis",
  round: 1,
  cycle: 1,
  text: "Consolidated result",
  created_at: "2026-08-16T00:00:00Z",
} satisfies ConversationMessage;

function reason(overrides: Partial<Parameters<typeof contextCheckpointUnavailableReason>[0]> = {}) {
  return contextCheckpointUnavailableReason({
    activeTopic: true,
    archivedTopic: false,
    protocolReady: true,
    previewMode: false,
    runActive: false,
    checkpointBusy: false,
    topicBusy: false,
    messages: [completeSynthesis],
    ...overrides,
  });
}

describe("context checkpoint eligibility", () => {
  it("requires a completed, non-partial Executor synthesis", () => {
    expect(reason({ messages: [] })).toContain("completed answer or Synthesis");
    expect(reason({ messages: [{ ...completeSynthesis, partial: true }] })).toContain("completed answer or Synthesis");
    expect(reason()).toBeNull();
  });

  it("allows direct answers, including after a speaker swap, but excludes partial answers", () => {
    expect(reason({ messages: [{ ...completeSynthesis, stage: "answer", runtime_id: "claude-code" }] })).toBeNull();
    expect(reason({ messages: [{ ...completeSynthesis, stage: "answer", partial: true }] })).toContain("completed answer");
  });

  it("explains topic, archive, native-runtime, offline, and busy states precisely", () => {
    expect(reason({ activeTopic: false })).toContain("Create or select a topic");
    expect(reason({ archivedTopic: true })).toContain("Unarchive this topic");
    expect(reason({ previewMode: true })).toContain("native Dialektikḗ app");
    expect(reason({ protocolReady: false })).toContain("governance core is offline");
    expect(reason({ topicBusy: true })).toContain("Wait for the topic change to finish");
    expect(reason({ checkpointBusy: true })).toContain("already being prepared");
    expect(reason({ runActive: true })).toContain("active dialectic run");
  });
});
