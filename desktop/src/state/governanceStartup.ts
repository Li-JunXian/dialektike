export interface GovernanceCoreStatus {
  running: boolean;
}

interface GovernanceStartupDependencies<TStatus extends GovernanceCoreStatus> {
  initialize: () => Promise<TStatus>;
  isCurrent?: () => boolean;
  onReady: (status: TStatus) => void;
}

/**
 * Cross the protocol-ready boundary exactly once for a single boot attempt.
 * A process-running event is not sufficient: callers may load persisted data
 * only from `onReady`, after the initialize acknowledgement resolves.
 */
export async function initializeGovernanceCore<TStatus extends GovernanceCoreStatus>({
  initialize,
  isCurrent = () => true,
  onReady,
}: GovernanceStartupDependencies<TStatus>): Promise<TStatus> {
  const status = await initialize();
  if (!status.running) {
    throw new Error("The local governance core did not report a running state.");
  }
  if (isCurrent()) onReady(status);
  return status;
}
