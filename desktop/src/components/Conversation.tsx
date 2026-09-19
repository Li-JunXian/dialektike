import { AlertTriangle, CheckCircle2, LoaderCircle, RefreshCw, SkipForward } from "lucide-react";

import type {
  ConversationMessage,
  LivePromptMessage,
  ParticipantActivity,
  PausedAuditFailure,
} from "../protocol/messages";
import { ModelMarkdown } from "./ModelMarkdown";
import { StructuredContent } from "./StructuredContent";

interface ConversationProps {
  /** Backward-compatible single-prompt rendering for older saved M2 records. */
  livePrompt?: string;
  prompts?: LivePromptMessage[];
  messages: ConversationMessage[];
  /** Immutable runtime display names keyed by runtime_id for saved turns. */
  runtimeDisplayNames?: Record<string, string>;
  /** Current seat labels keyed by participant_id for live activity/failures. */
  runtimeNames?: Record<string, string>;
  auditOrder?: string[];
  activities?: ParticipantActivity[];
  pausedAudit?: PausedAuditFailure | null;
  resolvingAudit?: boolean;
  onReview?: (message: ConversationMessage) => void;
  reviewDisabled?: boolean;
  reviewUnavailableReason?: string;
  onResolveAudit?: (resolution: "retry_failed" | "continue_without_failed") => void;
}

interface DialogueRound {
  round: number;
  proposal: ConversationMessage | null;
  audits: ConversationMessage[];
  followups: ConversationMessage[];
}

interface DialogueCycle {
  cycle: number;
  prompt: LivePromptMessage | null;
  rounds: DialogueRound[];
}

export function Conversation({
  livePrompt = "",
  prompts = [],
  messages,
  runtimeDisplayNames = {},
  runtimeNames = {},
  auditOrder = [],
  activities = [],
  pausedAudit = null,
  resolvingAudit = false,
  onResolveAudit,
  onReview,
  reviewDisabled = false,
  reviewUnavailableReason,
}: ConversationProps) {
  const normalizedPrompts =
    prompts.length > 0
      ? prompts
      : livePrompt
        ? [{ id: "legacy-live-prompt", text: livePrompt, cycle: 1 }]
        : [];
  const cycles = buildCycles(normalizedPrompts, messages, auditOrder, activities);

  return (
    <section className="conversation-feed" aria-label="Conversation" role="log" aria-live="polite" aria-relevant="additions" aria-atomic="false">
      {cycles.length === 0 ? (
        <div className="conversation-empty">
          <p>Send a message to your selected speaker. Review an answer when you choose.</p>
        </div>
      ) : (
        cycles.map((cycle) => (
          <section className="conversation-cycle" key={cycle.cycle} aria-label={`Conversation cycle ${cycle.cycle}`}>
            {cycle.prompt ? <LivePrompt prompt={cycle.prompt} /> : null}
            {cycle.rounds.map((round) => {
              const roundActivities = activities.filter(
                (activity) => activity.cycle === cycle.cycle && activity.round === round.round,
              );
              const proposalActivity = roundActivities.find((activity) => activity.stage === "proposal" || activity.stage === "answer");
              const synthesisActivity = roundActivities.find((activity) => activity.stage === "synthesis");
              const auditActivities = roundActivities
                .filter((activity) => activity.stage === "audit")
                .sort((left, right) => auditSeatIndex(left.participant_id, auditOrder) - auditSeatIndex(right.participant_id, auditOrder));
              const relevantFailure = pausedAudit?.cycle === cycle.cycle && pausedAudit.round === round.round ? pausedAudit : null;
              return (
                <section className="dialogue-cycle" key={`${cycle.cycle}:${round.round}`} aria-label={round.proposal?.stage === "answer" || proposalActivity?.stage === "answer" ? "Answer" : `Review round ${round.round}`}>
                  <div className="exchange-grid" data-geometry="exchange-grid">
                    <div className="executor-lane" data-geometry="executor-lane">
                      {round.proposal ? (
                        <TurnMessage onReview={onReview} reviewDisabled={reviewDisabled} reviewUnavailableReason={reviewUnavailableReason} message={round.proposal} runtimeName={runtimeDisplayNames[round.proposal.runtime_id]} />
                      ) : proposalActivity ? (
                        <ParticipantProgress activity={proposalActivity} runtimeName={runtimeNames[proposalActivity.participant_id]} />
                      ) : null}
                    </div>

                    <div className="auditor-lane" data-geometry="auditor-lane">
                      {round.audits.map((audit) => (
                        <TurnMessage key={audit.id} message={audit} runtimeName={runtimeDisplayNames[audit.runtime_id]} />
                      ))}
                      {auditActivities
                        .filter((activity) => !round.audits.some((audit) => audit.participant_id === activity.participant_id))
                        .map((activity) => (
                          <ParticipantProgress key={activity.participant_id} activity={activity} runtimeName={runtimeNames[activity.participant_id]} />
                        ))}
                      {relevantFailure && onResolveAudit ? (
                        <AuditFailureControls failure={relevantFailure} disabled={resolvingAudit} runtimeNames={runtimeNames} onResolve={onResolveAudit} />
                      ) : null}
                    </div>

                    {round.followups.length > 0 || synthesisActivity ? (
                      <div className="executor-followup-lane">
                        {round.followups.map((followup) => (
                          <TurnMessage onReview={onReview} reviewDisabled={reviewDisabled} reviewUnavailableReason={reviewUnavailableReason} key={followup.id} message={followup} runtimeName={runtimeDisplayNames[followup.runtime_id]} />
                        ))}
                        {round.followups.length === 0 && synthesisActivity ? (
                          <ParticipantProgress activity={synthesisActivity} runtimeName={runtimeNames[synthesisActivity.participant_id]} />
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </section>
              );
            })}
          </section>
        ))
      )}
    </section>
  );
}

function LivePrompt({ prompt }: { prompt: LivePromptMessage }) {
  return (
    <article className="live-prompt" data-geometry="live-prompt" data-source-anchor={prompt.id} tabIndex={-1}>
      <header>Live</header>
      <div><ModelMarkdown text={prompt.text} /></div>
    </article>
  );
}

function TurnMessage({ message, runtimeName, onReview, reviewDisabled, reviewUnavailableReason }: {
  message: ConversationMessage; runtimeName?: string;
  onReview?: (message: ConversationMessage) => void;
  reviewDisabled?: boolean; reviewUnavailableReason?: string;
}) {
  const stage = normalizedStage(message);
  const verdict = stage === "audit" ? message.verdict ?? verdictFromText(message.text) : null;
  const label = stage === "audit" && verdict ? `AUDIT · ${verdictLabel(verdict)}` : stage.toLocaleUpperCase();
  const modelEvidence = message.effective?.model;
  const effortEvidence = message.effective?.effort;
  const historicalLabel = [runtimeName ?? message.runtime_id, modelEvidence, effortEvidence]
    .filter((value): value is string => Boolean(value))
    .join(" · ");

  return (
    <article className={`turn-message turn-message--${message.role} turn-message--${stage}`} data-message-stage={stage} data-source-anchor={message.id} tabIndex={-1}>
      <span className="turn-rail" aria-hidden="true"><span className="turn-rail__dot" /><span className="turn-rail__line" /></span>
      <div className="turn-message__body">
        <header className="turn-message__header">
          <span className="turn-stage">{label}</span>
          <span className="turn-model">{historicalLabel}</span>
        </header>
        <StructuredContent fallbackText={message.text} blocks={message.blocks} />
        <footer className="turn-message__footer">
          {onReview && reviewTargetForMessage(message) ? <button type="button" className="button button--quiet" disabled={reviewDisabled} title={reviewUnavailableReason || "Review this saved answer"} onClick={() => onReview(message)}>Review</button> : null}
          <span>{formatTime(message.created_at)}</span><span aria-hidden="true">·</span>
          <span>{message.token_count !== undefined ? `${message.token_count.toLocaleString()} tokens` : `Round ${message.round}`}</span>
          {message.effective ? (
            <><span aria-hidden="true">·</span><span title={message.effective.authority}>Effective {message.effective.model}</span><span className="sr-only">Runtime evidence: {message.effective.model}. Authority: {message.effective.authority}</span></>
          ) : null}
        </footer>
      </div>
    </article>
  );
}

function ParticipantProgress({ activity, runtimeName }: { activity: ParticipantActivity; runtimeName?: string }) {
  const label = deterministicActivityLabel(activity, runtimeName);
  return (
    <article className={`participant-progress participant-progress--${activity.stage === "audit" ? "auditor" : "executor"} participant-progress--${activity.status}`} role="status">
      {activity.status === "completed" ? <CheckCircle2 size={15} aria-hidden="true" /> : <LoaderCircle className="participant-progress__spinner" size={15} aria-hidden="true" />}
      <div><strong>{label}</strong>{activity.native_summary ? <p>{activity.native_summary}</p> : null}</div>
    </article>
  );
}

function AuditFailureControls({
  failure,
  disabled,
  runtimeNames,
  onResolve,
}: {
  failure: PausedAuditFailure;
  disabled: boolean;
  runtimeNames: Record<string, string>;
  onResolve: (resolution: "retry_failed" | "continue_without_failed") => void;
}) {
  return (
    <section className="audit-failure" role="alert">
      <header><AlertTriangle size={16} aria-hidden="true" /><strong>Audit paused</strong></header>
      {failure.failed.map((item) => <p key={item.participant_id}><strong>{runtimeNames[item.participant_id] ?? item.runtime_id}</strong>: {item.message}</p>)}
      <div>
        <button type="button" className="button button--secondary" disabled={disabled} onClick={() => onResolve("retry_failed")}><RefreshCw size={14} aria-hidden="true" />Retry auditor</button>
        <button type="button" className="button button--quiet" disabled={disabled} onClick={() => onResolve("continue_without_failed")}><SkipForward size={14} aria-hidden="true" />Continue without this audit</button>
      </div>
    </section>
  );
}

function buildCycles(prompts: LivePromptMessage[], messages: ConversationMessage[], auditOrder: string[], activities: ParticipantActivity[]): DialogueCycle[] {
  const cycleNumbers = new Set<number>([
    ...prompts.map((prompt) => prompt.cycle),
    ...messages.map((message) => message.cycle ?? 1),
    ...activities.map((activity) => activity.cycle),
  ]);
  return [...cycleNumbers].sort((a, b) => a - b).map((cycle) => {
    const cycleMessages = messages.filter((message) => (message.cycle ?? 1) === cycle);
    const rounds = new Map<number, ConversationMessage[]>();
    for (const activity of activities.filter((item) => item.cycle === cycle)) rounds.set(activity.round, []);
    for (const message of cycleMessages) {
      const current = rounds.get(message.round) ?? [];
      current.push(message);
      rounds.set(message.round, current);
    }
    const dialogueRounds = [...rounds.entries()].sort(([left], [right]) => left - right).map(([round, roundMessages]) => {
      const executorMessages = roundMessages.filter((message) => message.role === "executor" || message.stage === "answer");
      const explicitProposal = executorMessages.find((message) => message.stage === "proposal" || message.stage === "answer");
      const proposal = explicitProposal ?? executorMessages.find((message) => message.stage === undefined) ?? null;
      const audits = roundMessages
        .filter((message) => message.stage === "audit" || (message.role === "auditor" && message.stage === undefined))
        .sort((left, right) => auditSeatIndex(left.participant_id, auditOrder) - auditSeatIndex(right.participant_id, auditOrder));
      const followups = executorMessages.filter((message) => message.id !== proposal?.id && (message.stage === "rebuttal" || message.stage === "synthesis" || message.stage === undefined));
      return { round, proposal, audits, followups };
    });
    return { cycle, prompt: prompts.find((prompt) => prompt.cycle === cycle) ?? null, rounds: dialogueRounds };
  });
}

function auditSeatIndex(participantId: string | undefined, order: string[]): number {
  const index = participantId ? order.indexOf(participantId) : -1;
  return index < 0 ? Number.MAX_SAFE_INTEGER : index;
}

function normalizedStage(message: ConversationMessage): NonNullable<ConversationMessage["stage"]> {
  if (message.stage) return message.stage;
  return message.role === "auditor" ? "audit" : "proposal";
}

function verdictFromText(text: string): NonNullable<ConversationMessage["verdict"]> | null {
  const normalized = text.trimStart().toLocaleUpperCase();
  if (normalized.startsWith("ACCEPT")) return "accept";
  if (normalized.startsWith("CHALLENGE")) return "challenge";
  if (normalized.startsWith("INSUFFICIENT EVIDENCE")) return "insufficient-evidence";
  return null;
}

function verdictLabel(verdict: NonNullable<ConversationMessage["verdict"]>): string {
  return verdict === "insufficient-evidence" ? "INSUFFICIENT EVIDENCE" : verdict.toLocaleUpperCase();
}

function formatTime(value?: string): string {
  if (!value) return "Saved";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);
}

function deterministicActivityLabel(activity: ParticipantActivity, runtimeName?: string): string {
  const runtime = runtimeName ?? activity.runtime_id;
  if (activity.status === "paused") return `${runtime} is paused`;
  if (activity.status === "failed") return `${runtime} could not complete the ${activity.stage}`;
  if (activity.status === "completed") return `${runtime} completed the ${activity.stage}`;
  if (activity.stage === "answer") return `${runtime} is answering…`;
  if (activity.stage === "proposal") return `${runtime} is proposing…`;
  if (activity.stage === "audit") return `${runtime} is reviewing…`;
  return `${runtime} is synthesizing…`;
}

/** Targets contain saved identifiers only; answer text is resolved by the backend. */
export function reviewTargetForMessage(message: ConversationMessage): { cycle_id: string; message_id: string } | null {
  if (message.partial || !["answer", "proposal", "synthesis"].includes(message.stage ?? "")) return null;
  const cycleId = message.cycle_id ?? /^(.*):[0-9]+$/.exec(message.id)?.[1];
  return cycleId ? { cycle_id: cycleId, message_id: message.id } : null;
}
