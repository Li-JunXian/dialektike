import {
  ArrowDown,
  ArrowUp,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import type { ReactNode } from "react";

import {
  runtimeDisplayName,
  selectableRuntimeIds,
  type CapabilityCatalog,
  type ParticipantConfiguration,
  type RuntimeId,
  type SelectionIssue,
} from "../state/model";

interface ParticipantManagerProps {
  open: boolean;
  configuration: ParticipantConfiguration;
  catalog: CapabilityCatalog;
  rounds: number;
  disabled: boolean;
  refreshing: boolean;
  issues: SelectionIssue[];
  onClose: () => void;
  onRoundsChange: (rounds: number) => void;
  onRefresh: () => void;
  onRuntimeChange: (participantId: string, runtimeId: RuntimeId) => void;
  onAddAuditor: (runtimeId: RuntimeId) => void;
  onRemoveAuditor: (participantId: string) => void;
  onMoveAuditor: (participantId: string, direction: -1 | 1) => void;
}

export function ParticipantManager({
  open,
  configuration,
  catalog,
  rounds,
  disabled,
  refreshing,
  issues,
  onClose,
  onRoundsChange,
  onRefresh,
  onRuntimeChange,
  onAddAuditor,
  onRemoveAuditor,
  onMoveAuditor,
}: ParticipantManagerProps) {
  if (!open) {
    return null;
  }
  const occupied = new Set([
    configuration.executor.runtimeId,
    ...configuration.auditors.map((auditor) => auditor.runtimeId),
  ]);
  const runtimeIds = selectableRuntimeIds(catalog);
  const occupiedVendors = new Set(
    [...occupied].map((runtimeId) => catalog[runtimeId]?.descriptor.vendorId).filter(Boolean),
  );
  const addable = runtimeIds.filter((runtimeId) =>
    !occupied.has(runtimeId) && !occupiedVendors.has(catalog[runtimeId].descriptor.vendorId),
  );
  const connectable = Object.values(catalog)
    .filter((runtime) => !runtime.availability.available)
    .sort((left, right) => left.descriptor.display.name.localeCompare(right.descriptor.display.name));

  return (
    <div className="configuration-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <aside className="configuration-drawer" role="dialog" aria-modal="true" aria-labelledby="participants-title">
        <header className="configuration-drawer__header">
          <div>
            <p className="eyebrow">This topic</p>
            <h2 id="participants-title">Manage participants</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close participant configuration" onClick={onClose}>
            <X size={19} aria-hidden="true" />
          </button>
        </header>

        <div className="configuration-drawer__actions">
          <label className="round-field">
            <span>Review rounds</span>
            <input
              type="number"
              min="1"
              step="1"
              inputMode="numeric"
              value={rounds}
              disabled={disabled}
              onChange={(event) => onRoundsChange(Number(event.currentTarget.value))}
            />
          </label>
          <button className="button button--quiet" type="button" disabled={refreshing || disabled} onClick={onRefresh}>
            <RefreshCw size={14} aria-hidden="true" />
            {refreshing ? "Refreshing…" : "Refresh choices"}
          </button>
        </div>

        <p className="configuration-note">
          One Executor proposes and synthesizes. Auditors review independently in seat order. Every seat must use a different vendor.
        </p>

        <section className="manager-section" aria-labelledby="executor-manager-title">
          <header><span className="manager-dot manager-dot--executor" /><h3 id="executor-manager-title">Executor</h3></header>
          <ParticipantManagerRow
            title="Executor seat"
            runtimeId={configuration.executor.runtimeId}
            catalog={catalog}
            disabled={disabled}
            onRuntimeChange={(runtimeId) => onRuntimeChange(configuration.executor.participantId, runtimeId)}
          />
        </section>

        <section className="manager-section" aria-labelledby="auditor-manager-title">
          <header><span className="manager-dot manager-dot--auditor" /><h3 id="auditor-manager-title">Auditors</h3><small>{configuration.auditors.length}</small></header>
          <div className="manager-auditor-list">
            {configuration.auditors.map((auditor, index) => (
              <ParticipantManagerRow
                key={auditor.participantId}
                title={`Auditor ${index + 1}`}
                runtimeId={auditor.runtimeId}
                catalog={catalog}
                disabled={disabled}
                onRuntimeChange={(runtimeId) => onRuntimeChange(auditor.participantId, runtimeId)}
                actions={
                  <>
                    <button className="icon-button" type="button" aria-label={`Move Auditor ${index + 1} up`} disabled={disabled || index === 0} onClick={() => onMoveAuditor(auditor.participantId, -1)}><ArrowUp size={15} aria-hidden="true" /></button>
                    <button className="icon-button" type="button" aria-label={`Move Auditor ${index + 1} down`} disabled={disabled || index === configuration.auditors.length - 1} onClick={() => onMoveAuditor(auditor.participantId, 1)}><ArrowDown size={15} aria-hidden="true" /></button>
                    <button className="icon-button icon-button--danger" type="button" aria-label={`Remove Auditor ${index + 1}`} disabled={disabled} onClick={() => onRemoveAuditor(auditor.participantId)}><Trash2 size={15} aria-hidden="true" /></button>
                  </>
                }
              />
            ))}
          </div>
          <div className="manager-add-row">
            {addable.map((runtimeId) => (
              <button key={runtimeId} className="button button--secondary" type="button" disabled={disabled} onClick={() => onAddAuditor(runtimeId)}>
                <Plus size={14} aria-hidden="true" /> Add {runtimeDisplayName(runtimeId, catalog)}
              </button>
            ))}
            {addable.length === 0 ? (
              <div className="manager-connect-provider">
                <p>No additional authenticated vendor is available for this topic.</p>
                {connectable.length > 0 ? connectable.map((runtime) => (
                  <div key={runtime.runtimeId} className="manager-connect-provider__option">
                    <button
                      className="button button--quiet"
                      type="button"
                      data-connect-action={runtime.descriptor.connect.action}
                      disabled={refreshing || disabled}
                      onClick={onRefresh}
                    >
                      <Plus size={14} aria-hidden="true" /> {runtime.descriptor.connect.label}
                    </button>
                    <small>{runtime.descriptor.connect.helpText}</small>
                  </div>
                )) : (
                  <div className="manager-connect-provider__option">
                    <button className="button button--quiet" type="button" disabled={refreshing || disabled} onClick={onRefresh}>
                      <Plus size={14} aria-hidden="true" /> Connect another provider
                    </button>
                    <small>Install and authenticate an approved adapter, then refresh choices. Seats appear only after successful discovery.</small>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </section>

        {issues.length > 0 ? (
          <div className="validation-summary validation-summary--manager" role="status">
            <strong>Resolve before the next run</strong>
            <ul>{issues.map((issue, index) => <li key={`${issue.field}-${issue.code}-${index}`}>{issue.message}</li>)}</ul>
          </div>
        ) : null}
      </aside>
    </div>
  );
}

function ParticipantManagerRow({
  title,
  runtimeId,
  catalog,
  disabled,
  onRuntimeChange,
  actions,
}: {
  title: string;
  runtimeId: RuntimeId;
  catalog: CapabilityCatalog;
  disabled: boolean;
  onRuntimeChange: (runtimeId: RuntimeId) => void;
  actions?: ReactNode;
}) {
  return (
    <article className="manager-participant-row">
      <div>
        <strong>{title}</strong>
        <small>{runtimeDisplayName(runtimeId, catalog)} · {catalog[runtimeId]?.accountRoute || "Not verified"}</small>
      </div>
      <label>
        <span className="sr-only">Runtime for {title}</span>
        <select value={runtimeId} disabled={disabled} onChange={(event) => onRuntimeChange(event.currentTarget.value as RuntimeId)}>
          {Object.keys(catalog).map((id) => <option key={id} value={id} disabled={!catalog[id].availability.available}>{runtimeDisplayName(id, catalog)}</option>)}
        </select>
      </label>
      {actions ? <div className="manager-row-actions">{actions}</div> : null}
    </article>
  );
}
