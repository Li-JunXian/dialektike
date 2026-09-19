import {
  NATIVE_DEFAULT_SERVICE_TIER,
  ROLE_IDS,
  explicitModelOptions,
  runtimeDisplayName,
  selectableRuntimeIds,
  serviceTierOptions,
  type CapabilityCatalog,
  type CapabilityOption,
  type ModelCapability,
  type Participant,
  type RequestedSettings,
  type RoleId,
  type RuntimeId,
} from "../state/model";

interface ParticipantCardProps {
  participant: Participant;
  catalog: CapabilityCatalog;
  disabled: boolean;
  onRoleChange: (role: RoleId) => void;
  onRuntimeChange: (runtimeId: RuntimeId) => void;
  onRequestedChange: (
    field: keyof RequestedSettings,
    value: string,
  ) => void;
}

export function ParticipantCard({
  participant,
  catalog,
  disabled,
  onRoleChange,
  onRuntimeChange,
  onRequestedChange,
}: ParticipantCardProps) {
  const capabilities = catalog[participant.runtimeId];
  const models = withCurrentModel(
    explicitModelOptions(capabilities?.models ?? []),
    participant.requested.model,
    capabilities
      ? "This model is not advertised by the authenticated runtime."
      : "Waiting for authenticated runtime discovery.",
  );
  const selectedModel = models.find(
    (model) => model.id === participant.requested.model,
  );
  const efforts = withCurrentOption(
    selectedModel?.efforts ?? [],
    participant.requested.effort,
    selectedModel
      ? "This effort is not advertised for the selected model."
      : "Select an available model first.",
  );
  const tiers = withCurrentOption(
    serviceTierOptions(selectedModel?.serviceTiers ?? []),
    participant.requested.serviceTier,
    selectedModel
      ? "This native service tier is not advertised for the selected model."
      : "Select an available model first.",
  );
  const unavailable = [
    ...models,
    ...efforts,
    ...tiers,
  ].filter((option) => !option.availability.available);

  return (
    <article
      className={`participant-card participant-card--${participant.role}`}
      aria-labelledby={`${participant.role}-title`}
    >
      <header className="participant-card__header">
        <div>
          <p className="eyebrow">Participant</p>
          <h2 id={`${participant.role}-title`}>
            {roleLabel(participant.role)} —{" "}
            {runtimeDisplayName(participant.runtimeId, catalog)}
          </h2>
        </div>
        <span className="runtime-mark" aria-hidden="true">
          {capabilities?.descriptor.display.mark ?? "•"}
        </span>
      </header>

      <div className="control-grid">
        <SelectField
          id={`${participant.role}-role`}
          label="Role"
          value={participant.role}
          disabled={disabled}
          onChange={(value) => onRoleChange(value as RoleId)}
          options={ROLE_IDS.map((role) => ({
            id: role,
            label: roleLabel(role),
            disabled: false,
          }))}
        />
        <SelectField
          id={`${participant.role}-runtime`}
          label="Runtime"
          value={participant.runtimeId}
          disabled={disabled}
          onChange={(value) => onRuntimeChange(value as RuntimeId)}
          options={selectableRuntimeIds(catalog).map((runtimeId) => ({
            id: runtimeId,
            label: runtimeDisplayName(runtimeId, catalog),
            disabled: false,
          }))}
        />
        <SelectField
          id={`${participant.role}-model`}
          label="Model"
          value={participant.requested.model}
          disabled={disabled || !capabilities}
          onChange={(value) => onRequestedChange("model", value)}
          options={models.map(selectOption)}
        />
        <SelectField
          id={`${participant.role}-effort`}
          label="Effort"
          value={participant.requested.effort}
          disabled={disabled || !selectedModel}
          onChange={(value) => onRequestedChange("effort", value)}
          options={efforts.map(selectOption)}
        />
        <SelectField
          id={`${participant.role}-speed`}
          label="Speed"
          value={participant.requested.serviceTier}
          disabled={disabled || !selectedModel}
          onChange={(value) =>
            onRequestedChange("serviceTier", value)
          }
          options={tiers.map(selectOption)}
        />
      </div>

      <section className="settings-proof" aria-label="Settings evidence">
        <div>
          <span>Requested</span>
          <strong>
            {participant.requested.model} · {participant.requested.effort} ·{" "}
            {tierLabel(participant.requested.serviceTier)}
          </strong>
        </div>
        <div>
          <span>Runtime evidence</span>
          <div>
            <strong>
              {participant.effective
                ? `${participant.effective.model} · ${
                    participant.effective.effort ?? "effort not reported"
                  } · ${participant.effective.serviceTier ?? "native default"}`
                : "Awaiting runtime acknowledgement"}
            </strong>
            {participant.effective ? (
              <small>{participant.effective.authority}</small>
            ) : null}
          </div>
        </div>
      </section>

      <dl className="runtime-evidence">
        <div>
          <dt>Account route</dt>
          <dd>{capabilities?.accountRoute || "Not verified"}</dd>
        </div>
        <div>
          <dt>Runtime version</dt>
          <dd>{capabilities?.runtimeVersion || "Not verified"}</dd>
        </div>
      </dl>

      {unavailable.length > 0 ? (
        <details className="unavailable-options">
          <summary>Unavailable options and reasons</summary>
          <ul>
            {dedupeOptions(unavailable).map((option) => (
              <li key={`${option.id}-${option.label}`}>
                <strong>{option.label}:</strong>{" "}
                {option.availability.available
                  ? ""
                  : option.availability.reason}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </article>
  );
}

interface SelectFieldProps {
  id: string;
  label: string;
  value: string;
  disabled: boolean;
  options: Array<{ id: string; label: string; disabled: boolean }>;
  onChange: (value: string) => void;
}

function SelectField({
  id,
  label,
  value,
  disabled,
  options,
  onChange,
}: SelectFieldProps) {
  return (
    <label className="field" htmlFor={id}>
      <span>{label}</span>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value)}
      >
        {options.map((option) => (
          <option
            key={option.id}
            value={option.id}
            disabled={option.disabled}
          >
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function withCurrentModel(
  options: readonly ModelCapability[],
  current: string,
  reason: string,
): ModelCapability[] {
  if (options.some((option) => option.id === current)) {
    return options.map(cloneModel);
  }
  return [
    {
      id: current,
      label: current,
      availability: { available: false, reason },
      efforts: [],
      serviceTiers: [],
    },
    ...options.map(cloneModel),
  ];
}

function withCurrentOption(
  options: readonly CapabilityOption[],
  current: string,
  reason: string,
): CapabilityOption[] {
  if (options.some((option) => option.id === current)) {
    return options.map(cloneOption);
  }
  return [
    {
      id: current,
      label:
        current === NATIVE_DEFAULT_SERVICE_TIER
          ? "Native default"
          : current,
      availability: { available: false, reason },
    },
    ...options.map(cloneOption),
  ];
}

function cloneModel(model: ModelCapability): ModelCapability {
  return {
    ...model,
    availability: { ...model.availability },
    efforts: model.efforts.map(cloneOption),
    serviceTiers: model.serviceTiers.map(cloneOption),
  };
}

function cloneOption(option: CapabilityOption): CapabilityOption {
  return {
    ...option,
    availability: { ...option.availability },
  };
}

function selectOption(option: CapabilityOption) {
  return {
    id: option.id,
    label: option.availability.available
      ? option.label
      : `${option.label} — unavailable`,
    disabled: !option.availability.available,
  };
}

function dedupeOptions(
  options: CapabilityOption[],
): CapabilityOption[] {
  const seen = new Set<string>();
  return options.filter((option) => {
    const key = `${option.id}:${option.availability.available ? "" : option.availability.reason}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function roleLabel(role: RoleId): string {
  return role === "executor" ? "Executor" : "Auditor";
}

function tierLabel(tier: string): string {
  return tier === NATIVE_DEFAULT_SERVICE_TIER ? "Native default" : tier;
}
