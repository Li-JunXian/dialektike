import { describe, expect, it } from "vitest";

import type { EventEnvelope, PermissionRequest, TopicSummary } from "../protocol/messages";
import {
  classifyTopicMutationEvent,
  dismissPermissionRequest,
  restoreDeletedTopic,
  restoreUpdatedTopic,
} from "./commandRecovery";

const topic = (id: string, title: string): TopicSummary => ({
  id,
  title,
  pinned: false,
  archived: false,
  projectId: null,
});

const event = (eventName: string, requestId: string): EventEnvelope => ({
  protocol: "dialektike.sidecar.v1",
  event: eventName,
  request_id: requestId,
  payload: {},
});

describe("sidecar command recovery", () => {
  it("defers a raced topic result, then distinguishes success from sidecar rejection", () => {
    expect(classifyTopicMutationEvent(
      { commandId: null, successEvent: "topic.updated" },
      event("protocol.error", "desktop-7"),
    )).toBe("defer");
    expect(classifyTopicMutationEvent(
      { commandId: "desktop-7", successEvent: "topic.updated" },
      event("topic.updated", "desktop-7"),
    )).toBe("succeeded");
    expect(classifyTopicMutationEvent(
      { commandId: "desktop-7", successEvent: "topic.updated" },
      event("protocol.error", "desktop-7"),
    )).toBe("rejected");
    expect(classifyTopicMutationEvent(
      { commandId: "desktop-8", successEvent: "topic.updated" },
      event("protocol.error", "desktop-7"),
    )).toBe("unrelated");
  });

  it("restores optimistic update and delete snapshots without duplicating topics", () => {
    const original = topic("one", "Original");
    const second = topic("two", "Second");
    const optimistic = [{ ...original, title: "Optimistic" }, second];
    expect(restoreUpdatedTopic(optimistic, original.id, original)).toEqual([original, second]);
    expect(restoreDeletedTopic([second], original, 0)).toEqual([original, second]);
    expect(restoreDeletedTopic([original, second], original, 0)).toEqual([original, second]);
  });

  it("dismisses only the dead permission card after a fail-closed rejection", () => {
    const request = (permissionId: string): PermissionRequest => ({
      permission_id: permissionId,
      runtime_id: "synthetic",
      request_kind: "review",
      title: "Review",
      card: "verbatim",
      native_payload: {},
      annotations: {},
    });
    expect(dismissPermissionRequest([request("dead"), request("next")], "dead").map((item) => item.permission_id)).toEqual(["next"]);
  });
});
