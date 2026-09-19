import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type {
  CapabilityCatalog,
  ParticipantConfiguration,
  ProviderDescriptor,
  RuntimeCapabilities,
} from "../state/model";
import { ParticipantManager } from "./ParticipantManager";

describe("descriptor-driven participant manager", () => {
  it("accepts and renders unanticipated synthetic providers without shared-provider branches", () => {
    const catalog: CapabilityCatalog = Object.fromEntries([
      provider("synthetic.executor", "vendor.synthetic.executor", "Synthetic Executor", "Authenticated synthetic executor"),
      provider("synthetic.auditor", "vendor.synthetic.auditor", "Synthetic Auditor", "Authenticated synthetic auditor"),
      provider("future.reviewer", "vendor.future.reviewer", "Future Reviewer", "Authenticated future reviewer"),
    ]);
    const configuration: ParticipantConfiguration = {
      executor: participant("executor-1", "executor", 0, "synthetic.executor"),
      auditors: [participant("auditor-1", "auditor", 0, "synthetic.auditor")],
    };

    const html = renderToStaticMarkup(
      <ParticipantManager
        open
        configuration={configuration}
        catalog={catalog}
        rounds={1}
        disabled={false}
        refreshing={false}
        issues={[]}
        onClose={() => undefined}
        onRoundsChange={() => undefined}
        onRefresh={() => undefined}
        onRuntimeChange={() => undefined}
        onAddAuditor={() => undefined}
        onRemoveAuditor={() => undefined}
        onMoveAuditor={() => undefined}
      />,
    );

    expect(html).toContain("Synthetic Executor · Authenticated synthetic executor");
    expect(html).toContain("Synthetic Auditor · Authenticated synthetic auditor");
    expect(html).toContain('<option value="future.reviewer">Future Reviewer</option>');
    expect(html).toContain("Add Future Reviewer");
    expect(html).not.toContain("Codex");
    expect(html).not.toContain("Claude Code");
  });

  it("renders unavailable providers from their declared connection metadata", () => {
    const catalog: CapabilityCatalog = Object.fromEntries([
      provider("synthetic.executor", "vendor.synthetic.executor", "Synthetic Executor", "Authenticated synthetic executor"),
      provider("synthetic.auditor", "vendor.synthetic.auditor", "Synthetic Auditor", "Authenticated synthetic auditor"),
      provider(
        "future.reviewer",
        "vendor.future.reviewer",
        "Future Reviewer",
        "Not authenticated",
        false,
        { label: "Authorize Future Reviewer", helpText: "Sign in through the approved Future Reviewer runtime, then refresh.", action: "refresh-capabilities" },
      ),
    ]);
    const configuration: ParticipantConfiguration = {
      executor: participant("executor-1", "executor", 0, "synthetic.executor"),
      auditors: [participant("auditor-1", "auditor", 0, "synthetic.auditor")],
    };

    const html = renderToStaticMarkup(
      <ParticipantManager
        open
        configuration={configuration}
        catalog={catalog}
        rounds={1}
        disabled={false}
        refreshing={false}
        issues={[]}
        onClose={() => undefined}
        onRoundsChange={() => undefined}
        onRefresh={() => undefined}
        onRuntimeChange={() => undefined}
        onAddAuditor={() => undefined}
        onRemoveAuditor={() => undefined}
        onMoveAuditor={() => undefined}
      />,
    );

    expect(html).toContain("Authorize Future Reviewer");
    expect(html).toContain("Sign in through the approved Future Reviewer runtime, then refresh.");
    expect(html).toContain('data-connect-action="refresh-capabilities"');
    expect(html).not.toContain("Connect another provider");
  });
});

function provider(
  runtimeId: string,
  vendorId: string,
  name: string,
  accountRoute: string,
  available = true,
  connect: ProviderDescriptor["connect"] = { label: "Connect", helpText: "Authenticate provider", action: "refresh-capabilities" },
): [string, RuntimeCapabilities] {
  const descriptor: ProviderDescriptor = {
    schemaVersion: 1,
    descriptorVersion: 1,
    runtimeId,
    vendorId,
    agentSystemId: runtimeId,
    relayProviderId: runtimeId,
    display: { name, shortName: name, mark: "S", iconToken: "terminal", accentToken: "blue" },
    authentication: { label: "Authentication", authority: "synthetic-test", notObservableLabel: "Not observable" },
    versionEvidence: { label: "Version", authority: "synthetic-test", notObservableLabel: "Not observable" },
    defaultSelection: { model: null, effort: null, serviceTier: null, executionProfile: "inherit-native" },
    controlSchema: [],
    supportedContentTypes: ["markdown"],
    executionProfiles: [{
      profileId: "inherit-native",
      label: "Inherit native",
      description: "Use provider-native defaults",
      availability: { available: true },
      values: {},
    }],
    runtimeFacilities: [],
    permissionPresentations: [],
    connect,
  };
  return [runtimeId, {
    runtimeId,
    descriptor,
    availability: available
      ? { available: true }
      : { available: false, reason: "Authentication required" },
    accountRoute,
    runtimeVersion: "synthetic-1",
    models: [],
  }];
}

function participant(participantId: string, role: "executor" | "auditor", order: number, runtimeId: string) {
  return {
    participantId,
    role,
    order,
    runtimeId,
    requested: {
      model: "native-default",
      effort: "native-default",
      serviceTier: "native-default",
      executionProfile: { profileId: "inherit-native", values: {} },
    },
    effective: null,
  };
}
