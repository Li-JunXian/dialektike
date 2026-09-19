import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PermissionModal } from "./PermissionModal";
import type { PermissionField, ProviderDescriptor } from "../state/model";

function descriptor(runtimeId: string, name: string, requestKind: string, layout: string, fields: PermissionField[]): ProviderDescriptor {
  return {
    schemaVersion: 1, descriptorVersion: 1, runtimeId, vendorId: `${runtimeId}-vendor`, agentSystemId: runtimeId, relayProviderId: runtimeId,
    display: { name, shortName: name, mark: "T", iconToken: "terminal", accentToken: "blue" },
    authentication: { label: "Auth", authority: "test", notObservableLabel: "Not observable" },
    versionEvidence: { label: "Version", authority: "test", notObservableLabel: "Not observable" },
    defaultSelection: { model: null, effort: null, serviceTier: null, executionProfile: "inherit-native" },
    controlSchema: [], supportedContentTypes: ["markdown"],
    executionProfiles: [{ profileId: "inherit-native", label: "Inherit native", description: "test", availability: { available: true }, values: {} }],
    runtimeFacilities: [],
    permissionPresentations: [{ requestKind, title: "Native permission", layout, fields }],
    connect: { label: "Connect", helpText: "Connect runtime", action: "refresh-capabilities" },
  };
}

describe("trusted permission modal", () => {
  it("uses Claude Code native hierarchy and keeps relay evidence under Details", () => {
    const html = renderToStaticMarkup(
      <PermissionModal
        request={{
          permission_id: "permission-1",
          runtime_id: "claude-code",
          request_kind: "can_use_tool",
          title: "Write",
          card: "FULL NATIVE CARD\nsecond line",
          native_payload: {
            tool: "Write",
            input: { path: "/tmp/example", content: "full content" },
            native_context: {
              description: "Create the requested file",
              decision_reason: "Path is outside allowed working directories",
              blocked_path: "/tmp/example",
            },
          },
          annotations: {
            path_confined: false,
            resolved_path: "/tmp/example",
          },
        }}
        descriptor={descriptor("claude-code", "Claude Code", "can_use_tool", "tool", [
          { fieldId: "tool", label: "Tool", pointer: "/tool", format: "text" },
          { fieldId: "input", label: "Input", pointer: "/input", format: "json" },
        ])}
        queuedCount={1}
        submitting={false}
        error=""
        onDecision={() => undefined}
      />,
    );

    expect(html).toContain("FULL NATIVE CARD\nsecond line");
    expect(html).toContain("&quot;full content&quot;");
    expect(html).toContain("&quot;path_confined&quot;");
    expect(html).toContain("&quot;resolved_path&quot;");
    expect(html).toContain("native-permission--tool");
    expect(html).toContain("Native permission");
    expect(html.indexOf("FULL NATIVE CARD")).toBeGreaterThan(
      html.indexOf("Details"),
    );
  });

  it("uses the Codex command hierarchy without promoting raw ids", () => {
    const html = renderToStaticMarkup(
      <PermissionModal
        request={{
          permission_id: "permission-2",
          runtime_id: "codex",
          request_kind: "item/commandExecution/requestApproval",
          title: "Run shell command",
          card: "VERBATIM CODEX RELAY CARD",
          native_payload: {
            command: ["git", "status", "--short"],
            reason: "Inspect the working tree",
            cwd: "/workspace",
            approvalId: "raw-approval-id",
          },
          annotations: { command_id_sha256: "abc" },
        }}
        descriptor={descriptor("codex", "Codex", "item/commandExecution/requestApproval", "command", [
          { fieldId: "command", label: "Command", pointer: "/command", format: "code" },
          { fieldId: "cwd", label: "Working directory", pointer: "/cwd", format: "path" },
        ])}
        queuedCount={1}
        submitting={false}
        error=""
        onDecision={() => undefined}
      />,
    );

    expect(html).toContain("native-permission--command");
    expect(html).toContain("git status --short");
    expect(html).toContain("/workspace");
    expect(html.indexOf("raw-approval-id")).toBeGreaterThan(
      html.indexOf("Details"),
    );
  });

  it("renders an unanticipated provider permission from its generic descriptor", () => {
    const html = renderToStaticMarkup(
      <PermissionModal
        request={{
          permission_id: "permission-synthetic-1",
          runtime_id: "synthetic.quantum",
          request_kind: "quantum/review",
          title: "Fallback request title",
          card: "VERBATIM SYNTHETIC RELAY CARD",
          native_payload: {
            review: {
              subject: "Proposed deployment",
              checks: ["signature", "rate-limit"],
            },
            internal_request_id: "owner-only-synthetic-id",
          },
          annotations: { descriptor_digest: "synthetic-digest" },
        }}
        descriptor={descriptor("synthetic.quantum", "Quantum Reviewer", "quantum/review", "review-card", [
          { fieldId: "subject", label: "Review subject", pointer: "/review/subject", format: "text" },
          { fieldId: "checks", label: "Required checks", pointer: "/review/checks", format: "json" },
          { fieldId: "second-check", label: "Second check", pointer: "/review/checks/1", format: "text" },
          { fieldId: "invalid-index", label: "Invalid index", pointer: "/review/checks/01", format: "text" },
        ])}
        queuedCount={1}
        submitting={false}
        error=""
        onDecision={() => undefined}
      />,
    );

    expect(html).toContain("Quantum Reviewer is requesting permission");
    expect(html).toContain("native-permission--review-card");
    expect(html).toContain("Native permission");
    expect(html).toContain("Review subject");
    expect(html).toContain("Proposed deployment");
    expect(html).toContain("Required checks");
    expect(html).toContain("&quot;rate-limit&quot;");
    expect(html).toContain("Second check");
    expect(html).toContain("<dd>rate-limit</dd>");
    expect(html).not.toContain("Invalid index");
    expect(html).not.toContain("Codex");
    expect(html).not.toContain("Claude Code");
    expect(html.indexOf("owner-only-synthetic-id")).toBeGreaterThan(html.indexOf("Details"));
  });
});
