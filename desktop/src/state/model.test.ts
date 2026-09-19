import { describe, expect, it } from "vitest";

import {
  NATIVE_DEFAULT_SERVICE_TIER,
  assignRuntime,
  availableOption,
  canStartRun,
  canStopRun,
  clearParticipantSelections,
  createDefaultParticipants,
  explicitModelOptions,
  hydrateRequestedDefaults,
  reconcileParticipantConfiguration,
  createDefaultParticipantConfiguration,
  recordEffectiveSettings,
  requestForSelectedModel,
  reduceRunState,
  serviceTierOptions,
  swapExecutorWithAuditor,
  unconfiguredRequestForRuntime,
  unavailableOption,
  validateParticipantSelection,
  validateRunConfiguration,
  type CapabilityCatalog,
  type ModelCapability,
  type ProviderDescriptor,
  type RunState,
  type RuntimeCapabilities,
} from "./model";

function model(
  id: string,
  efforts = [availableOption("ultra", "Ultra")],
  serviceTiers = serviceTierOptions([]),
): ModelCapability {
  return {
    ...availableOption(id, id),
    efforts,
    serviceTiers,
  };
}

function runtime(
  runtimeId: RuntimeCapabilities["runtimeId"],
  models: ModelCapability[],
): RuntimeCapabilities {
  return {
    runtimeId,
    descriptor: testDescriptor(runtimeId),
    availability: { available: true },
    accountRoute: runtimeId === "codex" ? "chatgpt" : "firstParty",
    runtimeVersion: "test",
    models,
  };
}

function testDescriptor(runtimeId: string): ProviderDescriptor {
  return {
    schemaVersion: 1,
    descriptorVersion: 1,
    runtimeId,
    vendorId: runtimeId === "codex" ? "openai" : runtimeId === "claude-code" ? "anthropic" : `${runtimeId}-vendor`,
    agentSystemId: runtimeId,
    relayProviderId: runtimeId,
    display: { name: runtimeId, shortName: runtimeId, mark: "T", iconToken: "terminal", accentToken: "blue" },
    authentication: { label: "Auth", authority: "test", notObservableLabel: "Not observable" },
    versionEvidence: { label: "Version", authority: "test", notObservableLabel: "Not observable" },
    defaultSelection: { model: null, effort: null, serviceTier: null, executionProfile: "inherit-native" },
    controlSchema: [],
    supportedContentTypes: ["markdown"],
    executionProfiles: [{ profileId: "inherit-native", label: "Inherit native", description: "test", availability: { available: true }, values: {} }],
    runtimeFacilities: [],
    permissionPresentations: [],
    connect: { label: "Connect", helpText: "Connect runtime", action: "refresh-capabilities" },
  };
}

function syntheticDescriptor(
  runtimeId: string,
  vendorId = "verdant-labs",
): ProviderDescriptor {
  return {
    ...testDescriptor(runtimeId),
    vendorId,
    agentSystemId: "agent-system-42",
    relayProviderId: `${runtimeId}-relay`,
    display: {
      name: "Unexpected Runtime",
      shortName: "Unexpected",
      mark: "U",
      iconToken: "provider",
      accentToken: "verdant",
    },
    defaultSelection: {
      model: null,
      effort: null,
      serviceTier: null,
      executionProfile: "governed",
    },
    controlSchema: [
      {
        controlId: "response-style",
        label: "Response style",
        group: "turn",
        kind: "select",
        description: "A synthetic provider turn control.",
        authority: "runtime-contract",
        defaultValue: "lucid",
        options: [
          {
            value: "lucid",
            label: "Lucid",
            availability: { available: true },
          },
          {
            value: "orbital",
            label: "Orbital",
            availability: {
              available: false,
              reason: "Not included in this subscription",
            },
          },
        ],
        minValue: null,
        maxValue: null,
      },
      {
        controlId: "network-access",
        label: "Network access",
        group: "execution",
        kind: "boolean",
        description: "A synthetic execution control.",
        authority: "runtime-contract",
        defaultValue: false,
        options: [],
        minValue: null,
        maxValue: null,
      },
    ],
    executionProfiles: [
      {
        profileId: "governed",
        label: "Governed",
        description: "Use the reviewed synthetic profile.",
        availability: { available: true },
        values: { "network-access": false },
      },
    ],
  };
}

function syntheticRuntime(
  runtimeId: string,
  vendorId = "verdant-labs",
): RuntimeCapabilities {
  return {
    runtimeId,
    descriptor: syntheticDescriptor(runtimeId, vendorId),
    availability: { available: true },
    accountRoute: "synthetic-subscription",
    runtimeVersion: "synthetic-7",
    models: [
      model("synthetic-model", [availableOption("deliberate", "Deliberate")]),
    ],
  };
}

describe("participant defaults", () => {
  it("creates occupied seats without silently choosing model or effort", () => {
    const participants = createDefaultParticipants();

    expect(participants.executor).toEqual({
      participantId: "executor-1",
      role: "executor",
      order: 0,
      runtimeId: "codex",
      requested: {
        model: "",
        effort: "",
        serviceTier: "native-default",
        controls: undefined,
        executionProfile: { profileId: "inherit-native", values: {} },
      },
      effective: null,
    });
    expect(participants.auditor).toEqual({
      participantId: "auditor-1",
      role: "auditor",
      order: 0,
      runtimeId: "claude-code",
      requested: {
        model: "",
        effort: "",
        serviceTier: "native-default",
        controls: undefined,
        executionProfile: { profileId: "inherit-native", values: {} },
      },
      effective: null,
    });
  });

  it("returns independent participant objects", () => {
    const first = createDefaultParticipants();
    const second = createDefaultParticipants();

    first.executor.requested.model = "changed";
    expect(second.executor.requested.model).toBe("");
  });

  it("reverses providers without changing role identity or carrying effective data", () => {
    const participants = createDefaultParticipantConfiguration();
    const executor = recordEffectiveSettings(participants.executor, {
      model: "gpt-5.6-sol",
      effort: "ultra",
      serviceTier: null,
      authority: "model/service tier: runtime echo; effort: accepted",
    });

    const reversed = assignRuntime(executor, "claude-code", {
      model: "opus",
      effort: "xhigh",
      serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
    });

    expect(reversed.role).toBe("executor");
    expect(reversed.runtimeId).toBe("claude-code");
    expect(reversed.requested.model).toBe("opus");
    expect(reversed.effective).toBeNull();
  });

  it("records effective settings separately from requested settings", () => {
    const participant = createDefaultParticipants().executor;
    const updated = recordEffectiveSettings(participant, {
      model: "gpt-5.6-sol-20260720",
      effort: "ultra",
      serviceTier: null,
      authority: "model/service tier: runtime echo; effort: accepted",
    });

    expect(updated.requested.model).toBe("");
    expect(updated.effective?.model).toBe("gpt-5.6-sol-20260720");
    expect(updated.effective?.authority).toContain("runtime echo");
    expect(participant.effective).toBeNull();
  });
});

describe("capability choices", () => {
  it("materializes provider defaults that the participant picker displays", () => {
    const capabilities = syntheticRuntime("unexpected.runtime-7");
    const requested = hydrateRequestedDefaults({
      model: "synthetic-model",
      effort: "deliberate",
      serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
    }, capabilities);

    expect(requested.controls).toEqual({ "response-style": "lucid" });
    expect(requested.executionProfile).toEqual({
      profileId: "governed",
      values: { "network-access": false },
    });
  });

  it("validates an unanticipated provider through descriptor controls", () => {
    const participant = {
      ...createDefaultParticipants().auditor,
      runtimeId: "unexpected.runtime-7",
      requested: {
        model: "synthetic-model",
        effort: "deliberate",
        serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
        controls: { "response-style": "lucid" },
        executionProfile: {
          profileId: "governed",
          values: { "network-access": false },
        },
      },
    };
    const catalog: CapabilityCatalog = {
      "unexpected.runtime-7": syntheticRuntime("unexpected.runtime-7"),
    };

    expect(validateParticipantSelection(participant, catalog)).toEqual([]);
    expect(
      validateParticipantSelection(
        {
          ...participant,
          requested: {
            ...participant.requested,
            controls: { "response-style": "orbital" },
          },
        },
        catalog,
      ),
    ).toContainEqual({
      field: "controls",
      code: "invalid",
      message: "Response style has an invalid or unavailable value.",
    });
    expect(
      validateParticipantSelection(
        {
          ...participant,
          requested: {
            ...participant.requested,
            executionProfile: {
              profileId: "governed",
              values: { "network-access": true },
            },
          },
        },
        catalog,
      ),
    ).toContainEqual({
      field: "executionProfile",
      code: "invalid",
      message: "Governed does not match its reviewed provider definition.",
    });
  });

  it("enforces distinct vendor ids without enumerating runtime ids", () => {
    const defaults = createDefaultParticipantConfiguration();
    const executor = {
      ...defaults.executor,
      runtimeId: "unexpected.runtime-7",
      requested: {
        model: "synthetic-model",
        effort: "deliberate",
        serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
        controls: { "response-style": "lucid" },
        executionProfile: {
          profileId: "governed",
          values: { "network-access": false },
        },
      },
    };
    const auditor = {
      ...defaults.auditors[0],
      runtimeId: "alternate.runtime-8",
      requested: {
        model: "synthetic-model",
        effort: "deliberate",
        serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
        controls: { "response-style": "lucid" },
        executionProfile: {
          profileId: "governed",
          values: { "network-access": false },
        },
      },
    };
    const participants = { executor, auditors: [auditor] };
    const distinctCatalog: CapabilityCatalog = {
      "unexpected.runtime-7": syntheticRuntime(
        "unexpected.runtime-7",
        "verdant-labs",
      ),
      "alternate.runtime-8": syntheticRuntime(
        "alternate.runtime-8",
        "cobalt-labs",
      ),
    };
    expect(
      validateRunConfiguration({ participants, rounds: 1 }, distinctCatalog),
    ).toEqual([]);

    const sameVendorCatalog: CapabilityCatalog = {
      ...distinctCatalog,
      "alternate.runtime-8": syntheticRuntime(
        "alternate.runtime-8",
        "verdant-labs",
      ),
    };
    expect(
      validateRunConfiguration({ participants, rounds: 1 }, sameVendorCatalog),
    ).toContainEqual({
      field: "participants",
      code: "same-vendor",
      message: "Every seat must use a different vendor in the same topic.",
    });
  });

  it("uses Native default as the only service tier when none is advertised", () => {
    expect(serviceTierOptions([])).toEqual([
      {
        id: "native-default",
        label: "Native default",
        availability: { available: true },
      },
    ]);
  });

  it("does not require an effort choice when the selected model exposes no effort control", () => {
    const participant = {
      ...createDefaultParticipants().auditor,
      requested: {
        model: "haiku",
        effort: "",
        serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
      },
    };
    const catalog: CapabilityCatalog = {
      "claude-code": runtime("claude-code", [
        model("haiku", []),
      ]),
    };

    expect(validateParticipantSelection(participant, catalog)).toEqual([]);
  });

  it("keeps a billed mode visible but Native default selectable", () => {
    const advertised = [
      unavailableOption("fast", "Fast", "Billed outside the subscription."),
    ];

    expect(serviceTierOptions(advertised)).toEqual([
      availableOption("native-default", "Native default"),
      ...advertised,
    ]);
  });

  it("requires an unavailable choice to carry a reason", () => {
    expect(() => unavailableOption("fast", "Fast", "  ")).toThrow(
      "requires a reason",
    );
  });

  it("accepts only advertised, available, model-compatible settings", () => {
    const participant = {
      ...createDefaultParticipants().executor,
      requested: {
        model: "gpt-5.6-sol",
        effort: "ultra",
        serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
      },
    };
    const catalog: CapabilityCatalog = {
      codex: runtime("codex", [model("gpt-5.6-sol")]),
    };

    expect(validateParticipantSelection(participant, catalog)).toEqual([]);
  });

  it("fails before a turn when an explicit option is unavailable", () => {
    const participant = {
      ...createDefaultParticipants().executor,
      requested: {
        model: "gpt-5.6-sol",
        effort: "ultra",
        serviceTier: "priority",
      },
    };
    const catalog: CapabilityCatalog = {
      codex: runtime("codex", [
        model(
          "gpt-5.6-sol",
          [availableOption("ultra", "Ultra")],
          [
            unavailableOption(
              "priority",
              "Priority",
              "Uses separately billed credits.",
            ),
          ],
        ),
      ]),
    };

    expect(validateParticipantSelection(participant, catalog)).toEqual([
      {
        field: "serviceTier",
        code: "unavailable",
        message:
          "Priority is unavailable: Uses separately billed credits.",
      },
    ]);
  });

  it("reports unsupported choices instead of silently substituting them", () => {
    const participant = {
      ...createDefaultParticipants().executor,
      requested: {
        model: "gpt-5.6-sol",
        effort: "xhigh",
        serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
      },
    };
    const catalog: CapabilityCatalog = {
      codex: runtime("codex", [model("gpt-5.6-sol")]),
    };

    expect(validateParticipantSelection(participant, catalog)).toEqual([
      {
        field: "effort",
        code: "not-advertised",
        message: "xhigh is not advertised for gpt-5.6-sol.",
      },
    ]);
    expect(participant.requested.effort).toBe("xhigh");
  });

  it("blocks starting while a runtime catalog is absent", () => {
    const issues = validateParticipantSelection(
      createDefaultParticipants().auditor,
      {},
    );

    expect(issues).toEqual([
      {
        field: "capabilities",
        code: "not-loaded",
        message: "Capabilities for claude-code are not loaded.",
      },
    ]);
  });

  it("validates positive integral rounds and both participants", () => {
    const participants = createDefaultParticipantConfiguration();
    participants.executor.requested = {
      model: "gpt-5.6-sol",
      effort: "ultra",
      serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
    };
    participants.auditors[0].requested = {
      model: "opus",
      effort: "xhigh",
      serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
    };
    const catalog: CapabilityCatalog = {
      codex: runtime("codex", [model("gpt-5.6-sol")]),
      "claude-code": runtime("claude-code", [
        model("opus", [availableOption("xhigh", "XHigh")]),
      ]),
    };

    expect(
      validateRunConfiguration({ participants, rounds: 2 }, catalog),
    ).toEqual([]);
    expect(
      validateRunConfiguration({ participants, rounds: 1.5 }, catalog)[0]
    ).toEqual({
      field: "rounds",
      code: "invalid",
      message: "Rounds must be a positive integer.",
    });
  });

  it("requires Live to select model and advertised effort explicitly", () => {
    const participant = createDefaultParticipants().executor;
    const catalog: CapabilityCatalog = {
      codex: runtime("codex", [model("gpt-5.6-sol")]),
    };

    expect(validateParticipantSelection(participant, catalog)).toContainEqual({
      field: "model",
      code: "invalid",
      message: "Select a model for codex.",
    });
    const modelSelected = {
      ...participant,
      requested: requestForSelectedModel(
        participant.requested,
        "gpt-5.6-sol",
        catalog.codex.models,
      ),
    };
    expect(modelSelected.requested.effort).toBe("");
    expect(validateParticipantSelection(modelSelected, catalog)).toContainEqual({
      field: "effort",
      code: "invalid",
      message: "Select effort for gpt-5.6-sol.",
    });
  });

  it("starts a fresh topic with blank model and effort while preserving its seats", () => {
    const original = createDefaultParticipantConfiguration();
    original.executor.requested = {
      model: "gpt-5.6-sol",
      effort: "ultra",
      serviceTier: "priority",
      controls: { "response-style": "orbital" },
      executionProfile: {
        profileId: "governed",
        values: { "network-access": false },
      },
    };
    original.executor.effective = {
      model: "gpt-5.6-sol",
      effort: "ultra",
      serviceTier: "priority",
      authority: "runtime echo",
    };
    original.auditors[0].requested = {
      model: "opus",
      effort: "xhigh",
      serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
    };

    const catalog: CapabilityCatalog = {
      codex: runtime("codex", [model("gpt-5.6-sol")]),
      "claude-code": runtime("claude-code", [
        model("opus", [availableOption("xhigh", "XHigh")]),
      ]),
    };
    const fresh = clearParticipantSelections(original, catalog);

    expect(fresh.executor.participantId).toBe(original.executor.participantId);
    expect(fresh.executor.role).toBe("executor");
    expect(fresh.executor.runtimeId).toBe("codex");
    expect(fresh.executor.requested.model).toBe("");
    expect(fresh.executor.requested.effort).toBe("");
    expect(fresh.executor.requested.serviceTier).toBe(
      NATIVE_DEFAULT_SERVICE_TIER,
    );
    expect(fresh.executor.effective).toBeNull();
    expect(fresh.auditors[0].participantId).toBe(
      original.auditors[0].participantId,
    );
    expect(fresh.auditors[0].role).toBe("auditor");
    expect(fresh.auditors[0].runtimeId).toBe("claude-code");
    expect(fresh.auditors[0].requested.model).toBe("");
    expect(fresh.auditors[0].requested.effort).toBe("");
    expect(original.executor.requested.model).toBe("gpt-5.6-sol");
    expect(original.auditors[0].requested.model).toBe("opus");
  });

  it("rejects a runtime-default alias as an explicit model version", () => {
    const alias = {
      ...model("default"),
      label: "Default (recommended)",
      explicitSelectable: false,
    };
    const participant = {
      ...createDefaultParticipants().executor,
      requested: {
        model: "default",
        effort: "ultra",
        serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
      },
    };
    const catalog: CapabilityCatalog = {
      codex: runtime("codex", [alias, model("concrete-model")]),
    };

    expect(validateParticipantSelection(participant, catalog)).toEqual([
      {
        field: "model",
        code: "invalid",
        message: "Default (recommended) is a runtime default, not an explicit model version. Select a concrete model.",
      },
    ]);
    expect(explicitModelOptions(catalog.codex.models).map((item) => item.id)).toEqual([
      "concrete-model",
    ]);
    expect(
      requestForSelectedModel(
        participant.requested,
        "default",
        catalog.codex.models,
      ),
    ).toEqual(participant.requested);
  });

  it("does not materialize descriptor model or effort defaults for a new runtime assignment", () => {
    const capabilities = syntheticRuntime("unexpected.runtime-7");
    const request = unconfiguredRequestForRuntime(capabilities);

    expect(request.model).toBe("");
    expect(request.effort).toBe("");
    expect(request.controls).toEqual({ "response-style": "lucid" });
    expect(request.executionProfile).toEqual({
      profileId: "governed",
      values: { "network-access": false },
    });
  });

  it("swaps complete runtime assignments while preserving stable seat identities", () => {
    const participants = createDefaultParticipantConfiguration();
    participants.executor = {
      ...participants.executor,
      runtimeId: "runtime.executor",
      requested: {
        model: "executor-model",
        effort: "high",
        serviceTier: "standard",
        controls: { style: "precise" },
        executionProfile: { profileId: "manual", values: { approval: true } },
      },
      effective: {
        model: "executor-effective",
        effort: "high",
        serviceTier: "standard",
        authority: "runtime echo",
      },
    };
    participants.auditors[0] = {
      ...participants.auditors[0],
      runtimeId: "runtime.auditor",
      requested: {
        model: "auditor-model",
        effort: "medium",
        serviceTier: "native-default",
        controls: { style: "careful" },
        executionProfile: { profileId: "plan", values: { approval: false } },
      },
      effective: {
        model: "auditor-effective",
        effort: "medium",
        serviceTier: null,
        authority: "runtime echo",
      },
    };

    const swapped = swapExecutorWithAuditor(
      participants,
      participants.auditors[0].participantId,
    );

    expect(swapped.executor).toMatchObject({
      participantId: "executor-1",
      role: "executor",
      order: 0,
      runtimeId: "runtime.auditor",
      requested: participants.auditors[0].requested,
      effective: participants.auditors[0].effective,
    });
    expect(swapped.auditors[0]).toMatchObject({
      participantId: "auditor-1",
      role: "auditor",
      order: 0,
      runtimeId: "runtime.executor",
      requested: participants.executor.requested,
      effective: participants.executor.effective,
    });
    swapped.executor.requested.controls!.style = "changed";
    expect(participants.auditors[0].requested.controls!.style).toBe("careful");
  });
});

describe("run lifecycle", () => {
  it("starts, advances rounds, and completes", () => {
    let state: RunState = { phase: "idle" };

    state = reduceRunState(state, { type: "start-requested", rounds: 3 });
    expect(state).toEqual({ phase: "starting", rounds: 3 });
    state = reduceRunState(state, { type: "started", runId: "run-1" });
    state = reduceRunState(state, { type: "round-started", round: 2 });
    expect(state).toMatchObject({
      phase: "running",
      runId: "run-1",
      currentRound: 2,
      rounds: 3,
    });
    state = reduceRunState(state, { type: "completed" });
    expect(state).toEqual({ phase: "completed", runId: "run-1" });
  });

  it("supports Live stopping an active run", () => {
    let state: RunState = {
      phase: "running",
      runId: "run-1",
      currentRound: 1,
      rounds: 2,
    };

    expect(canStopRun(state)).toBe(true);
    state = reduceRunState(state, { type: "stop-requested" });
    expect(state.phase).toBe("stopping");
    state = reduceRunState(state, { type: "stopped", reason: "live" });
    expect(state).toEqual({
      phase: "stopped",
      runId: "run-1",
      reason: "live",
    });
    expect(canStartRun(state)).toBe(true);
  });

  it("preserves plan-warning as a distinct stop reason", () => {
    const state = reduceRunState(
      { phase: "starting", rounds: 1 },
      { type: "stopped", reason: "plan-warning" },
    );

    expect(state).toEqual({
      phase: "stopped",
      runId: null,
      reason: "plan-warning",
    });
  });

  it("ignores stale and impossible lifecycle events", () => {
    const idle: RunState = { phase: "idle" };
    expect(reduceRunState(idle, { type: "completed" })).toBe(idle);
    expect(reduceRunState(idle, { type: "start-requested", rounds: 0 })).toBe(
      idle,
    );

    const running: RunState = {
      phase: "running",
      runId: "run-1",
      currentRound: 2,
      rounds: 3,
    };
    expect(
      reduceRunState(running, { type: "round-started", round: 1 }),
    ).toBe(running);
    expect(
      reduceRunState(running, { type: "round-started", round: 4 }),
    ).toBe(running);
  });
});

describe("chat selection and dormant reviewer preservation", () => {
  it("allows the available selected speaker while full review requires its unavailable reviewer", () => {
    const configuration = createDefaultParticipantConfiguration();
    configuration.executor.requested.model = "chat-model";
    configuration.executor.requested.effort = "ultra";
    const catalog = { codex: runtime("codex", [model("chat-model")]), "claude-code": { ...runtime("claude-code", []), availability: { available: false, reason: "Offline" } } };
    expect(validateParticipantSelection(configuration.executor, catalog)).toEqual([]);
    expect(validateRunConfiguration({ participants: configuration, rounds: 1 }, catalog).some((issue) => issue.code === "unavailable")).toBe(true);
  });
  it("retains dormant runtime, model, effort, tier, controls and profile across catalog refresh", () => {
    const configuration = createDefaultParticipantConfiguration();
    configuration.auditors[0].requested = { model: "saved-model", effort: "max", serviceTier: "saved-tier", controls: { option: true }, executionProfile: { profileId: "saved", values: { setting: false } } };
    const catalog = { codex: runtime("codex", [model("chat-model")]), "claude-code": { ...runtime("claude-code", []), availability: { available: false, reason: "Offline" } } };
    expect(reconcileParticipantConfiguration(configuration, catalog).auditors).toEqual(configuration.auditors);
    expect(reconcileParticipantConfiguration(configuration, { codex: catalog.codex }).auditors).toEqual(configuration.auditors);
    const swapped = swapExecutorWithAuditor(configuration, configuration.auditors[0].participantId);
    expect(swapped.executor.runtimeId).toBe("claude-code");
    expect(swapped.executor.requested).toEqual(configuration.auditors[0].requested);
  });
});
