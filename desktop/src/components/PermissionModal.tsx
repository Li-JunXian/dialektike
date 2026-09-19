import { ChevronDown, FilePenLine, ShieldCheck, Terminal } from "lucide-react";
import { useEffect, useRef } from "react";

import type { PermissionDecision, PermissionRequest } from "../protocol/messages";
import type { PermissionField, ProviderDescriptor } from "../state/model";

interface PermissionModalProps {
  request: PermissionRequest | null;
  descriptor?: ProviderDescriptor;
  queuedCount: number;
  submitting: boolean;
  error: string;
  onDecision: (decision: PermissionDecision) => void;
}

export function PermissionModal({ request, descriptor, queuedCount, submitting, error, onDecision }: PermissionModalProps) {
  const denyButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const surface = document.getElementById("application-surface");
    if (request) {
      surface?.setAttribute("inert", "");
      denyButton.current?.focus();
    }
    return () => surface?.removeAttribute("inert");
  }, [request]);

  if (!request) return null;
  const runtimeLabel = descriptor?.display.name ?? request.runtime_id;
  const presentation = descriptor?.permissionPresentations.find(
    (candidate) => candidate.requestKind === request.request_kind,
  );

  return (
    <div className="modal-backdrop">
      <section
        className="permission-modal permission-modal--native"
        data-accent={descriptor?.display.accentToken}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="permission-title"
        aria-describedby="permission-description"
      >
        <header className="permission-modal__header">
          <div className="trusted-channel"><ShieldCheck size={14} aria-hidden="true" />Trusted permission channel</div>
          <p className="permission-runtime">{runtimeLabel} is requesting permission</p>
          <h2 id="permission-title">{request.title}</h2>
          <p id="permission-description">This native request is isolated from model-authored conversation text.</p>
        </header>

        <NativePermission
          runtimeLabel={runtimeLabel}
          payload={request.native_payload}
          title={presentation?.title ?? request.title}
          layout={presentation?.layout ?? "native"}
          fields={presentation?.fields ?? []}
          card={request.card}
        />

        <details className="permission-details">
          <summary>Details <ChevronDown size={14} aria-hidden="true" /></summary>
          <section><h3>Verbatim relay card</h3><pre>{request.card}</pre></section>
          <section><h3>Full native payload</h3><pre>{JSON.stringify(request.native_payload, null, 2)}</pre></section>
          <section><h3>Trusted annotations</h3><pre>{JSON.stringify(request.annotations, null, 2)}</pre></section>
        </details>

        {queuedCount > 1 ? <p className="queue-note">{queuedCount - 1} additional permission {queuedCount - 1 === 1 ? "request is" : "requests are"} queued.</p> : null}
        {error ? <p className="form-error">{error}</p> : null}

        <footer>
          <button className="button button--secondary" type="button" ref={denyButton} disabled={submitting} onClick={() => onDecision("deny")}>Deny</button>
          <button className="button button--permission" type="button" disabled={submitting} onClick={() => onDecision("allow_once")}>{submitting ? "Recording…" : "Allow once"}</button>
        </footer>
      </section>
    </div>
  );
}

function NativePermission({
  runtimeLabel,
  payload,
  title,
  layout,
  fields,
  card,
}: {
  runtimeLabel: string;
  payload: Record<string, unknown>;
  title: string;
  layout: string;
  fields: PermissionField[];
  card: string;
}) {
  const presented = fields.flatMap((field) => {
    const value = jsonPointer(payload, field.pointer);
    return value === undefined ? [] : [{ field, value }];
  });
  const Icon = layout === "command" ? Terminal : FilePenLine;
  return (
    <section className={`native-permission native-permission--${layout}`} aria-label={`${runtimeLabel} native permission request`}>
      <header><Icon size={18} aria-hidden="true" /><div><span>{runtimeLabel}</span><strong>{title}</strong></div></header>
      {presented.length > 0 ? (
        <dl className="native-field-list">
          {presented.map(({ field, value }) => (
            <NativeField key={field.fieldId} label={field.label} value={formatNativeValue(value, field.format)} code={field.format === "code" || field.format === "json"} />
          ))}
        </dl>
      ) : <pre className="native-permission__verbatim"><code>{card}</code></pre>}
    </section>
  );
}

function NativeField({ label, value, code = false }: { label: string; value: string; code?: boolean }) {
  return <div><dt>{label}</dt><dd>{code ? <pre><code>{value}</code></pre> : value}</dd></div>;
}

function jsonPointer(payload: Record<string, unknown>, pointer: string): unknown {
  if (!pointer.startsWith("/")) return undefined;
  let current: unknown = payload;
  for (const encoded of pointer.slice(1).split("/")) {
    const key = encoded.replaceAll("~1", "/").replaceAll("~0", "~");
    if (Array.isArray(current)) {
      if (!/^(0|[1-9][0-9]*)$/.test(key)) return undefined;
      const index = Number(key);
      if (!Number.isSafeInteger(index) || index >= current.length) return undefined;
      current = current[index];
      continue;
    }
    if (typeof current !== "object" || current === null) return undefined;
    if (!Object.prototype.hasOwnProperty.call(current, key)) return undefined;
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}

function formatNativeValue(value: unknown, format: string): string {
  if (format === "code" && Array.isArray(value) && value.every((item) => typeof item === "string")) return value.join(" ");
  if (format === "json" || (typeof value === "object" && value !== null)) return JSON.stringify(value, null, 2);
  return String(value);
}
