import {
  CircleAlert,
  CircleStop,
  LoaderCircle,
  ShieldQuestion,
  TriangleAlert,
  X,
} from "lucide-react";

export type PersistentStatusTone = "running" | "paused" | "permission" | "warning" | "error";

export interface PersistentStatus {
  tone: PersistentStatusTone;
  message: string;
  actionLabel?: string;
}

interface RunStatusSurfaceProps {
  persistent: PersistentStatus | null;
  toast: string | null;
  onDismissPersistent?: () => void;
  onPersistentAction?: () => void;
  onDismissToast: () => void;
}

export function RunStatusSurface({
  persistent,
  toast,
  onDismissPersistent,
  onPersistentAction,
  onDismissToast,
}: RunStatusSurfaceProps) {
  return (
    <>
      {persistent ? (
        <section
          className={`run-status-banner run-status-banner--${persistent.tone}`}
          role={persistent.tone === "error" || persistent.tone === "warning" ? "alert" : "status"}
          aria-live={persistent.tone === "error" || persistent.tone === "warning" ? "assertive" : "polite"}
        >
          <StatusIcon tone={persistent.tone} />
          <span>{persistent.message}</span>
          <span className="run-status-banner__actions">
            {persistent.actionLabel && onPersistentAction ? (
              <button className="run-status-banner__action" type="button" onClick={onPersistentAction}>
                {persistent.actionLabel}
              </button>
            ) : null}
            {onDismissPersistent ? (
              <button type="button" aria-label="Dismiss status" onClick={onDismissPersistent}>
                <X size={14} aria-hidden="true" />
              </button>
            ) : null}
          </span>
        </section>
      ) : null}

      {toast ? (
        <section className="status-toast" role="status" aria-live="polite" aria-atomic="true">
          <span>{toast}</span>
          <button type="button" aria-label="Dismiss notification" onClick={onDismissToast}>
            <X size={14} aria-hidden="true" />
          </button>
        </section>
      ) : null}
    </>
  );
}

function StatusIcon({ tone }: { tone: PersistentStatusTone }) {
  if (tone === "permission") return <ShieldQuestion size={15} aria-hidden="true" />;
  if (tone === "paused") return <CircleStop size={15} aria-hidden="true" />;
  if (tone === "warning") return <TriangleAlert size={15} aria-hidden="true" />;
  if (tone === "error") return <CircleAlert size={15} aria-hidden="true" />;
  return <LoaderCircle className="run-status-banner__spinner" size={15} aria-hidden="true" />;
}
