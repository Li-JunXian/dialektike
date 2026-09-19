import { describe, expect, it, vi } from "vitest";

import { initializeGovernanceCore } from "./governanceStartup";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

describe("governance core startup boundary", () => {
  it("does not unlock persisted-topic loading before initialize acknowledges readiness", async () => {
    const pending = deferred<{ running: boolean; pid?: number }>();
    const listTopics = vi.fn();
    let staleError = "the Dialektikḗ sidecar is not running";

    const startup = initializeGovernanceCore({
      initialize: () => pending.promise,
      onReady: () => {
        staleError = "";
        listTopics();
      },
    });

    await Promise.resolve();
    expect(listTopics).not.toHaveBeenCalled();
    expect(staleError).toContain("not running");

    pending.resolve({ running: true, pid: 42 });
    await startup;

    expect(listTopics).toHaveBeenCalledTimes(1);
    expect(staleError).toBe("");
  });

  it("fails closed without unlocking topic commands when initialize is not running", async () => {
    const onReady = vi.fn();
    await expect(initializeGovernanceCore({
      initialize: async () => ({ running: false }),
      onReady,
    })).rejects.toThrow("did not report a running state");
    expect(onReady).not.toHaveBeenCalled();
  });

  it("ignores a superseded StrictMode-style boot acknowledgement", async () => {
    const first = deferred<{ running: boolean }>();
    const second = deferred<{ running: boolean }>();
    let currentAttempt = 1;
    const ready = vi.fn();

    const staleStartup = initializeGovernanceCore({
      initialize: () => first.promise,
      isCurrent: () => currentAttempt === 1,
      onReady: ready,
    });
    currentAttempt = 2;
    const currentStartup = initializeGovernanceCore({
      initialize: () => second.promise,
      isCurrent: () => currentAttempt === 2,
      onReady: ready,
    });

    first.resolve({ running: true });
    await staleStartup;
    expect(ready).not.toHaveBeenCalled();

    second.resolve({ running: true });
    await currentStartup;
    expect(ready).toHaveBeenCalledTimes(1);
  });
});
