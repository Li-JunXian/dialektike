import type { ReactNode } from "react";

import type { EvidenceSummary, RuntimeGateEvidence } from "../protocol/messages";

interface EvidencePanelProps {
  evidence: EvidenceSummary | null;
  runtimeNames?: Record<string, string>;
  source?: "current-run" | "saved-topic" | "loading" | "unavailable";
  unavailableMessage?: string;
}

export function EvidencePanel({ evidence, runtimeNames = {}, source = evidence ? "current-run" : "unavailable", unavailableMessage }: EvidencePanelProps) {
  const sourceCopy = evidence
    ? source === "saved-topic"
      ? "Loaded from the latest saved closed run for this topic."
      : "Received when the latest run closed in this app session."
    : source === "loading"
      ? "Loading the latest saved closed-run evidence for this topic…"
      : unavailableMessage || "No latest closed-run evidence is available for this topic yet.";
  return (
    <section className="evidence-panel panel" aria-labelledby="evidence-title">
      <header className="section-header">
        <div>
          <p className="eyebrow">Bounded, read-only projection</p>
          <h2 id="evidence-title">Latest run evidence</h2>
        </div>
        {evidence ? (
          <span className="evidence-status">
            Run {evidence.run_status}
          </span>
        ) : null}
      </header>

      <p className="evidence-source">{sourceCopy} Original owner-only evidence remains unchanged.</p>

      {!evidence ? (
        <div className="evidence-empty">
          {source === "loading"
            ? "Please wait while saved evidence is checked."
            : "Gate, rate-limit, permission, capture, and chain evidence will appear here after a run closes. Raw contents remain owner-only."}
        </div>
      ) : (
        <div className="evidence-grid">
          <EvidenceSection title="Runtime and account gates">
            <article className="environment-gate">
              <strong>
                Environment scrub:{" "}
                {evidence.environment_gate.verified
                  ? "verified"
                  : "not evidenced"}
              </strong>
              <span>
                Policy: {evidence.environment_gate.policy ?? "unknown"}
              </span>
              <span>
                Kept names:{" "}
                {evidence.environment_gate.kept.join(", ") || "not recorded"}
              </span>
              <span>
                Dropped names:{" "}
                {evidence.environment_gate.dropped_count ?? "not recorded"}
              </span>
            </article>
            <div className="gate-grid">
              {evidence.runtime_gates.map((gate) => (
                <GateEvidence key={gate.runtime_id} gate={gate} runtimeNames={runtimeNames} />
              ))}
            </div>
          </EvidenceSection>

          <EvidenceSection title="Rate-limit observations">
            <dl className="evidence-metrics">
              <Metric
                label="Events captured"
                value={evidence.rate_limits.observed_event_count}
              />
              <Metric
                label="Plan warnings"
                value={evidence.rate_limits.warning_count}
              />
              <Metric
                label="Capture parse faults"
                value={evidence.rate_limits.capture_parse_failures}
              />
            </dl>
            {Object.keys(evidence.rate_limits.by_runtime).length ? (
              <p className="evidence-detail">
                {Object.entries(evidence.rate_limits.by_runtime)
                  .map(
                    ([runtime, count]) =>
                      `${runtimeLabel(runtime, runtimeNames)}: ${count}`,
                  )
                  .join(" · ")}
              </p>
            ) : null}
            {evidence.rate_limits.warnings.length ? (
              <ul className="evidence-warnings">
                {evidence.rate_limits.warnings.map((warning, index) => (
                  <li key={`${warning.runtime_id}-${index}`}>
                    <strong>{runtimeLabel(warning.runtime_id, runtimeNames)}:</strong>{" "}
                    {warning.message}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="evidence-detail">No plan warning was recorded.</p>
            )}
          </EvidenceSection>

          <EvidenceSection title="Permissions and audit">
            {evidence.governance.derived_from_verified_chain &&
            evidence.governance.permission_decisions &&
            evidence.governance.audit_counts ? (
              <>
                <dl className="evidence-metrics">
                  <Metric
                    label="Permission decisions"
                    value={evidence.governance.permission_decisions.total}
                  />
                  <Metric
                    label="Allowed once"
                    value={evidence.governance.permission_decisions.allow}
                  />
                  <Metric
                    label="Denied"
                    value={evidence.governance.permission_decisions.deny}
                  />
                </dl>
                <CountList
                  counts={evidence.governance.audit_counts}
                  empty="No audit records were written."
                />
              </>
            ) : (
              <p className="evidence-failure">
                Counts withheld because the decision chain did not verify.
              </p>
            )}
          </EvidenceSection>

          <EvidenceSection title="Owner-only raw capture">
            <dl className="evidence-metrics">
              <Metric
                label="Files"
                value={evidence.raw_capture.file_count}
              />
              <Metric
                label="Turns captured"
                value={evidence.raw_capture.turns_with_capture}
              />
              <Metric
                label="Bytes"
                value={evidence.raw_capture.total_bytes}
              />
            </dl>
            <CountList
              counts={evidence.raw_capture.by_category}
              empty="No raw capture file was written."
            />
            <p className="evidence-detail">
              Inventory only. No filename, path, credential, or raw payload
              content is exposed to this view.
            </p>
          </EvidenceSection>

          <EvidenceSection title="Hash-chain verification">
            <p
              className={
                evidence.decision_chain.verified
                  ? "evidence-chain evidence-chain--verified"
                  : "evidence-chain evidence-chain--failed"
              }
            >
              {evidence.decision_chain.verified
                ? `${evidence.decision_chain.record_count} decision records verified`
                : evidence.decision_chain.error}
            </p>
            {evidence.decision_chain.head_sha256 ? (
              <code className="chain-head">
                {evidence.decision_chain.head_sha256}
              </code>
            ) : (
              <p className="evidence-detail">
                {evidence.decision_chain.verified
                  ? "Empty chain; no head hash yet."
                  : "No chain-derived evidence is displayed."}
              </p>
            )}
            <p className="evidence-detail">
              Event log readable: {evidence.event_log_readable ? "yes" : "no"}
            </p>
          </EvidenceSection>
        </div>
      )}
    </section>
  );
}

function EvidenceSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="evidence-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function GateEvidence({ gate, runtimeNames }: { gate: RuntimeGateEvidence; runtimeNames: Record<string, string> }) {
  return (
    <article className="gate-evidence">
      <strong>{runtimeLabel(gate.runtime_id, runtimeNames)}</strong>
      <span>
        Catalog gate: {gate.catalog_verified ? "verified" : "not verified"}
      </span>
      <span>Account: {gate.account_route}</span>
      <span>Runtime: {gate.runtime_version ?? "not evidenced"}</span>
      <span>
        Native provider:{" "}
        {gate.model_providers.join(", ") || "not separately echoed"}
      </span>
      <span>Turn revalidations: {gate.turn_revalidated_count}</span>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value.toLocaleString()}</dd>
    </div>
  );
}

function CountList({
  counts,
  empty,
}: {
  counts: Record<string, number>;
  empty: string;
}) {
  const entries = Object.entries(counts);
  return entries.length ? (
    <ul className="evidence-counts">
      {entries.map(([kind, count]) => (
        <li key={kind}>
          <span>{humanize(kind)}</span>
          <strong>{count}</strong>
        </li>
      ))}
    </ul>
  ) : (
    <p className="evidence-detail">{empty}</p>
  );
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function runtimeLabel(runtimeId: string, runtimeNames: Record<string, string>): string {
  return runtimeNames[runtimeId] ?? runtimeId;
}
