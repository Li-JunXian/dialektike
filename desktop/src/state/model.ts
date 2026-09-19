/**
 * Provider identities are validated opaque strings. Shared desktop code must
 * never enumerate providers: the signed sidecar descriptor catalog is the
 * sole source of runtimes that may occupy a seat.
 */
export type RuntimeId = string;

const OPAQUE_ID = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$/;

export function isOpaqueId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 96 &&
    OPAQUE_ID.test(value)
  );
}

export const ROLE_IDS = ["executor", "auditor"] as const;
export type RoleId = (typeof ROLE_IDS)[number];

export const NATIVE_DEFAULT_EFFORT = "native-default";
export const NATIVE_DEFAULT_SERVICE_TIER = "native-default";
export const UNSELECTED_MODEL = "";
export const UNSELECTED_EFFORT = "";

export type ControlScalar = string | boolean | number;

export interface ExecutionProfileSelection {
  profileId: string;
  values: Record<string, ControlScalar>;
}

export interface RequestedSettings {
  model: string;
  effort: string;
  serviceTier: string;
  controls?: Record<string, ControlScalar>;
  executionProfile?: ExecutionProfileSelection;
}

export interface EffectiveSettings {
  model: string;
  effort: string | null;
  serviceTier: string | null;
  /**
   * Human-readable runtime evidence. This must distinguish values echoed by
   * the runtime from requests that were accepted but cannot be echoed.
   */
  authority: string;
  controls?: Record<string, {
    value: ControlScalar | null;
    authority: string;
    observable: boolean;
  }>;
  executionProfile?: {
    profileId: string;
    authority: string;
  };
}

export interface Participant {
  /** Stable within a topic; runtime/model changes never change seat identity. */
  participantId: string;
  role: RoleId;
  order: number;
  runtimeId: RuntimeId;
  requested: RequestedSettings;
  effective: EffectiveSettings | null;
}

export interface Available {
  available: true;
}

export interface Unavailable {
  available: false;
  reason: string;
}

export type Availability = Available | Unavailable;

export interface CapabilityOption {
  id: string;
  label: string;
  availability: Availability;
}

export type ControlGroup = "model" | "turn" | "execution" | "runtime";
export type ControlKind = "select" | "boolean" | "integer" | "status";

export interface ProviderControlOption {
  value: ControlScalar;
  label: string;
  availability: Availability;
}

export interface ProviderControlDefinition {
  controlId: string;
  label: string;
  group: ControlGroup;
  kind: ControlKind;
  description: string;
  authority: string;
  defaultValue: ControlScalar | null;
  options: ProviderControlOption[];
  minValue: number | null;
  maxValue: number | null;
}

export interface ExecutionProfileDefinition {
  profileId: string;
  label: string;
  description: string;
  availability: Availability;
  values: Record<string, ControlScalar>;
}

export interface RuntimeFacility {
  facilityId: string;
  label: string;
  description: string;
  observability: string;
  management: string;
}

export interface PermissionField {
  fieldId: string;
  label: string;
  pointer: string;
  format: string;
}

export interface PermissionPresentation {
  requestKind: string;
  title: string;
  layout: string;
  fields: PermissionField[];
}

export interface ProviderDescriptor {
  schemaVersion: 1;
  descriptorVersion: number;
  runtimeId: RuntimeId;
  vendorId: string;
  agentSystemId: string;
  relayProviderId: string;
  display: {
    name: string;
    shortName: string;
    mark: string;
    iconToken: string;
    accentToken: string;
  };
  authentication: {
    label: string;
    authority: string;
    notObservableLabel: string;
  };
  versionEvidence: {
    label: string;
    authority: string;
    notObservableLabel: string;
  };
  defaultSelection: {
    model: string | null;
    effort: string | null;
    serviceTier: string | null;
    executionProfile: string;
  };
  controlSchema: ProviderControlDefinition[];
  supportedContentTypes: string[];
  executionProfiles: ExecutionProfileDefinition[];
  runtimeFacilities: RuntimeFacility[];
  permissionPresentations: PermissionPresentation[];
  connect: {
    label: string;
    helpText: string;
    action: string;
  };
}

export interface ModelCapability extends CapabilityOption {
  description?: string;
  /** False for moving runtime-default aliases rather than pinned versions. */
  explicitSelectable?: boolean;
  efforts: CapabilityOption[];
  serviceTiers: CapabilityOption[];
}

export interface RuntimeCapabilities {
  runtimeId: RuntimeId;
  descriptor: ProviderDescriptor;
  availability: Availability;
  accountRoute: string | null;
  runtimeVersion: string | null;
  models: ModelCapability[];
}

export type CapabilityCatalog = Record<RuntimeId, RuntimeCapabilities>;

export interface SelectionIssue {
  field:
    | "capabilities"
    | "model"
    | "effort"
    | "serviceTier"
    | "controls"
    | "executionProfile"
    | "rounds"
    | "participants";
  code:
    | "not-loaded"
    | "not-advertised"
    | "unavailable"
    | "invalid"
    | "same-vendor";
  message: string;
}

export interface ParticipantConfiguration {
  executor: Participant;
  auditors: Participant[];
}

export interface RunConfiguration {
  participants: ParticipantConfiguration;
  rounds: number;
}

export type StopReason = "live" | "plan-warning";

export type RunState =
  | { phase: "idle" }
  | { phase: "starting"; rounds: number }
  | {
      phase: "running";
      runId: string;
      currentRound: number;
      rounds: number;
    }
  | {
      phase: "stopping";
      runId: string | null;
      currentRound: number;
      rounds: number;
    }
  | { phase: "stopped"; runId: string | null; reason: StopReason }
  | { phase: "completed"; runId: string }
  | { phase: "failed"; runId: string | null; message: string };

export type RunAction =
  | { type: "start-requested"; rounds: number }
  | { type: "started"; runId: string }
  | { type: "round-started"; round: number }
  | { type: "stop-requested" }
  | { type: "stopped"; reason: StopReason }
  | { type: "completed" }
  | { type: "failed"; message: string };

const available: Availability = Object.freeze({ available: true });

export const DEFAULT_PARTICIPANTS: Readonly<Record<RoleId, Participant>> =
  Object.freeze({
    executor: Object.freeze({
      participantId: "executor-1",
      role: "executor",
      order: 0,
      runtimeId: "codex",
      requested: Object.freeze({
        model: UNSELECTED_MODEL,
        effort: UNSELECTED_EFFORT,
        serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
        executionProfile: { profileId: "inherit-native", values: {} },
      }),
      effective: null,
    }),
    auditor: Object.freeze({
      participantId: "auditor-1",
      role: "auditor",
      order: 0,
      runtimeId: "claude-code",
      requested: Object.freeze({
        model: UNSELECTED_MODEL,
        effort: UNSELECTED_EFFORT,
        serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
        executionProfile: { profileId: "inherit-native", values: {} },
      }),
      effective: null,
    }),
  });

export function createDefaultParticipants(): Record<RoleId, Participant> {
  return {
    executor: cloneParticipant(DEFAULT_PARTICIPANTS.executor),
    auditor: cloneParticipant(DEFAULT_PARTICIPANTS.auditor),
  };
}

export function createDefaultParticipantConfiguration(): ParticipantConfiguration {
  const participants = createDefaultParticipants();
  return {
    executor: participants.executor,
    auditors: [participants.auditor],
  };
}

export function availableOption(id: string, label: string): CapabilityOption {
  return { id, label, availability: available };
}

export function unavailableOption(
  id: string,
  label: string,
  reason: string,
): CapabilityOption {
  const normalizedReason = reason.trim();
  if (!normalizedReason) {
    throw new Error("An unavailable option requires a reason.");
  }
  return {
    id,
    label,
    availability: { available: false, reason: normalizedReason },
  };
}

/**
 * "Speed" is represented by a native service tier. A runtime that advertises
 * no tiers has exactly one honest UI choice: Native default.
 */
export function serviceTierOptions(
  advertised: readonly CapabilityOption[],
): CapabilityOption[] {
  const cloned = advertised.map(cloneOption);
  const hasSelectableTier = advertised.some(
    (option) => option.availability.available,
  );
  const hasNativeDefault = advertised.some(
    (option) => option.id === NATIVE_DEFAULT_SERVICE_TIER,
  );
  if (hasSelectableTier || hasNativeDefault) {
    return cloned;
  }
  return [
    availableOption(NATIVE_DEFAULT_SERVICE_TIER, "Native default"),
    ...cloned,
  ];
}

/**
 * Assigning a runtime requires an explicit compatible selection. This avoids
 * silently carrying or substituting settings when roles are reversed.
 */
export function assignRuntime(
  participant: Participant,
  runtimeId: RuntimeId,
  requested: RequestedSettings,
): Participant {
  return {
    participantId: participant.participantId,
    role: participant.role,
    order: participant.order,
    runtimeId,
    requested: { ...requested },
    effective: null,
  };
}

/**
 * Return an intentionally incomplete request for a newly assigned runtime.
 * Model and effort are choices for Live, never values inferred from provider
 * ordering or descriptor defaults. Provider-declared controls and execution
 * profiles remain materialized because they are separate reviewed settings.
 */
export function unconfiguredRequestForRuntime(
  capabilities: RuntimeCapabilities | undefined,
): RequestedSettings {
  const controls = Object.fromEntries(
    (capabilities?.descriptor.controlSchema ?? [])
      .filter(
        (control) =>
          (control.group === "model" || control.group === "turn") &&
          control.defaultValue !== null,
      )
      .map((control) => [control.controlId, control.defaultValue!]),
  );
  const profileId =
    capabilities?.descriptor.defaultSelection.executionProfile ??
    "inherit-native";
  const profile = capabilities?.descriptor.executionProfiles.find(
    (candidate) => candidate.profileId === profileId,
  );
  return {
    model: UNSELECTED_MODEL,
    effort: UNSELECTED_EFFORT,
    serviceTier: NATIVE_DEFAULT_SERVICE_TIER,
    controls,
    executionProfile: {
      profileId,
      values: { ...(profile?.values ?? {}) },
    },
  };
}

/**
 * Start a fresh topic without silently carrying a prior topic's model/effort.
 * Runtime seats remain where Live placed them; every model-specific choice and
 * effective echo is reset for an explicit selection in the new topic.
 */
export function clearParticipantSelections(
  configuration: ParticipantConfiguration,
  catalog: CapabilityCatalog,
): ParticipantConfiguration {
  const clear = (participant: Participant): Participant =>
    assignRuntime(
      participant,
      participant.runtimeId,
      unconfiguredRequestForRuntime(catalog[participant.runtimeId]),
    );
  return {
    executor: clear(configuration.executor),
    auditors: configuration.auditors.map(clear),
  };
}

/** Selecting a model deliberately leaves effort for a second explicit choice. */
export function requestForSelectedModel(
  current: RequestedSettings,
  modelId: string,
  models: readonly ModelCapability[],
): RequestedSettings {
  const model = models.find((candidate) => candidate.id === modelId);
  if (!model || model.explicitSelectable === false) return { ...current };
  const tier = serviceTierOptions(model?.serviceTiers ?? []).find(
    (option) => option.availability.available,
  );
  return {
    ...current,
    model: modelId,
    effort: UNSELECTED_EFFORT,
    serviceTier: tier?.id ?? NATIVE_DEFAULT_SERVICE_TIER,
  };
}

export function explicitModelOptions(
  models: readonly ModelCapability[],
): ModelCapability[] {
  return models.filter((model) => model.explicitSelectable !== false);
}

/**
 * Exchange complete runtime assignments while keeping the stable topic seat
 * ids/roles/orders that historical messages reference.
 */
export function swapExecutorWithAuditor(
  configuration: ParticipantConfiguration,
  auditorId: string,
): ParticipantConfiguration {
  const auditorIndex = configuration.auditors.findIndex(
    (participant) => participant.participantId === auditorId,
  );
  if (auditorIndex < 0) return configuration;

  const sourceExecutor = configuration.executor;
  const sourceAuditor = configuration.auditors[auditorIndex];
  const executor = copyRuntimeAssignment(sourceExecutor, sourceAuditor);
  const auditors = configuration.auditors.map((participant, index) =>
    index === auditorIndex
      ? copyRuntimeAssignment(participant, sourceExecutor)
      : cloneParticipant(participant),
  );
  return { executor, auditors };
}

/** Materialize descriptor defaults before a request crosses the wire.
 * A control shown as selected in the UI must never disappear merely because
 * an older saved/default participant omitted the explicit value. */
export function hydrateRequestedDefaults(
  requested: RequestedSettings,
  capabilities: RuntimeCapabilities,
): RequestedSettings {
  const controls = { ...(requested.controls ?? {}) };
  for (const control of capabilities.descriptor.controlSchema) {
    if (
      (control.group === "model" || control.group === "turn") &&
      control.defaultValue !== null &&
      controls[control.controlId] === undefined
    ) controls[control.controlId] = control.defaultValue;
  }
  let executionProfile = requested.executionProfile;
  if (!executionProfile) {
    const defaultProfile = capabilities.descriptor.executionProfiles.find(
      (profile) => profile.profileId === capabilities.descriptor.defaultSelection.executionProfile,
    );
    if (defaultProfile) {
      executionProfile = {
        profileId: defaultProfile.profileId,
        values: { ...defaultProfile.values },
      };
    }
  }
  return {
    ...requested,
    controls,
    executionProfile,
  };
}

export function recordEffectiveSettings(
  participant: Participant,
  effective: EffectiveSettings,
): Participant {
  return {
    ...participant,
    requested: { ...participant.requested },
    effective: { ...effective },
  };
}

export function validateParticipantSelection(
  participant: Participant,
  catalog: CapabilityCatalog,
): SelectionIssue[] {
  const capabilities = catalog[participant.runtimeId];
  if (!capabilities) {
    return [
      {
        field: "capabilities",
        code: "not-loaded",
        message: `Capabilities for ${participant.runtimeId} are not loaded.`,
      },
    ];
  }
  if (!capabilities.availability.available) {
    return [
      {
        field: "capabilities",
        code: "unavailable",
        message: `${capabilities.descriptor.display.name} is unavailable: ${capabilities.availability.reason}`,
      },
    ];
  }

  const issues: SelectionIssue[] = [];
  if (!participant.requested.model) {
    return [
      {
        field: "model",
        code: "invalid",
        message: `Select a model for ${capabilities.descriptor.display.name}.`,
      },
    ];
  }
  const model = findOption(capabilities.models, participant.requested.model);
  if (!model) {
    return [
      notAdvertised(
        "model",
        participant.requested.model,
        participant.runtimeId,
      ),
    ];
  }
  if (!model.availability.available) {
    issues.push(unavailable("model", model));
    return issues;
  }
  if (model.explicitSelectable === false) {
    return [
      {
        field: "model",
        code: "invalid",
        message: `${model.label} is a runtime default, not an explicit model version. Select a concrete model.`,
      },
    ];
  }

  if (model.efforts.length > 0) {
    if (
      !participant.requested.effort ||
      participant.requested.effort === NATIVE_DEFAULT_EFFORT
    ) {
      issues.push({
        field: "effort",
        code: "invalid",
        message: `Select effort for ${model.label}.`,
      });
    } else {
      validateNestedOption(
        issues,
        "effort",
        participant.requested.effort,
        model.efforts,
        model.id,
      );
    }
  } else if (
    participant.requested.effort &&
    participant.requested.effort !== NATIVE_DEFAULT_EFFORT
  ) {
    issues.push(notAdvertised("effort", participant.requested.effort, model.id));
  }
  validateNestedOption(
    issues,
    "serviceTier",
    participant.requested.serviceTier,
    serviceTierOptions(model.serviceTiers),
    model.id,
  );
  const controls = participant.requested.controls ?? {};
  const declaredControls = new Map(
    capabilities.descriptor.controlSchema
      .filter((control) => control.group === "model" || control.group === "turn")
      .map((control) => [control.controlId, control]),
  );
  for (const [controlId, value] of Object.entries(controls)) {
    const control = declaredControls.get(controlId);
    if (!control) {
      issues.push({ field: "controls", code: "not-advertised", message: `${controlId} is not an advertised turn control for ${participant.runtimeId}.` });
      continue;
    }
    if (!validControlValue(control, value)) {
      issues.push({ field: "controls", code: "invalid", message: `${control.label} has an invalid or unavailable value.` });
    }
  }
  const defaultProfile = capabilities.descriptor.executionProfiles.find(
    (candidate) => candidate.profileId === capabilities.descriptor.defaultSelection.executionProfile,
  );
  const selectedProfile = participant.requested.executionProfile ?? (defaultProfile ? {
    profileId: defaultProfile.profileId,
    values: defaultProfile.values,
  } : undefined);
  if (!selectedProfile) {
    issues.push({ field: "executionProfile", code: "invalid", message: `The provider does not declare a default execution profile for ${capabilities.descriptor.display.name}.` });
  } else {
    const profile = capabilities.descriptor.executionProfiles.find((candidate) => candidate.profileId === selectedProfile.profileId);
    if (!profile) {
      issues.push({ field: "executionProfile", code: "not-advertised", message: `${selectedProfile.profileId} is not an advertised execution profile.` });
    } else if (!profile.availability.available) {
      issues.push({ field: "executionProfile", code: "unavailable", message: `${profile.label} is unavailable: ${profile.availability.reason}` });
    } else if (!sameControlRecord(profile.values, selectedProfile.values)) {
      issues.push({ field: "executionProfile", code: "invalid", message: `${profile.label} does not match its reviewed provider definition.` });
    }
  }
  return issues;
}

export function validateRunConfiguration(
  configuration: RunConfiguration,
  catalog: CapabilityCatalog,
): SelectionIssue[] {
  const issues: SelectionIssue[] = [];
  if (!Number.isInteger(configuration.rounds) || configuration.rounds < 1) {
    issues.push({
      field: "rounds",
      code: "invalid",
      message: "Rounds must be a positive integer.",
    });
  }
  const allParticipants = [
    configuration.participants.executor,
    ...configuration.participants.auditors,
  ];
  if (configuration.participants.auditors.length < 1) {
    issues.push({
      field: "participants",
      code: "invalid",
      message: "At least one Auditor is required.",
    });
  }
  const vendors = new Set<string>();
  for (const participant of allParticipants) {
    const provider = catalog[participant.runtimeId];
    const vendorId = provider?.descriptor.vendorId;
    if (vendorId && vendors.has(vendorId)) {
      issues.push({
        field: "participants",
        code: "same-vendor",
        message:
          "Every seat must use a different vendor in the same topic.",
      });
    }
    if (vendorId) vendors.add(vendorId);
    issues.push(...validateParticipantSelection(participant, catalog));
  }
  return issues;
}

export function canStartRun(state: RunState): boolean {
  return (
    state.phase === "idle" ||
    state.phase === "stopped" ||
    state.phase === "completed" ||
    state.phase === "failed"
  );
}

export function canStopRun(state: RunState): boolean {
  return state.phase === "starting" || state.phase === "running";
}

/**
 * Reduces trusted lifecycle facts into display state. Invalid or stale events
 * leave the current state untouched.
 */
export function reduceRunState(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "start-requested":
      if (!canStartRun(state) || !isPositiveInteger(action.rounds)) {
        return state;
      }
      return { phase: "starting", rounds: action.rounds };

    case "started":
      if (state.phase !== "starting" || !action.runId) {
        return state;
      }
      return {
        phase: "running",
        runId: action.runId,
        currentRound: 1,
        rounds: state.rounds,
      };

    case "round-started":
      if (
        state.phase !== "running" ||
        !isPositiveInteger(action.round) ||
        action.round < state.currentRound ||
        action.round > state.rounds
      ) {
        return state;
      }
      return { ...state, currentRound: action.round };

    case "stop-requested":
      if (state.phase !== "starting" && state.phase !== "running") {
        return state;
      }
      return {
        phase: "stopping",
        runId: state.phase === "running" ? state.runId : null,
        currentRound: state.phase === "running" ? state.currentRound : 0,
        rounds: state.rounds,
      };

    case "stopped":
      if (
        state.phase !== "starting" &&
        state.phase !== "running" &&
        state.phase !== "stopping"
      ) {
        return state;
      }
      return {
        phase: "stopped",
        runId: "runId" in state ? state.runId : null,
        reason: action.reason,
      };

    case "completed":
      if (state.phase !== "running") {
        return state;
      }
      return { phase: "completed", runId: state.runId };

    case "failed":
      if (
        state.phase !== "starting" &&
        state.phase !== "running" &&
        state.phase !== "stopping"
      ) {
        return state;
      }
      return {
        phase: "failed",
        runId: "runId" in state ? state.runId : null,
        message: action.message,
      };
  }
}

function cloneParticipant(participant: Participant): Participant {
  return {
    ...participant,
    requested: {
      ...participant.requested,
      controls: participant.requested.controls
        ? { ...participant.requested.controls }
        : undefined,
      executionProfile: participant.requested.executionProfile
        ? {
            profileId: participant.requested.executionProfile.profileId,
            values: { ...participant.requested.executionProfile.values },
          }
        : undefined,
    },
    effective: participant.effective
      ? {
          ...participant.effective,
          controls: participant.effective.controls
            ? Object.fromEntries(
                Object.entries(participant.effective.controls).map(
                  ([controlId, value]) => [controlId, { ...value }],
                ),
              )
            : undefined,
          executionProfile: participant.effective.executionProfile
            ? { ...participant.effective.executionProfile }
            : undefined,
        }
      : null,
  };
}

function copyRuntimeAssignment(
  targetSeat: Participant,
  source: Participant,
): Participant {
  const clonedSource = cloneParticipant(source);
  return {
    participantId: targetSeat.participantId,
    role: targetSeat.role,
    order: targetSeat.order,
    runtimeId: clonedSource.runtimeId,
    requested: clonedSource.requested,
    effective: clonedSource.effective,
  };
}

export function selectableRuntimeIds(catalog: CapabilityCatalog): RuntimeId[] {
  return Object.values(catalog)
    .filter((entry) => entry.availability.available)
    .map((entry) => entry.runtimeId)
    .sort((left, right) =>
      catalog[left].descriptor.display.name.localeCompare(
        catalog[right].descriptor.display.name,
      ),
    );
}

export function runtimeDisplayName(
  runtimeId: RuntimeId,
  catalog: CapabilityCatalog,
): string {
  return catalog[runtimeId]?.descriptor.display.name ?? runtimeId;
}

function cloneOption(option: CapabilityOption): CapabilityOption {
  return {
    ...option,
    availability: option.availability.available
      ? available
      : { ...option.availability },
  };
}

function findOption<T extends CapabilityOption>(
  options: readonly T[],
  id: string,
): T | undefined {
  return options.find((option) => option.id === id);
}

function notAdvertised(
  field: SelectionIssue["field"],
  id: string,
  context: string,
): SelectionIssue {
  return {
    field,
    code: "not-advertised",
    message: `${id} is not advertised for ${context}.`,
  };
}

function unavailable(
  field: SelectionIssue["field"],
  option: CapabilityOption,
): SelectionIssue {
  if (option.availability.available) {
    throw new Error("Expected an unavailable capability option.");
  }
  return {
    field,
    code: "unavailable",
    message: `${option.label} is unavailable: ${option.availability.reason}`,
  };
}

function validateNestedOption(
  issues: SelectionIssue[],
  field: "effort" | "serviceTier",
  requestedId: string,
  options: readonly CapabilityOption[],
  modelId: string,
): void {
  const option = findOption(options, requestedId);
  if (!option) {
    issues.push(notAdvertised(field, requestedId, modelId));
  } else if (!option.availability.available) {
    issues.push(unavailable(field, option));
  }
}

function validControlValue(control: ProviderControlDefinition, value: ControlScalar): boolean {
  if (control.kind === "boolean") return typeof value === "boolean";
  if (control.kind === "integer") {
    return typeof value === "number" && Number.isInteger(value) &&
      (control.minValue === null || value >= control.minValue) &&
      (control.maxValue === null || value <= control.maxValue);
  }
  if (control.kind === "status") return false;
  const option = control.options.find((candidate) => candidate.value === value);
  return Boolean(option?.availability.available);
}

function sameControlRecord(left: Record<string, ControlScalar>, right: Record<string, ControlScalar>): boolean {
  const leftEntries = Object.entries(left).sort(([a], [b]) => a.localeCompare(b));
  const rightEntries = Object.entries(right).sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify(leftEntries) === JSON.stringify(rightEntries);
}

function isPositiveInteger(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

export function reconcileParticipantConfiguration(current: ParticipantConfiguration, catalog: CapabilityCatalog): ParticipantConfiguration {
  // Catalog refresh must not change Live's runtime assignment or erase dormant choices.
  const reconcile = (participant: Participant): Participant => {
    const capabilities = catalog[participant.runtimeId];
    return capabilities?.availability.available
      ? { ...participant, requested: hydrateRequestedDefaults(participant.requested, capabilities) }
      : participant;
  };
  return { executor: reconcile(current.executor), auditors: current.auditors.map(reconcile) };
}
