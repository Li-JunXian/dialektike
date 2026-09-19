import { describe, expect, it, vi } from "vitest";

import { SIDECAR_PROTOCOL, type EventEnvelope } from "../protocol/messages";
import {
  bindCheckpointCommand,
  classifyCheckpointEvent,
  shouldProcessDeferredCheckpointEvent,
  type PendingCheckpointCommand,
} from "./checkpointRecovery";

function event(name: string, requestId: string, payload: Record<string, unknown> = {}): EventEnvelope {
  return { protocol: SIDECAR_PROTOCOL, event: name, request_id: requestId, payload };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

describe("checkpoint command recovery", () => {
  it("keeps a draft pending through command.result, started, and topic.updated", () => {
    const pending: PendingCheckpointCommand = { action: "draft", topicId: "topic-1", commandId: "draft-1" };
    expect(classifyCheckpointEvent(pending, event("command.result", "draft-1"))).toBe("progress");
    expect(classifyCheckpointEvent(pending, event("topic.checkpoint.started", "draft-1", { topic_id: "topic-1" }))).toBe("progress");
    expect(classifyCheckpointEvent(pending, event("topic.updated", "draft-1"))).toBe("progress");
    expect(classifyCheckpointEvent(pending, event("topic.checkpoint.drafted", "draft-1", { topic_id: "topic-1" }))).toBe("completed");
    expect(classifyCheckpointEvent(pending, event("topic.checkpoint.failed", "draft-1", { topic_id: "topic-1" }))).toBe("completed");
  });

  it("lets an early topic projection update render while its correlation remains queued", () => {
    const pending: PendingCheckpointCommand = { action: "draft", topicId: "topic-1", commandId: null };
    const update = event("topic.updated", "draft-1", { topic: { summary: { id: "topic-1" } } });
    expect(classifyCheckpointEvent(pending, update)).toBe("defer");
    expect(shouldProcessDeferredCheckpointEvent(update)).toBe(true);
    expect(shouldProcessDeferredCheckpointEvent(event("topic.checkpoint.started", "draft-1"))).toBe(false);
  });

  it("uses action-specific terminals and ignores unrelated errors", () => {
    const approve: PendingCheckpointCommand = { action: "approve", topicId: "topic-1", checkpointId: "cp-1", commandId: "approve-1" };
    expect(classifyCheckpointEvent(approve, event("topic.checkpoint.drafted", "approve-1", { topic_id: "topic-1" }))).toBe("unrelated");
    expect(classifyCheckpointEvent(approve, event("topic.checkpoint.activated", "approve-1", { topic_id: "topic-1", checkpoint_id: "cp-1" }))).toBe("completed");
    expect(classifyCheckpointEvent(approve, event("protocol.error", "other"))).toBe("unrelated");
    expect(classifyCheckpointEvent(approve, event("protocol.error", "approve-1"))).toBe("rejected");

    const deactivate: PendingCheckpointCommand = { action: "deactivate", topicId: "topic-1", commandId: "off-1" };
    expect(classifyCheckpointEvent(deactivate, event("topic.checkpoint.activated", "off-1", { topic_id: "topic-1" }))).toBe("unrelated");
    expect(classifyCheckpointEvent(deactivate, event("topic.checkpoint.deactivated", "off-1", { topic_id: "topic-1" }))).toBe("completed");
  });

  it("replays an early request-correlated rejection only after invoke returns its id", async () => {
    const invoke = deferred<string>();
    const pending: PendingCheckpointCommand = { action: "draft", topicId: "topic-1", commandId: null };
    const rejection = event("protocol.error", "draft-1", { message: "Rejected safely" });
    expect(classifyCheckpointEvent(pending, rejection)).toBe("defer");
    const delivered: EventEnvelope[] = [];

    const binding = bindCheckpointCommand({
      pending,
      invoke: () => invoke.promise,
      isCurrent: () => true,
      drainEarly: (commandId) => commandId === "draft-1" ? [rejection] : [],
      onEvent: (value) => delivered.push(value),
      onTransportFailure: vi.fn(),
    });
    expect(delivered).toEqual([]);
    invoke.resolve("draft-1");
    await binding;
    expect(delivered).toEqual([rejection]);
    expect(classifyCheckpointEvent(pending, delivered[0])).toBe("rejected");
  });

  it("reports a transport failure only for the still-current checkpoint action", async () => {
    const pending: PendingCheckpointCommand = { action: "approve", topicId: "topic-1", commandId: null };
    const onTransportFailure = vi.fn();
    await bindCheckpointCommand({
      pending,
      invoke: async () => { throw new Error("transport closed"); },
      isCurrent: () => true,
      drainEarly: () => [],
      onEvent: vi.fn(),
      onTransportFailure,
    });
    expect(onTransportFailure).toHaveBeenCalledOnce();

    onTransportFailure.mockClear();
    await bindCheckpointCommand({
      pending,
      invoke: async () => { throw new Error("stale failure"); },
      isCurrent: () => false,
      drainEarly: () => [],
      onEvent: vi.fn(),
      onTransportFailure,
    });
    expect(onTransportFailure).not.toHaveBeenCalled();
  });
});
