import { ArrowLeftRight, ChevronDown, LockKeyhole, Plus, Settings2 } from "lucide-react";

import type { ActivityStatus } from "../protocol/messages";
import type { RuntimeId } from "../state/model";

export interface SeatSummary {
  id: string;
  runtimeId: RuntimeId;
  agentSystem: string;
  modelLine: string;
  activity?: {
    status: ActivityStatus;
    label: string;
    nativeSummary?: string;
  };
}

interface WorkspaceHeaderProps {
  executor: SeatSummary;
  auditors: SeatSummary[];
  activeRun: boolean;
  onSeatClick: (seatId: string, anchor: DOMRect) => void;
  onManageParticipants: () => void;
  onAddAuditor: () => void;
  onSwapRoles: (auditorId: string) => void;
}

export function WorkspaceHeader({
  executor,
  auditors,
  activeRun,
  onSeatClick,
  onManageParticipants,
  onAddAuditor,
  onSwapRoles,
}: WorkspaceHeaderProps) {
  return (
    <header className="workspace-header">
      <div className="seat-map">
        <section className="seat-group seat-group--executor">
          <div className="seat-group__heading">
            <span className="seat-group__label">Selected speaker · Executor</span>
          </div>
          <SeatButton seat={executor} tone="executor" disabled={activeRun} onClick={onSeatClick} />
        </section>

        <div className="live-seat" data-geometry="live-seat" aria-label="Live, the human arbiter">
          <span className="live-seat__ring" aria-hidden="true" />
          <span>Live</span>
          <SwapRolesControl
            auditors={auditors}
            disabled={activeRun}
            onSwapRoles={onSwapRoles}
          />
        </div>

        <section className="seat-group seat-group--auditors">
          <div className="seat-group__heading">
            <span className="seat-group__label">
              Optional reviewers · Auditors <span>· {auditors.length}</span>
            </span>
            <div className="seat-group__actions">
              <button
                className="add-auditor-button"
                type="button"
                onClick={onAddAuditor}
                disabled={activeRun}
              >
                <Plus size={13} aria-hidden="true" />
                <span>Add Auditor</span>
              </button>
              <button
                className="configuration-button"
                type="button"
                onClick={onManageParticipants}
                disabled={activeRun}
                aria-label={activeRun ? "Participant settings are locked during this run" : "Manage participants"}
              >
                {activeRun ? <LockKeyhole size={13} aria-hidden="true" /> : <Settings2 size={13} aria-hidden="true" />}
                <span>{activeRun ? "Locked" : "Manage"}</span>
              </button>
            </div>
          </div>
          <div className="auditor-seat-list">
            {auditors.map((auditor) => (
              <SeatButton key={auditor.id} seat={auditor} tone="auditor" disabled={activeRun} onClick={onSeatClick} />
            ))}
          </div>
        </section>
      </div>
    </header>
  );
}

function SwapRolesControl({
  auditors,
  disabled,
  onSwapRoles,
}: {
  auditors: SeatSummary[];
  disabled: boolean;
  onSwapRoles: (auditorId: string) => void;
}) {
  if (auditors.length === 0) return null;
  if (auditors.length === 1) {
    return (
      <button
        className="swap-roles-button"
        type="button"
        disabled={disabled}
        onClick={() => onSwapRoles(auditors[0].id)}
        aria-label={`Swap Executor with Auditor ${auditors[0].agentSystem}`}
        title={`Swap Executor with ${auditors[0].agentSystem}`}
      >
        <ArrowLeftRight size={13} aria-hidden="true" />
        <span>Swap</span>
      </button>
    );
  }

  return (
    <details className="swap-roles-menu">
      <summary
        className="swap-roles-button"
        aria-label="Choose an Auditor to swap with the Executor"
        aria-disabled={disabled}
        onClick={(event) => {
          if (disabled) event.preventDefault();
        }}
      >
        <ArrowLeftRight size={13} aria-hidden="true" />
        <span>Swap</span>
      </summary>
      <div className="swap-roles-menu__choices" role="menu">
        {auditors.map((auditor) => (
          <button
            key={auditor.id}
            type="button"
            role="menuitem"
            disabled={disabled}
            onClick={(event) => {
              onSwapRoles(auditor.id);
              event.currentTarget.closest("details")?.removeAttribute("open");
            }}
          >
            Swap with {auditor.agentSystem}
            <small>{auditor.modelLine}</small>
          </button>
        ))}
      </div>
    </details>
  );
}

function SeatButton({
  seat,
  tone,
  disabled,
  onClick,
}: {
  seat: SeatSummary;
  tone: "executor" | "auditor";
  disabled: boolean;
  onClick: (seatId: string, anchor: DOMRect) => void;
}) {
  const activity = seat.activity;
  return (
    <button
      className={`seat-button seat-button--${tone}`}
      type="button"
      disabled={disabled}
      onClick={(event) => onClick(seat.id, event.currentTarget.getBoundingClientRect())}
      aria-label={`Configure ${tone}: ${seat.agentSystem}, ${seat.modelLine}`}
      aria-haspopup="dialog"
    >
      <span className="seat-button__dot" aria-hidden="true" />
      <span className="seat-button__copy">
        <strong>{seat.agentSystem}</strong>
        <small>{seat.modelLine}</small>
        {activity ? (
          <span className={`seat-activity seat-activity--${activity.status}`}>
            {activity.label}
            {activity.nativeSummary ? <small>{activity.nativeSummary}</small> : null}
          </span>
        ) : null}
      </span>
      <ChevronDown size={14} aria-hidden="true" />
    </button>
  );
}
