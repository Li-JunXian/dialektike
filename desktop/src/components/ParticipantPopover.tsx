import {
  Check,
  ChevronLeft,
  ChevronRight,
  Search,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  NATIVE_DEFAULT_SERVICE_TIER,
  explicitModelOptions,
  serviceTierOptions,
  type CapabilityCatalog,
  type CapabilityOption,
  type ControlScalar,
  type ModelCapability,
  type Participant,
  type RequestedSettings,
} from "../state/model";

interface ParticipantPopoverProps {
  participant: Participant;
  catalog: CapabilityCatalog;
  anchor: DOMRect;
  disabled: boolean;
  onClose: () => void;
  onRequestedChange: (field: keyof RequestedSettings, value: string) => void;
  onControlChange: (controlId: string, value: ControlScalar) => void;
  onExecutionProfileChange: (profileId: string) => void;
  onReset: () => void;
}

type ChoicePanel = "model" | "effort" | "speed" | null;

export function ParticipantPopover({
  participant,
  catalog,
  anchor,
  disabled,
  onClose,
  onRequestedChange,
  onControlChange,
  onExecutionProfileChange,
  onReset,
}: ParticipantPopoverProps) {
  const [panel, setPanel] = useState<ChoicePanel>(null);
  const [query, setQuery] = useState("");
  const popover = useRef<HTMLDivElement>(null);
  const capabilities = catalog[participant.runtimeId];
  const model = capabilities?.models.find((candidate) => candidate.id === participant.requested.model);
  const efforts = model?.efforts ?? [];
  const tiers = serviceTierOptions(model?.serviceTiers ?? []);
  const left = Math.min(
    Math.max(12, anchor.left),
    Math.max(12, globalThis.innerWidth - 398),
  );
  const top = Math.min(anchor.bottom + 8, Math.max(12, globalThis.innerHeight - 520));

  useEffect(() => {
    const firstButton = popover.current?.querySelector<HTMLButtonElement>("button:not(:disabled)");
    firstButton?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const options = useMemo(() => {
    if (panel === "model") {
      return explicitModelOptions(capabilities?.models ?? []);
    }
    if (panel === "effort") {
      return efforts;
    }
    if (panel === "speed") {
      return tiers;
    }
    return [];
  }, [capabilities?.models, efforts, panel, tiers]);

  const filtered = options.filter((option) =>
    `${option.label} ${"description" in option ? option.description ?? "" : ""}`
      .toLocaleLowerCase()
      .includes(query.trim().toLocaleLowerCase()),
  );

  function choose(option: CapabilityOption) {
    if (!option.availability.available || !panel) {
      return;
    }
    onRequestedChange(panel === "speed" ? "serviceTier" : panel, option.id);
    setPanel(null);
    setQuery("");
  }

  return (
    <div className="popover-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target) {
        onClose();
      }
    }}>
      <div
        ref={popover}
        className="participant-popover"
        role="dialog"
        aria-modal="false"
        aria-label={`Configure ${capabilities?.descriptor.display.name ?? participant.runtimeId}`}
        style={{ left, top }}
      >
        {panel ? (
          <ChoiceList
            panel={panel}
            participant={participant}
            query={query}
            options={filtered}
            onQueryChange={setQuery}
            onBack={() => {
              setPanel(null);
              setQuery("");
            }}
            onChoose={choose}
          />
        ) : (
          <ProviderControls
            participant={participant}
            capabilities={capabilities}
            model={model}
            efforts={efforts}
            tiers={tiers}
            disabled={disabled}
            onPanel={setPanel}
            onReset={onReset}
            onControlChange={onControlChange}
            onExecutionProfileChange={onExecutionProfileChange}
            onClose={onClose}
          />
        )}

        {!panel ? (
          <details className="participant-popover__details">
            <summary>Details</summary>
            <ProviderEvidenceDetails participant={participant} capabilities={capabilities} />
            {capabilities?.descriptor.runtimeFacilities.length ? (
              <section className="participant-popover__facilities" aria-label="Runtime facilities">
                <strong>Runtime facilities</strong>
                <ul>
                  {capabilities.descriptor.runtimeFacilities.map((facility) => (
                    <li key={facility.facilityId}>
                      <span>{facility.label}</span>
                      <small>{facility.description}</small>
                      <small>{facility.observability} · {facility.management}</small>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </details>
        ) : null}
      </div>
    </div>
  );
}

function ProviderEvidenceDetails({
  participant,
  capabilities,
}: {
  participant: Participant;
  capabilities: CapabilityCatalog[string] | undefined;
}) {
  const descriptor = capabilities?.descriptor;
  const requestedProfile = descriptor?.executionProfiles.find(
    (profile) => profile.profileId === participant.requested.executionProfile?.profileId,
  );
  const effective = participant.effective;
  const controls = descriptor?.controlSchema.filter(
    (control) => control.group === "model" || control.group === "turn",
  ) ?? [];
  return (
    <dl>
      <div><dt>Account route</dt><dd>{capabilities?.accountRoute || descriptor?.authentication.notObservableLabel || "Not verified"}</dd></div>
      <div><dt>Runtime version</dt><dd>{capabilities?.runtimeVersion || descriptor?.versionEvidence.notObservableLabel || "Not verified"}</dd></div>
      <div><dt>Requested model</dt><dd>{participant.requested.model || "Not selected"}</dd></div>
      <div><dt>Effective model</dt><dd>{effective?.model || "Awaiting runtime acknowledgement"}</dd></div>
      <div><dt>Requested effort</dt><dd>{modelEffortLabel(participant, capabilities)}</dd></div>
      <div><dt>Effective effort</dt><dd>{effective ? effective.effort ?? "Not observable" : "Awaiting runtime acknowledgement"}</dd></div>
      <div><dt>Requested speed</dt><dd>{participant.requested.serviceTier}</dd></div>
      <div><dt>Effective speed</dt><dd>{effective ? effective.serviceTier ?? "Not observable" : "Awaiting runtime acknowledgement"}</dd></div>
      <div><dt>Requested mode</dt><dd>{requestedProfile?.label ?? participant.requested.executionProfile?.profileId ?? "Native default"}</dd></div>
      <div><dt>Effective mode</dt><dd>{effective?.executionProfile?.profileId ?? (effective ? "Not observable" : "Awaiting runtime acknowledgement")}</dd></div>
      {controls.map((control) => {
        const requestedValue = participant.requested.controls?.[control.controlId] ?? control.defaultValue;
        const observed = effective?.controls?.[control.controlId];
        return (
          <div key={control.controlId}>
            <dt>{control.label}</dt>
            <dd>
              Requested {formatControlValue(requestedValue)} · Effective {observed?.observable ? formatControlValue(observed.value) : "not observable"}
            </dd>
          </div>
        );
      })}
      {effective ? <div><dt>Effective authority</dt><dd>{effective.authority}</dd></div> : null}
    </dl>
  );
}

function formatControlValue(value: ControlScalar | null | undefined): string {
  if (value === null || value === undefined) return "native default";
  if (typeof value === "boolean") return value ? "on" : "off";
  return String(value);
}

function ProviderControls({
  participant,
  capabilities,
  model,
  efforts,
  tiers,
  disabled,
  onPanel,
  onReset,
  onControlChange,
  onExecutionProfileChange,
  onClose,
}: {
  participant: Participant;
  capabilities: CapabilityCatalog[string] | undefined;
  model?: ModelCapability;
  efforts: CapabilityOption[];
  tiers: CapabilityOption[];
  disabled: boolean;
  onPanel: (panel: ChoicePanel) => void;
  onReset: () => void;
  onControlChange: (controlId: string, value: ControlScalar) => void;
  onExecutionProfileChange: (profileId: string) => void;
  onClose: () => void;
}) {
  return (
    <>
      <PopoverTitle title={capabilities?.descriptor.display.name ?? participant.runtimeId} onClose={onClose} />
      <label className="participant-popover__filter">
        <Search size={14} aria-hidden="true" />
        <input aria-label="Filter actions" placeholder="Filter actions…" disabled />
      </label>
      <p className="provider-section-label">Model</p>
      <div className="provider-action-list">
        <ActionRow label="Switch model…" value={model?.label ?? (participant.requested.model || "Select model")} disabled={disabled} onClick={() => onPanel("model")} />
        <ActionRow
          label="Effort"
          value={!model ? "Select model first" : efforts.length === 0 ? "Not supported" : optionLabel(efforts, participant.requested.effort) || "Select effort"}
          disabled={disabled || !model || efforts.length === 0}
          onClick={() => onPanel("effort")}
        />
        <ActionRow label="Speed" value={optionLabel(tiers, participant.requested.serviceTier)} disabled={disabled} onClick={() => onPanel("speed")} />
      </div>
      {capabilities && capabilities.descriptor.executionProfiles.length > 0 ? (
        <div className="provider-declared-controls">
          <p className="provider-section-label">Execution</p>
          <label className="provider-control-field">
            <span>Mode</span>
            <select
              value={participant.requested.executionProfile?.profileId ?? capabilities.descriptor.defaultSelection.executionProfile}
              disabled={disabled}
              onChange={(event) => onExecutionProfileChange(event.currentTarget.value)}
            >
              {capabilities.descriptor.executionProfiles.map((profile) => (
                <option key={profile.profileId} value={profile.profileId} disabled={!profile.availability.available}>{profile.label}{profile.availability.available ? "" : " — unavailable"}</option>
              ))}
            </select>
          </label>
          {capabilities.descriptor.controlSchema.filter((control) => control.group === "model" || control.group === "turn").map((control) => (
            <DeclaredControl
              key={control.controlId}
              control={control}
              value={participant.requested.controls?.[control.controlId] ?? control.defaultValue}
              disabled={disabled}
              onChange={(value) => onControlChange(control.controlId, value)}
            />
          ))}
        </div>
      ) : null}
      <div className="provider-action-list">
        <button className="provider-reset" type="button" disabled={disabled} onClick={onReset}>
          <span>Clear selections</span>
        </button>
      </div>
    </>
  );
}

function DeclaredControl({
  control,
  value,
  disabled,
  onChange,
}: {
  control: NonNullable<CapabilityCatalog[string]>["descriptor"]["controlSchema"][number];
  value: ControlScalar | null;
  disabled: boolean;
  onChange: (value: ControlScalar) => void;
}) {
  if (control.kind === "status") {
    return <div className="provider-control-field"><span>{control.label}</span><output>{value === null ? "Not observable" : String(value)}</output></div>;
  }
  if (control.kind === "boolean") {
    return <label className="provider-control-field"><span>{control.label}</span><input type="checkbox" checked={value === true} disabled={disabled} onChange={(event) => onChange(event.currentTarget.checked)} /></label>;
  }
  if (control.kind === "integer") {
    return <label className="provider-control-field"><span>{control.label}</span><input type="number" min={control.minValue ?? undefined} max={control.maxValue ?? undefined} value={typeof value === "number" ? value : ""} disabled={disabled} onChange={(event) => onChange(Number(event.currentTarget.value))} /></label>;
  }
  return (
    <label className="provider-control-field" title={control.description}>
      <span>{control.label}</span>
      <select value={value === null ? "" : String(value)} disabled={disabled} onChange={(event) => onChange(control.options.find((option) => String(option.value) === event.currentTarget.value)?.value ?? event.currentTarget.value)}>
        {value === null ? <option value="">Native default</option> : null}
        {control.options.map((option) => <option key={String(option.value)} value={String(option.value)} disabled={!option.availability.available}>{option.label}{option.availability.available ? "" : " — unavailable"}</option>)}
      </select>
    </label>
  );
}

function PopoverTitle({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <header className="participant-popover__header">
      <strong>{title}</strong>
      <button className="icon-button" type="button" aria-label="Close participant settings" onClick={onClose}>
        <X size={16} aria-hidden="true" />
      </button>
    </header>
  );
}

function ActionRow({
  label,
  value,
  disabled,
  onClick,
}: {
  label: string;
  value?: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button className="provider-action" type="button" disabled={disabled} onClick={onClick}>
      <span>{label}</span>
      <span className="provider-action__value">{value}<ChevronRight size={15} aria-hidden="true" /></span>
    </button>
  );
}

function ChoiceList({
  panel,
  participant,
  query,
  options,
  onQueryChange,
  onBack,
  onChoose,
}: {
  panel: Exclude<ChoicePanel, null>;
  participant: Participant;
  query: string;
  options: Array<CapabilityOption | ModelCapability>;
  onQueryChange: (value: string) => void;
  onBack: () => void;
  onChoose: (option: CapabilityOption) => void;
}) {
  const selected = panel === "model" ? participant.requested.model : panel === "effort" ? participant.requested.effort : participant.requested.serviceTier;
  return (
    <>
      <header className="choice-list__header">
        <button className="icon-button" type="button" aria-label="Back to participant settings" onClick={onBack}><ChevronLeft size={17} aria-hidden="true" /></button>
        <strong>{panel === "model" ? "Select a model" : panel === "effort" ? "Select effort" : "Select speed"}</strong>
      </header>
      {options.length > 5 ? (
        <label className="participant-popover__filter">
          <Search size={14} aria-hidden="true" />
          <input autoFocus value={query} placeholder="Filter choices…" aria-label="Filter choices" onChange={(event) => onQueryChange(event.currentTarget.value)} />
        </label>
      ) : null}
      <div className="choice-list" role="listbox">
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            role="option"
            aria-selected={selected === option.id}
            className="choice-option"
            disabled={!option.availability.available}
            title={option.availability.available ? undefined : option.availability.reason}
            onClick={() => onChoose(option)}
          >
            <span>
              <strong>{option.label}</strong>
              {"description" in option && option.description ? <small>{option.description}</small> : null}
              {!option.availability.available ? <small>{option.availability.reason}</small> : null}
            </span>
            {selected === option.id ? <Check size={16} aria-hidden="true" /> : null}
          </button>
        ))}
        {options.length === 0 ? <p className="choice-list__empty">No choice is advertised by this runtime.</p> : null}
      </div>
    </>
  );
}

function optionLabel(options: CapabilityOption[], id: string): string {
  return options.find((option) => option.id === id)?.label ?? id;
}

function modelEffortLabel(
  participant: Participant,
  capabilities: CapabilityCatalog[string] | undefined,
): string {
  const model = capabilities?.models.find(
    (candidate) => candidate.id === participant.requested.model,
  );
  if (!model) return "Not selected";
  if (model.efforts.length === 0) return "Not supported by this model";
  return participant.requested.effort || "Not selected";
}
