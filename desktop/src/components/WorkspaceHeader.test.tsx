import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceHeader } from "./WorkspaceHeader";

describe("participant header", () => {
  it("keeps management with the seats and omits the old status row", () => {
    const html = renderToStaticMarkup(
      <WorkspaceHeader
        executor={{ id: "executor-1", runtimeId: "codex", agentSystem: "Codex", modelLine: "Sol · Ultra" }}
        auditors={[{ id: "auditor-1", runtimeId: "claude-code", agentSystem: "Claude Code", modelLine: "Opus · Extra high" }]}
        activeRun={false}
        onSeatClick={() => undefined}
        onManageParticipants={() => undefined}
        onAddAuditor={() => undefined}
        onSwapRoles={() => undefined}
      />,
    );
    expect(html).toContain("seat-group__actions");
    expect(html).toContain("Add Auditor");
    expect(html).toContain("Manage");
    expect(html).toContain("Swap Executor with Auditor Claude Code");
    expect(html).not.toContain("workspace-status");
  });

  it("offers a compact deterministic chooser when several Auditors are seated", () => {
    const html = renderToStaticMarkup(
      <WorkspaceHeader
        executor={{ id: "executor-1", runtimeId: "executor", agentSystem: "Executor Runtime", modelLine: "Model E · High" }}
        auditors={[
          { id: "auditor-1", runtimeId: "auditor-a", agentSystem: "Auditor A", modelLine: "Model A · Medium" },
          { id: "auditor-2", runtimeId: "auditor-b", agentSystem: "Auditor B", modelLine: "Model B · High" },
        ]}
        activeRun={false}
        onSeatClick={() => undefined}
        onManageParticipants={() => undefined}
        onAddAuditor={() => undefined}
        onSwapRoles={() => undefined}
      />,
    );

    expect(html).toContain("Choose an Auditor to swap with the Executor");
    expect(html).toContain("Swap with Auditor A");
    expect(html).toContain("Swap with Auditor B");
  });
});
