import { describe, expect, it } from "vitest";

import {
  classifyEvidenceResponse,
  isEvidenceForActiveTopic,
  type PendingEvidenceRead,
} from "./evidenceHistory";

describe("saved topic evidence correlation", () => {
  it("accepts only the exact active topic and rejects missing or stale responses", () => {
    expect(isEvidenceForActiveTopic("topic-b", "topic-b")).toBe(true);
    expect(isEvidenceForActiveTopic("topic-b", "topic-a")).toBe(false);
    expect(isEvidenceForActiveTopic("topic-b", null)).toBe(false);
    expect(isEvidenceForActiveTopic(null, "topic-b")).toBe(false);
  });

  it("defers an early event and rejects an older response for the same topic", () => {
    const pending: PendingEvidenceRead = { topicId: "topic-a", commandId: null };
    expect(classifyEvidenceResponse(pending, "new-command", "topic-a")).toBe("defer");
    pending.commandId = "new-command";
    expect(classifyEvidenceResponse(pending, "old-command", "topic-a")).toBe("ignore");
    expect(classifyEvidenceResponse(pending, "new-command", "topic-a")).toBe("accept");
  });

  it("correlates a protocol rejection without requiring a topic id", () => {
    const pending: PendingEvidenceRead = { topicId: "topic-a", commandId: null };
    expect(classifyEvidenceResponse(pending, "evidence-1", null, true)).toBe("defer");
    pending.commandId = "evidence-1";
    expect(classifyEvidenceResponse(pending, "other", null, true)).toBe("ignore");
    expect(classifyEvidenceResponse(pending, "evidence-1", null, true)).toBe("accept");
  });
});
