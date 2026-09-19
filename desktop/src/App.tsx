import { buildRunInput } from "./state/runIntent";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { ArrowUp, ChevronDown, Minimize2, ShieldCheck, Square } from "lucide-react";

import {
  createTopic as createTopicBridge,
  approveTopicCheckpoint,
  deactivateTopicCheckpoint,
  draftTopicCheckpoint,
  deleteTopic as deleteTopicBridge,
  discoverCapabilities,
  getAccessibilityDisplayState,
  getWindowAppearance,
  initializeSidecar,
  isNativeDesktopRuntime,
  listProjects,
  listTopics,
  listenForOrdinaryEvents,
  listenForPermissionEvents,
  listenForWindowAppearance,
  readTopic,
  readTopicEvidence,
  registerProject,
  resolveAuditFailure,
  respondToPermission,
  startRun,
  setWindowAppearance,
  searchTopics,
  stopRun,
  setTopicProject,
  updateTopic,
} from "./bridge/tauri";
import { Conversation, reviewTargetForMessage } from "./components/Conversation";
import { EvidencePanel } from "./components/EvidencePanel";
import { ParticipantManager } from "./components/ParticipantManager";
import { ParticipantPopover } from "./components/ParticipantPopover";
import { PermissionModal } from "./components/PermissionModal";
import { TopicProjectContext } from "./components/ProjectControls";
import { RunStatusSurface, type PersistentStatus } from "./components/RunStatusSurface";
import { TopicSidebar } from "./components/TopicSidebar";
import { WorkspaceHeader, type SeatSummary } from "./components/WorkspaceHeader";
import {
  isEventEnvelope,
  parseCapabilityCatalog,
  parseConversationMessage,
  parseEvidenceSummary,
  parseLivePrompt,
  parseParticipantActivity,
  parsePausedAuditFailure,
  parsePermissionRequest,
  parseProjectSummaries,
  parseProjectSummary,
  parseTopicDetail,
  parseTopicEvidenceLoaded,
  parseTopicEvidenceUnavailable,
  parseTopicSearchOccurrences,
  parseTopicSummaries,
  stringField,
  type ConversationMessage,
  type EvidenceSummary,
  type EventEnvelope,
  type LivePromptMessage,
  type ParticipantActivity,
  type PausedAuditFailure,
  type PermissionDecision,
  type PermissionRequest,
  type ProjectSummary,
  type TopicDetail,
  type TopicContextCheckpoint,
  type TopicParticipantInput,
  type TopicSearchOccurrence,
  type TopicSummary,
  PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT,
} from "./protocol/messages";
import {
  NATIVE_DEFAULT_SERVICE_TIER,
  assignRuntime,
  clearParticipantSelections,
  canStartRun,
  canStopRun,
  createDefaultParticipantConfiguration,
  reconcileParticipantConfiguration as reconcileConfiguration,
  recordEffectiveSettings,
  requestForSelectedModel,
  reduceRunState,
  selectableRuntimeIds,
  serviceTierOptions,
  swapExecutorWithAuditor,
  unconfiguredRequestForRuntime,
  validateRunConfiguration,
  validateParticipantSelection,
  type CapabilityCatalog,
  type ControlScalar,
  type Participant,
  type ParticipantConfiguration,
  type ProviderDescriptor,
  type RequestedSettings,
  type RunState,
  type RuntimeId,
} from "./state/model";
import { transitionTopicView } from "./state/topics";
import {
  applyAppearanceState,
  readAppearancePreference,
  resolveAppearance,
  storeAppearancePreference,
  type AccessibilityDisplayState,
  type AppearancePreference,
  type EffectiveAppearance,
} from "./state/appearance";
import {
  classifyTopicMutationEvent,
  dismissPermissionRequest,
  restoreDeletedTopic,
  restoreUpdatedTopic,
  type PendingTopicMutation,
} from "./state/commandRecovery";
import { contextCheckpointUnavailableReason } from "./state/contextCheckpoint";
import { initializeGovernanceCore } from "./state/governanceStartup";
import {
  classifyEvidenceResponse,
  isEvidenceForActiveTopic,
  type PendingEvidenceRead,
} from "./state/evidenceHistory";
import {
  bindCheckpointCommand,
  classifyCheckpointEvent,
  isCheckpointLifecycleEvent,
  shouldProcessDeferredCheckpointEvent,
  type CheckpointCommandAction,
  type PendingCheckpointCommand,
} from "./state/checkpointRecovery";
import {
  readSidebarVisibility,
  storeSidebarVisibility,
  type SidebarVisibility,
} from "./state/sidebarPreference";

interface SeatPopoverState {
  participantId: string;
  anchor: DOMRect;
}

type GovernanceCorePhase = "starting" | "ready" | "failed" | "preview";
type EvidenceSource = "current-run" | "saved-topic" | "loading" | "unavailable";

export function App() {
  const previewMode = !isNativeDesktopRuntime();
  const [appearance, setAppearance] = useState<AppearancePreference>(() => readAppearancePreference(safeLocalStorage()));
  const [sidebarVisibility, setSidebarVisibility] = useState<SidebarVisibility>(
    () => readSidebarVisibility(safeLocalStorage()),
  );
  const [systemAppearance, setSystemAppearance] = useState<EffectiveAppearance>(browserSystemAppearance);
  const [accessibilityDisplay, setAccessibilityDisplay] = useState<AccessibilityDisplayState>(browserAccessibilityDisplayState);
  const [catalog, setCatalog] = useState<CapabilityCatalog>(() => previewMode ? PREVIEW_CATALOG : {});
  const [configuration, setConfiguration] = useState<ParticipantConfiguration>(() => previewMode
    ? reconcileConfiguration(createDefaultParticipantConfiguration(), PREVIEW_CATALOG)
    : createDefaultParticipantConfiguration());
  const [rounds, setRounds] = useState(1);
  const [prompt, setPrompt] = useState("");
  const [prompts, setPrompts] = useState<LivePromptMessage[]>(() => previewMode ? PREVIEW_DETAIL.prompts : []);
  const [pendingPrompt, setPendingPrompt] = useState<LivePromptMessage | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>(() => previewMode ? PREVIEW_DETAIL.messages : []);
  const [activities, setActivities] = useState<ParticipantActivity[]>([]);
  const [pausedAudit, setPausedAudit] = useState<PausedAuditFailure | null>(null);
  const [resolvingAudit, setResolvingAudit] = useState(false);
  const [runState, dispatchRun] = useReducer(reduceRunState, { phase: "idle" } satisfies RunState);
  const [evidence, setEvidence] = useState<EvidenceSummary | null>(null);
  const [evidenceSource, setEvidenceSource] = useState<EvidenceSource>(previewMode ? "current-run" : "unavailable");
  const [evidenceUnavailableMessage, setEvidenceUnavailableMessage] = useState("");
  const [permissions, setPermissions] = useState<PermissionRequest[]>([]);
  const [permissionSubmitting, setPermissionSubmitting] = useState(false);
  const [permissionError, setPermissionError] = useState("");
  const [sidecarReady, setSidecarReady] = useState(false);
  const [governanceCorePhase, setGovernanceCorePhase] = useState<GovernanceCorePhase>(previewMode ? "preview" : "starting");
  const [governanceCoreAttempt, setGovernanceCoreAttempt] = useState(0);
  const [notice, setNotice] = useState("Starting the local governance core…");
  const [connectionError, setConnectionError] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [composerOverlayHeight, setComposerOverlayHeight] = useState(176);
  const [refreshing, setRefreshing] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [seatPopover, setSeatPopover] = useState<SeatPopoverState | null>(null);
  const [topicQuery, setTopicQuery] = useState("");
  const [archivedView, setArchivedView] = useState(false);
  const [topics, setTopics] = useState<TopicSummary[]>(() => previewMode ? PREVIEW_TOPICS : []);
  const [projects, setProjects] = useState<ProjectSummary[]>(() => previewMode ? PREVIEW_PROJECTS : []);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(() => previewMode ? PREVIEW_DETAIL.summary.projectId : null);
  const [projectBusy, setProjectBusy] = useState(false);
  const [activeTopicId, setActiveTopicId] = useState<string | null>(() => previewMode ? PREVIEW_DETAIL.summary.id : null);
  const [activeTopic, setActiveTopic] = useState<TopicDetail | null>(() => previewMode ? PREVIEW_DETAIL : null);
  const [searchOccurrences, setSearchOccurrences] = useState<TopicSearchOccurrence[]>([]);
  const [searchingTopics, setSearchingTopics] = useState(false);
  const [checkpointBusy, setCheckpointBusy] = useState(false);
  const [topicBusy, setTopicBusy] = useState(false);
  const pendingPermissionCommand = useRef<{ commandId: string; permissionId: string } | null>(null);
  const permissionInvokeInFlight = useRef(false);
  const earlyCommandEvents = useRef(new Map<string, EventEnvelope>());
  const pendingTopicMutation = useRef<PendingTopicMutation | null>(null);
  const earlyTopicMutationEvents = useRef(new Map<string, EventEnvelope>());
  const pendingProjectCommand = useRef<{ action: "list" | "register"; commandId: string | null } | null>(null);
  const earlyProjectEvents = useRef(new Map<string, EventEnvelope>());
  const activeTopicIdRef = useRef<string | null>(activeTopicId);
  const catalogRef = useRef<CapabilityCatalog>(catalog);
  const topicListModeRef = useRef(false);
  const runTopicIdRef = useRef<string | null>(null);
  const pendingActiveArchive = useRef<{ topicId: string; nextId: string | null } | null>(null);
  const pendingActiveDelete = useRef<{ topicId: string; nextId: string | null } | null>(null);
  const composerDockRef = useRef<HTMLElement>(null);
  const pendingSearchAnchor = useRef<string | null>(null);
  const governanceProtocolReady = useRef(previewMode);
  const pendingEvidenceRead = useRef<PendingEvidenceRead | null>(null);
  const earlyEvidenceEvents = useRef(new Map<string, EventEnvelope>());
  const ordinaryEventHandler = useRef<(value: EventEnvelope) => void>(() => undefined);
  const pendingCheckpointCommand = useRef<PendingCheckpointCommand | null>(null);
  const earlyCheckpointEvents = useRef(new Map<string, EventEnvelope[]>());

  useEffect(() => {
    activeTopicIdRef.current = activeTopicId;
  }, [activeTopicId]);

  useEffect(() => {
    catalogRef.current = catalog;
  }, [catalog]);

  useEffect(() => {
    const effective = resolveAppearance(appearance, systemAppearance);
    applyAppearanceState(document.documentElement, appearance, effective, accessibilityDisplay);
    storeAppearancePreference(safeLocalStorage(), appearance);
  }, [accessibilityDisplay, appearance, systemAppearance]);

  useEffect(() => {
    storeSidebarVisibility(safeLocalStorage(), sidebarVisibility);
  }, [sidebarVisibility]);

  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | undefined;
    const media = globalThis.matchMedia?.("(prefers-color-scheme: dark)");

    function readBrowserTheme() {
      if (active) setSystemAppearance(media?.matches ? "dark" : "light");
    }

    if (previewMode) {
      readBrowserTheme();
      media?.addEventListener("change", readBrowserTheme);
      return () => {
        active = false;
        media?.removeEventListener("change", readBrowserTheme);
      };
    }

    void setWindowAppearance(appearance)
      .then(() => getWindowAppearance())
      .then((theme) => { if (active) setSystemAppearance(theme); })
      .catch(() => undefined);
    void listenForWindowAppearance((theme) => {
      if (active) setSystemAppearance(theme);
    }).then((stop) => {
      if (!active) stop();
      else unlisten = stop;
    }).catch(() => undefined);

    return () => {
      active = false;
      unlisten?.();
    };
  }, [appearance, previewMode]);

  useEffect(() => {
    let active = true;
    const contrast = globalThis.matchMedia?.("(prefers-contrast: more)");
    const transparency = globalThis.matchMedia?.("(prefers-reduced-transparency: reduce)");
    const motion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)");

    function applyBrowserAccessibility() {
      if (!active) return;
      setAccessibilityDisplay({
        increaseContrast: Boolean(contrast?.matches),
        reduceTransparency: Boolean(transparency?.matches),
        differentiateWithoutColor: false,
        reduceMotion: Boolean(motion?.matches),
      });
    }

    async function refreshNativeAccessibility() {
      if (!active || previewMode) return;
      try {
        const state = await getAccessibilityDisplayState();
        if (active) setAccessibilityDisplay(state);
      } catch {
        applyBrowserAccessibility();
      }
    }

    applyBrowserAccessibility();
    contrast?.addEventListener("change", applyBrowserAccessibility);
    transparency?.addEventListener("change", applyBrowserAccessibility);
    motion?.addEventListener("change", applyBrowserAccessibility);
    const timer = previewMode ? undefined : globalThis.setInterval(() => void refreshNativeAccessibility(), 2_000);
    const refreshOnFocus = () => void refreshNativeAccessibility();
    globalThis.addEventListener?.("focus", refreshOnFocus);
    void refreshNativeAccessibility();

    return () => {
      active = false;
      if (timer !== undefined) globalThis.clearInterval(timer);
      contrast?.removeEventListener("change", applyBrowserAccessibility);
      transparency?.removeEventListener("change", applyBrowserAccessibility);
      motion?.removeEventListener("change", applyBrowserAccessibility);
      globalThis.removeEventListener?.("focus", refreshOnFocus);
    };
  }, [previewMode]);

  useEffect(() => {
    if (!toast) return;
    const timer = globalThis.setTimeout(() => setToast(null), 4_500);
    return () => globalThis.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const dock = composerDockRef.current;
    if (!dock) return;
    const update = () => setComposerOverlayHeight(Math.ceil(dock.getBoundingClientRect().height));
    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(dock);
    return () => observer?.disconnect();
  }, []);

  const loadTopicDetail = useCallback((detail: TopicDetail) => {
    const nextConfiguration = reconcileConfiguration(configurationFromWire(detail.participants), catalogRef.current);
    activeTopicIdRef.current = detail.summary.id;
    setActiveTopicId(detail.summary.id);
    setActiveTopic(detail);
    setSelectedProjectId(detail.summary.projectId);
    setTopics((current) => upsertTopic(current, detail.summary));
    setRounds(detail.rounds);
    setConfiguration(nextConfiguration);
    setPrompts(detail.prompts);
    setPendingPrompt(null);
    setMessages(detail.messages);
    setActivities([]);
    setPausedAudit(null);
    setEvidence(null);
    setEvidenceUnavailableMessage("");
    setEvidenceSource(previewMode ? "current-run" : "loading");
    setPrompt("");
    setTopicBusy(false);
    if (!previewMode) {
      const topicId = detail.summary.id;
      const pending: PendingEvidenceRead = { topicId, commandId: null };
      pendingEvidenceRead.current = pending;
      earlyEvidenceEvents.current.clear();
      void readTopicEvidence({ topic_id: topicId }).then((commandId) => {
        if (pendingEvidenceRead.current !== pending) return;
        pending.commandId = commandId;
        const early = earlyEvidenceEvents.current.get(commandId);
        earlyEvidenceEvents.current.clear();
        if (early) ordinaryEventHandler.current(early);
      }).catch(() => {
        if (pendingEvidenceRead.current !== pending || activeTopicIdRef.current !== topicId) return;
        pendingEvidenceRead.current = null;
        earlyEvidenceEvents.current.clear();
        setEvidenceSource("unavailable");
        setEvidenceUnavailableMessage("The latest saved closed-run evidence could not be requested.");
      });
    }
    const anchor = pendingSearchAnchor.current;
    if (anchor) {
      pendingSearchAnchor.current = null;
      globalThis.setTimeout(() => focusSearchAnchor(anchor), 0);
    }
  }, [previewMode]);

  const handleOrdinaryEvent = useCallback((value: EventEnvelope) => {
    if (!isEventEnvelope(value) || value.event === "permission.request") return;
    const payload = value.payload;
    const projectCommand = pendingProjectCommand.current;
    const projectLifecycleEvent = value.event === "project.list.result" || value.event === "project.registered";
    if (projectCommand && value.request_id && (projectLifecycleEvent || value.event === "protocol.error")) {
      if (!projectCommand.commandId) {
        earlyProjectEvents.current.set(value.request_id, value);
        return;
      }
      if (projectLifecycleEvent && projectCommand.commandId !== value.request_id) return;
      if (projectCommand.commandId === value.request_id && value.event === "protocol.error") {
        pendingProjectCommand.current = null;
        earlyProjectEvents.current.clear();
        setProjectBusy(false);
        setConnectionError(stringField(payload, "message") || "The Project change was rejected safely.");
        return;
      }
    }
    const checkpointDisposition = classifyCheckpointEvent(pendingCheckpointCommand.current, value);
    if (value.event === "protocol.error") {
      let checkpointDeferred = false;
      if (checkpointDisposition === "defer" && value.request_id) {
        const queued = earlyCheckpointEvents.current.get(value.request_id) ?? [];
        earlyCheckpointEvents.current.set(value.request_id, [...queued, value]);
        checkpointDeferred = true;
      }

      const evidenceDisposition = classifyEvidenceResponse(
        pendingEvidenceRead.current,
        value.request_id,
        null,
        true,
      );
      let evidenceDeferred = false;
      if (evidenceDisposition === "defer" && value.request_id) {
        earlyEvidenceEvents.current.set(value.request_id, value);
        evidenceDeferred = true;
      }

      if (checkpointDisposition === "rejected") {
        pendingCheckpointCommand.current = null;
        earlyCheckpointEvents.current.clear();
        setCheckpointBusy(false);
        setConnectionError(stringField(payload, "message") || "The context checkpoint change was rejected safely.");
      }
      if (evidenceDisposition === "accept") {
        pendingEvidenceRead.current = null;
        earlyEvidenceEvents.current.clear();
        setEvidence(null);
        setEvidenceSource("unavailable");
        setEvidenceUnavailableMessage("The latest saved closed-run evidence could not be loaded.");
      }
      if (
        checkpointDisposition === "rejected" ||
        evidenceDisposition === "accept" ||
        checkpointDeferred ||
        evidenceDeferred
      ) {
        return;
      }
    } else {
      if (checkpointDisposition === "defer" && value.request_id) {
        const queued = earlyCheckpointEvents.current.get(value.request_id) ?? [];
        earlyCheckpointEvents.current.set(value.request_id, [...queued, value]);
        if (earlyCheckpointEvents.current.size > 32) {
          const oldest = earlyCheckpointEvents.current.keys().next().value;
          if (oldest) earlyCheckpointEvents.current.delete(oldest);
        }
        if (!shouldProcessDeferredCheckpointEvent(value)) return;
      }
      if (checkpointDisposition === "completed") {
        pendingCheckpointCommand.current = null;
        earlyCheckpointEvents.current.clear();
        setCheckpointBusy(false);
      } else if (isCheckpointLifecycleEvent(value.event) && checkpointDisposition === "unrelated") {
        return;
      } else if (checkpointDisposition === "progress" && value.event === "command.result") {
        return;
      }
    }
    const pendingMutation = pendingTopicMutation.current;
    if (pendingMutation) {
      const disposition = classifyTopicMutationEvent(pendingMutation, value);
      if (disposition === "defer") {
        if (!value.request_id) return;
        earlyTopicMutationEvents.current.set(value.request_id, value);
        return;
      }
      if (disposition === "succeeded" || disposition === "rejected") {
        pendingTopicMutation.current = null;
        if (disposition === "rejected") {
          pendingMutation.rollback();
          setTopicBusy(false);
          setConnectionError(stringField(payload, "message") || "The topic change was rejected and has been restored.");
          return;
        }
      }
    }
    if (value.request_id && (value.event === "command.result" || value.event === "protocol.error")) {
      const pending = pendingPermissionCommand.current;
      if (pending?.commandId === value.request_id) {
        pendingPermissionCommand.current = null;
        if (value.event === "command.result") setPermissionError("");
        else {
          const message = stringField(payload, "message") || "The permission decision was not accepted; the action remained denied.";
          setPermissions((queue) => dismissPermissionRequest(queue, pending.permissionId));
          setPermissionSubmitting(false);
          setPermissionError("");
          setConnectionError(message);
        }
        return;
      }
      earlyCommandEvents.current.set(value.request_id, value);
      if (earlyCommandEvents.current.size > 64) {
        const oldest = earlyCommandEvents.current.keys().next().value;
        if (oldest) earlyCommandEvents.current.delete(oldest);
      }
      if (permissionInvokeInFlight.current) return;
    }

    switch (value.event) {
      case "sidecar.ready":
        if (governanceProtocolReady.current) {
          setSidecarReady(true);
          setNotice("Governance core ready");
        }
        break;
      case "capabilities.result": {
        const nextCatalog = parseCapabilityCatalog(payload.providers);
        if (nextCatalog) {
          catalogRef.current = nextCatalog;
          setCatalog(nextCatalog);
          setConfiguration((current) => reconcileConfiguration(current, nextCatalog));
          setRefreshing(false);
          setNotice("Authenticated runtime choices refreshed");
        } else {
          setRefreshing(false);
          setConnectionError("The capability response was malformed.");
        }
        break;
      }
      case "project.list.result": {
        const nextProjects = parseProjectSummaries(payload.projects);
        if (!nextProjects) {
          setConnectionError("The Project list was malformed.");
        } else {
          setProjects(nextProjects);
        }
        pendingProjectCommand.current = null;
        earlyProjectEvents.current.clear();
        setProjectBusy(false);
        break;
      }
      case "project.registered": {
        const project = parseProjectSummary(payload.project);
        if (!project) {
          setConnectionError("The registered Project response was malformed.");
        } else {
          setProjects((current) => current.some((item) => item.id === project.id)
            ? current.map((item) => item.id === project.id ? project : item)
            : [...current, project]);
          setSelectedProjectId(project.id);
          clearActiveTopicView();
          setToast(`${project.name} is ready · New Topic will use this Project`);
        }
        pendingProjectCommand.current = null;
        earlyProjectEvents.current.clear();
        setProjectBusy(false);
        break;
      }
      case "topic.search.result": {
        const occurrences = parseTopicSearchOccurrences(payload.occurrences);
        if (!occurrences) {
          setConnectionError("The topic search response was malformed.");
        } else {
          setSearchOccurrences(occurrences);
        }
        setSearchingTopics(false);
        break;
      }
      case "topic.list.result": {
        const nextTopics = parseTopicSummaries(payload.topics);
        if (!nextTopics) {
          setConnectionError("The topic list was malformed.");
          break;
        }
        const listedArchived = topicListModeRef.current;
        setTopics((current) => [
          ...current.filter((topic) => topic.archived !== listedArchived),
          ...nextTopics,
        ]);
        setTopicBusy(false);
        setActiveTopicId((current) => {
          if (current) return current;
          if (listedArchived) return current;
          const first = nextTopics.find((topic) => !topic.archived);
          if (first) void readTopic({ topic_id: first.id });
          return first?.id ?? null;
        });
        break;
      }
      case "topic.created":
      case "topic.loaded": {
        const detail = parseTopicDetail(payload.topic);
        if (detail) loadTopicDetail(detail);
        else setConnectionError("The saved topic response was malformed.");
        break;
      }
      case "topic.evidence.loaded": {
        const parsed = parseTopicEvidenceLoaded(payload);
        const topicId = parsed?.topicId ?? stringField(payload, "topic_id");
        const disposition = classifyEvidenceResponse(pendingEvidenceRead.current, value.request_id, topicId);
        if (disposition === "defer" && value.request_id) {
          earlyEvidenceEvents.current.set(value.request_id, value);
          break;
        }
        if (disposition !== "accept" || !isEvidenceForActiveTopic(activeTopicIdRef.current, topicId)) break;
        pendingEvidenceRead.current = null;
        earlyEvidenceEvents.current.clear();
        if (!parsed) {
          setEvidence(null);
          setEvidenceSource("unavailable");
          setEvidenceUnavailableMessage("The latest saved closed-run evidence was malformed and was not displayed.");
          break;
        }
        setEvidence(parsed.summary);
        setEvidenceSource("saved-topic");
        setEvidenceUnavailableMessage("");
        break;
      }
      case "topic.evidence.unavailable": {
        const parsed = parseTopicEvidenceUnavailable(payload);
        const topicId = parsed?.topicId ?? stringField(payload, "topic_id");
        const disposition = classifyEvidenceResponse(pendingEvidenceRead.current, value.request_id, topicId);
        if (disposition === "defer" && value.request_id) {
          earlyEvidenceEvents.current.set(value.request_id, value);
          break;
        }
        if (disposition !== "accept" || !isEvidenceForActiveTopic(activeTopicIdRef.current, topicId)) break;
        pendingEvidenceRead.current = null;
        earlyEvidenceEvents.current.clear();
        setEvidence(null);
        setEvidenceSource("unavailable");
        setEvidenceUnavailableMessage(
          parsed?.message || "The latest saved closed-run evidence is unavailable for this topic.",
        );
        break;
      }
      case "topic.updated": {
        const detail = parseTopicDetail(payload.topic);
        if (!detail) {
          setTopicBusy(false);
          setConnectionError("The saved topic response was malformed.");
          break;
        }
        setTopics((current) => upsertTopic(current, detail.summary));
        if (detail.summary.id === activeTopicIdRef.current) setActiveTopic(detail);
        setTopicBusy(false);
        const pending = pendingActiveArchive.current;
        if (pending?.topicId === detail.summary.id && detail.summary.archived) {
          pendingActiveArchive.current = null;
          if (pending.nextId) {
            activeTopicIdRef.current = pending.nextId;
            pendingEvidenceRead.current = null;
            earlyEvidenceEvents.current.clear();
            setEvidence(null);
            setEvidenceSource("loading");
            setEvidenceUnavailableMessage("");
            setTopicBusy(true);
            void readTopic({ topic_id: pending.nextId }).catch((error) => {
              setTopicBusy(false);
              setEvidenceSource("unavailable");
              setEvidenceUnavailableMessage("The next topic and its latest saved evidence could not be loaded.");
              setConnectionError(formatError(error));
            });
          } else {
            activeTopicIdRef.current = null;
            pendingEvidenceRead.current = null;
            earlyEvidenceEvents.current.clear();
            setActiveTopicId(null);
            setActiveTopic(null);
            setPrompts([]);
            setMessages([]);
            setActivities([]);
            setEvidence(null);
            setEvidenceSource("unavailable");
            setEvidenceUnavailableMessage("");
          }
        }
        break;
      }
      case "topic.deleted": {
        const topicId = stringField(payload, "topic_id");
        if (!topicId) break;
        setTopics((current) => current.filter((topic) => topic.id !== topicId));
        const pendingDelete = pendingActiveDelete.current;
        pendingActiveDelete.current = null;
        setActiveTopicId((current) => {
          if (current !== topicId) return current;
          if (pendingDelete?.topicId === topicId && pendingDelete.nextId) {
            activeTopicIdRef.current = pendingDelete.nextId;
            pendingEvidenceRead.current = null;
            earlyEvidenceEvents.current.clear();
            setPrompts([]);
            setMessages([]);
            setActivities([]);
            setEvidence(null);
            setEvidenceSource("loading");
            setEvidenceUnavailableMessage("");
            setTopicBusy(true);
            void readTopic({ topic_id: pendingDelete.nextId }).catch((error) => {
              setTopicBusy(false);
              setEvidenceSource("unavailable");
              setEvidenceUnavailableMessage("The next topic and its latest saved evidence could not be loaded.");
              setConnectionError(formatError(error));
            });
            return pendingDelete.nextId;
          }
          activeTopicIdRef.current = null;
          pendingEvidenceRead.current = null;
          earlyEvidenceEvents.current.clear();
          setActiveTopic(null);
          setPrompts([]);
          setMessages([]);
          setActivities([]);
          setEvidence(null);
          setEvidenceSource("unavailable");
          setEvidenceUnavailableMessage("");
          return null;
        });
        if (!pendingDelete?.nextId) setTopicBusy(false);
        break;
      }
      case "topic.checkpoint.started":
        setNotice("Executor is preparing a context checkpoint…");
        break;
      case "topic.checkpoint.drafted":
        setToast(stringField(payload, "message") || "Checkpoint draft ready for Live's review.");
        break;
      case "topic.checkpoint.failed":
        setConnectionError(stringField(payload, "message") || "Checkpoint generation failed safely.");
        break;
      case "topic.checkpoint.activated":
        setToast("Context checkpoint activated by Live.");
        break;
      case "topic.checkpoint.deactivated":
        setToast("Full canonical topic context restored.");
        break;
      case "conversation.prompt": {
        if (!eventMatchesTopic(payload, activeTopicIdRef.current, runTopicIdRef.current)) break;
        const nextPrompt = parseLivePrompt(payload.prompt);
        if (!nextPrompt) break;
        setPrompts((current) => current.some((item) => item.id === nextPrompt.id) ? current : [...current, nextPrompt]);
        setPendingPrompt((current) => current?.cycle === nextPrompt.cycle ? null : current);
        break;
      }
      case "run.started": {
        const runId = stringField(payload, "run_id");
        if (runId) {
          dispatchRun({ type: "started", runId });
          setNotice("Run active");
        }
        break;
      }
      case "run.round.started":
        if (typeof payload.round === "number") dispatchRun({ type: "round-started", round: payload.round });
        break;
      case "conversation.message": {
        if (!eventMatchesTopic(payload, activeTopicIdRef.current, runTopicIdRef.current)) break;
        const message = parseConversationMessage(payload.message);
        if (!message) break;
        setMessages((current) => current.some((existing) => existing.id === message.id) ? current : [...current, message]);
        if (message.effective) {
          setConfiguration((current) => mapParticipant(current, message.participant_id, message.role, (participant) => recordEffectiveSettings(participant, message.effective!)));
        }
        break;
      }
      case "participant.activity": {
        if (!eventMatchesTopic(payload, activeTopicIdRef.current, runTopicIdRef.current)) break;
        const activity = parseParticipantActivity(payload);
        if (!activity) break;
        setActivities((current) => {
          const withoutPrevious = current.filter((item) => !(item.run_id === activity.run_id && item.participant_id === activity.participant_id && item.stage === activity.stage && item.round === activity.round && item.cycle === activity.cycle));
          return [...withoutPrevious, activity];
        });
        break;
      }
      case "audit.failure.paused": {
        const failure = parsePausedAuditFailure(payload);
        if (failure) {
          setPausedAudit(failure);
          setResolvingAudit(false);
          setNotice("Audit paused for Live");
        }
        break;
      }
      case "audit.failure.resumed":
        setPausedAudit((current) => current?.failure_id === payload.failure_id ? null : current);
        setResolvingAudit(false);
        setNotice("Audit resumed");
        break;
      case "permission.recorded": {
        const permissionId = stringField(payload, "permission_id");
        if (permissionId) setPermissions((queue) => dismissPermissionRequest(queue, permissionId));
        setPermissionSubmitting(false);
        setPermissionError("");
        break;
      }
      case "permission.record_failed": {
        const permissionId = stringField(payload, "permission_id");
        const message = stringField(payload, "message") || "The permission decision could not be durably recorded; the action was not authorized.";
        if (permissionId) setPermissions((queue) => dismissPermissionRequest(queue, permissionId));
        setPermissionSubmitting(false);
        setPermissionError("");
        setConnectionError(message);
        break;
      }
      case "run.evidence": {
        const summary = parseEvidenceSummary(payload.summary);
        if (summary) {
          setEvidence(summary);
          setEvidenceSource("current-run");
          setEvidenceUnavailableMessage("");
        }
        else setConnectionError("The run evidence summary was malformed and was not displayed.");
        break;
      }
      case "run.evidence.unavailable":
        setEvidence(null);
        setEvidenceSource("unavailable");
        setEvidenceUnavailableMessage(stringField(payload, "message") || "The owner-only evidence summary could not be produced.");
        break;
      case "run.completed":
        setPermissions([]);
        setPermissionSubmitting(false);
        setPendingPrompt(null);
        dispatchRun({ type: "completed" });
        setNotice("Cycle completed and saved");
        setToast("Cycle completed and saved");
        runTopicIdRef.current = null;
        break;
      case "run.stopped":
        setPermissions([]);
        setPermissionSubmitting(false);
        setPendingPrompt(null);
        dispatchRun({ type: "stopped", reason: payload.reason === "plan-warning" ? "plan-warning" : "live" });
        setNotice(payload.reason === "plan-warning" ? "Stopped: plan-usage warning" : "Stopped by Live");
        runTopicIdRef.current = null;
        break;
      case "plan.warning":
        dispatchRun({ type: "stopped", reason: "plan-warning" });
        setNotice("Stopped: plan-usage warning");
        setConnectionError(stringField(payload, "message") || "The runtime reported a plan-usage warning.");
        break;
      case "run.failed":
      case "sidecar_run_fault": {
        const message = stringField(payload, "message") || "The run failed safely.";
        setPermissions([]);
        setPermissionSubmitting(false);
        setPendingPrompt(null);
        dispatchRun({ type: "failed", message });
        setConnectionError(message);
        runTopicIdRef.current = null;
        break;
      }
      case "supervisor.status":
        if (payload.state === "running") {
          // Process-running can precede the initialize acknowledgement. It is
          // deliberately not treated as protocol readiness.
          if (governanceProtocolReady.current) setSidecarReady(true);
        } else if (payload.state === "exited") {
          governanceProtocolReady.current = false;
          pendingEvidenceRead.current = null;
          earlyEvidenceEvents.current.clear();
          pendingCheckpointCommand.current = null;
          earlyCheckpointEvents.current.clear();
          pendingProjectCommand.current = null;
          earlyProjectEvents.current.clear();
          setSidecarReady(false);
          setGovernanceCorePhase("failed");
          const pendingMutation = pendingTopicMutation.current;
          pendingTopicMutation.current = null;
          earlyTopicMutationEvents.current.clear();
          pendingMutation?.rollback();
          setCheckpointBusy(false);
          setRefreshing(false);
          setTopicBusy(false);
          setProjectBusy(false);
          setNotice("Governance core stopped");
          const message = "The local governance core exited. Retry it to reload saved topics.";
          setConnectionError(message);
          dispatchRun({ type: "failed", message });
          setPermissions([]);
          if (pendingPermissionCommand.current) {
            pendingPermissionCommand.current = null;
            setPermissionSubmitting(false);
            setPermissionError("The governance core exited before recording this decision.");
          }
        }
        break;
      case "supervisor.error":
      case "protocol.error": {
        const message = stringField(payload, "message") || "The local governance core reported an error.";
        setConnectionError(message);
        dispatchRun({ type: "failed", message });
        break;
      }
    }
  }, [loadTopicDetail]);

  ordinaryEventHandler.current = handleOrdinaryEvent;

  const handlePermissionEvent = useCallback((value: EventEnvelope) => {
    if (!isEventEnvelope(value)) return;
    const request = parsePermissionRequest(value);
    if (!request) {
      setConnectionError("A malformed permission request was rejected by the trusted channel.");
      return;
    }
    setPermissions((current) => current.some((item) => item.permission_id === request.permission_id) ? current : [...current, request]);
  }, []);

  useEffect(() => {
    let active = true;
    const unlisten: Array<() => void> = [];
    async function connect() {
      if (previewMode) {
        setGovernanceCorePhase("preview");
        setNotice("Browser preview · open the native app to connect runtimes");
        return;
      }
      governanceProtocolReady.current = false;
      setGovernanceCorePhase("starting");
      setSidecarReady(false);
      setRefreshing(true);
      setTopicBusy(true);
      setNotice("Starting the local governance core…");
      try {
        const ordinary = await listenForOrdinaryEvents(handleOrdinaryEvent);
        if (!active) { ordinary(); return; }
        unlisten.push(ordinary);
        const permission = await listenForPermissionEvents(handlePermissionEvent);
        if (!active) { permission(); return; }
        unlisten.push(permission);
        await initializeGovernanceCore({
          initialize: initializeSidecar,
          isCurrent: () => active,
          onReady: () => {
            governanceProtocolReady.current = true;
            setSidecarReady(true);
            setGovernanceCorePhase("ready");
            setConnectionError("");
            setNotice("Governance core started; discovering runtimes…");
          },
        });
      } catch (error) {
        if (active) {
          governanceProtocolReady.current = false;
          setSidecarReady(false);
          setGovernanceCorePhase("failed");
          setRefreshing(false);
          setTopicBusy(false);
          setConnectionError(formatError(error));
          setNotice("Governance core unavailable");
        }
        return;
      }
      if (!active) return;
      try {
        await discoverCapabilities();
      } catch (error) {
        if (active) {
          setRefreshing(false);
          setConnectionError(formatError(error));
        }
      }
    }
    void connect();
    return () => { active = false; unlisten.forEach((stopListening) => stopListening()); };
  }, [governanceCoreAttempt, handleOrdinaryEvent, handlePermissionEvent, previewMode]);

  useEffect(() => {
    if (previewMode || governanceCorePhase !== "ready") return;
    topicListModeRef.current = archivedView;
    setTopicBusy(true);
    void listTopics({ archived: archivedView }).catch((error) => {
      setTopicBusy(false);
      setConnectionError(formatError(error));
    });
  }, [archivedView, governanceCorePhase, previewMode]);

  useEffect(() => {
    if (previewMode || governanceCorePhase !== "ready" || pendingProjectCommand.current) return;
    sendProjectCommand("list", () => listProjects());
  }, [governanceCorePhase, previewMode]);

  useEffect(() => {
    const query = topicQuery.trim();
    if (!query) {
      setSearchOccurrences([]);
      setSearchingTopics(false);
      return;
    }
    if (previewMode) {
      setSearchOccurrences(previewSearch(query));
      return;
    }
    if (governanceCorePhase !== "ready") {
      setSearchOccurrences([]);
      setSearchingTopics(false);
      return;
    }
    setSearchingTopics(true);
    const timer = globalThis.setTimeout(() => {
      void searchTopics({ query, include_archived: true, limit: 100 }).catch((error) => {
        setSearchingTopics(false);
        setConnectionError(formatError(error));
      });
    }, 180);
    return () => globalThis.clearTimeout(timer);
  }, [governanceCorePhase, previewMode, topicQuery]);

  const configurationIssues = useMemo(() => validateParticipantSelection(configuration.executor, catalog), [catalog, configuration]);
  const reviewIssues = useMemo(() => validateRunConfiguration({ participants: configuration, rounds }, catalog), [catalog, configuration, rounds]);
  const activeRun = runState.phase === "starting" || runState.phase === "running" || runState.phase === "stopping";
  const activeOperation = activeRun || checkpointBusy;
  const checkpointCancelable = checkpointBusy && pendingCheckpointCommand.current?.action === "draft";
  const activeProject = activeTopic?.summary.projectId
    ? projects.find((project) => project.id === activeTopic.summary.projectId)
    : undefined;
  const activeProjectUnavailable = Boolean(
    activeTopic?.summary.projectId && !projectBusy && (!activeProject || !activeProject.available),
  );
  const operationReady = Boolean(activeTopicId) && !topicBusy && !activeTopic?.summary.archived && governanceCorePhase === "ready" && sidecarReady && !refreshing && !checkpointBusy && !activeProjectUnavailable && canStartRun(runState);
  const startEnabled = operationReady && prompt.trim().length > 0 && configurationIssues.length === 0;
  const reviewEnabled = operationReady && reviewIssues.length === 0;
  const allPrompts = pendingPrompt ? [...prompts, pendingPrompt] : prompts;
  const executorSeat = seatSummary(configuration.executor, catalog, latestActivity(activities, configuration.executor.participantId));
  const auditorSeats = configuration.auditors.map((auditor) => seatSummary(auditor, catalog, latestActivity(activities, auditor.participantId)));
  const runtimeNames = Object.fromEntries([configuration.executor, ...configuration.auditors].map((participant) => [participant.participantId, seatInlineLabel(seatSummary(participant, catalog))]));
  const runtimeDisplayNames = Object.fromEntries(Object.values(catalog).map((entry) => [entry.runtimeId, entry.descriptor.display.name]));
  const popoverParticipant = seatPopover ? findParticipant(configuration, seatPopover.participantId) : null;
  const checkpointUnavailableReason = contextCheckpointUnavailableReason({
    activeTopic: Boolean(activeTopicId),
    archivedTopic: Boolean(activeTopic?.summary.archived),
    protocolReady: governanceCorePhase === "ready" && sidecarReady,
    previewMode,
    runActive: activeRun,
    checkpointBusy,
    topicBusy,
    messages,
  });
  const persistentStatus = useMemo<PersistentStatus | null>(() => {
    if (governanceCorePhase === "starting") {
      return { tone: "running", message: "Starting the local governance core…" };
    }
    if (governanceCorePhase === "failed") {
      return {
        tone: "error",
        message: connectionError || "The local governance core is unavailable.",
        actionLabel: "Retry governance core",
      };
    }
    if (runState.phase === "stopped" && runState.reason === "plan-warning") {
      return { tone: "warning", message: connectionError || "Stopped: plan-usage warning" };
    }
    if (connectionError) return { tone: "error", message: connectionError };
    if (activeProjectUnavailable) {
      return { tone: "warning", message: "This topic's Project folder is unavailable. Choose an available Project before starting." };
    }
    if (permissions.length > 0) {
      const suffix = permissions.length > 1 ? ` · ${permissions.length - 1} more queued` : "";
      return { tone: "permission", message: `Waiting for Live's permission decision${suffix}` };
    }
    if (pausedAudit) return { tone: "paused", message: "Audit paused for Live's resolution" };
    if (checkpointBusy) return { tone: "running", message: notice || "Executor is preparing a context checkpoint…" };
    if (runState.phase === "starting" || runState.phase === "running" || runState.phase === "stopping") {
      return { tone: "running", message: notice };
    }
    if (runState.phase === "failed") return { tone: "error", message: runState.message };
    return null;
  }, [activeProjectUnavailable, checkpointBusy, connectionError, governanceCorePhase, notice, pausedAudit, permissions.length, runState]);

  function retryGovernanceCore() {
    if (previewMode || governanceCorePhase === "starting") return;
    // A retry only reconnects the local core and reloads persisted topics. It
    // never invokes run_start or resumes an interrupted model turn.
    setGovernanceCoreAttempt((attempt) => attempt + 1);
  }

  async function refreshCapabilities() {
    setRefreshing(true);
    setConnectionError("");
    setNotice("Refreshing authenticated runtime choices…");
    try { await discoverCapabilities(); } catch (error) { setRefreshing(false); setConnectionError(formatError(error)); }
  }

  function sendProjectCommand(
    action: "list" | "register",
    send: () => Promise<string | null>,
  ) {
    if (pendingProjectCommand.current) return;
    const pending = { action, commandId: null as string | null };
    pendingProjectCommand.current = pending;
    earlyProjectEvents.current.clear();
    setProjectBusy(true);
    setConnectionError("");
    void Promise.resolve().then(send).then((commandId) => {
      if (pendingProjectCommand.current !== pending) return;
      if (!commandId) {
        pendingProjectCommand.current = null;
        earlyProjectEvents.current.clear();
        setProjectBusy(false);
        return;
      }
      pending.commandId = commandId;
      const early = earlyProjectEvents.current.get(commandId);
      earlyProjectEvents.current.clear();
      if (early) ordinaryEventHandler.current(early);
    }).catch((error) => {
      if (pendingProjectCommand.current !== pending) return;
      pendingProjectCommand.current = null;
      earlyProjectEvents.current.clear();
      setProjectBusy(false);
      setConnectionError(formatError(error));
    });
  }

  function openProjectFolder() {
    if (previewMode) {
      setToast("Folder selection is available in the native Dialektikḗ app.");
      return;
    }
    if (activeOperation || topicBusy || projectBusy) return;
    sendProjectCommand("register", () => registerProject({
      acknowledgement: PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT,
    }));
  }

  function clearActiveTopicView() {
    activeTopicIdRef.current = null;
    pendingEvidenceRead.current = null;
    earlyEvidenceEvents.current.clear();
    setActiveTopicId(null);
    setActiveTopic(null);
    setPrompts([]);
    setMessages([]);
    setActivities([]);
    setEvidence(null);
    setEvidenceSource("unavailable");
    setEvidenceUnavailableMessage("");
  }

  async function selectTopic(topicId: string) {
    if (activeOperation || topicBusy) return;
    const previousTopicId = activeTopicIdRef.current;
    activeTopicIdRef.current = topicId;
    pendingEvidenceRead.current = null;
    earlyEvidenceEvents.current.clear();
    setSeatPopover(null);
    setManageOpen(false);
    setTopicBusy(true);
    setEvidence(null);
    setEvidenceSource(previewMode ? "current-run" : "loading");
    setEvidenceUnavailableMessage("");
    if (previewMode) {
      loadTopicDetail(previewDetailFor(topicId));
      return;
    }
    try { await readTopic({ topic_id: topicId }); } catch (error) {
      if (activeTopicIdRef.current === topicId) activeTopicIdRef.current = previousTopicId;
      setTopicBusy(false);
      setEvidenceSource("unavailable");
      setEvidenceUnavailableMessage("The selected topic and its latest saved evidence could not be loaded.");
      setConnectionError(formatError(error));
    }
  }

  async function selectSearchOccurrence(occurrence: TopicSearchOccurrence) {
    if (activeOperation || topicBusy) return;
    pendingSearchAnchor.current = occurrence.sourceAnchor;
    setArchivedView(occurrence.archived);
    setTopicQuery("");
    setSelectedProjectId(topics.find((topic) => topic.id === occurrence.topicId)?.projectId ?? null);
    await selectTopic(occurrence.topicId);
  }

  function selectProject(projectId: string | null) {
    if (activeOperation || topicBusy || projectBusy || selectedProjectId === projectId) return;
    setSelectedProjectId(projectId);
    setTopicQuery("");
    const next = topics.find((topic) => topic.projectId === projectId && topic.archived === archivedView);
    if (next) {
      void selectTopic(next.id);
      return;
    }
    clearActiveTopicView();
  }

  async function createTopic() {
    if (activeOperation || topicBusy || projectBusy) return;
    const freshConfiguration = clearParticipantSelections(configuration, catalog);
    setTopicBusy(true);
    if (previewMode) {
      const now = new Date().toISOString();
      const detail: TopicDetail = {
        summary: { id: `preview-topic-${Date.now()}`, title: "Untitled topic", pinned: false, archived: false, created_at: now, updated_at: now, projectId: selectedProjectId },
        rounds,
        participants: configurationToWire(freshConfiguration),
        prompts: [],
        messages: [],
        contextCheckpoints: [],
        activeContextCheckpointId: null,
      };
      loadTopicDetail(detail);
      return;
    }
    try {
      await createTopicBridge({
        rounds,
        participants: configurationToWire(freshConfiguration),
        project_id: selectedProjectId ?? undefined,
      });
    } catch (error) {
      setTopicBusy(false);
      setConnectionError(formatError(error));
    }
  }

  function patchTopic(topicId: string, patch: { title?: string; pinned?: boolean; archived?: boolean }) {
    if (activeOperation || topicBusy) return;
    if (previewMode) {
      const updatedTopics = topics.map((topic) => topic.id === topicId ? { ...topic, ...patch, updated_at: new Date().toISOString() } : topic);
      setTopics(updatedTopics);
      if (patch.archived && activeTopicId === topicId) {
        const next = updatedTopics.find((topic) => !topic.archived && topic.id !== topicId && topic.projectId === selectedProjectId);
        if (next) void selectTopic(next.id);
        else {
          setActiveTopicId(null);
          setActiveTopic(null);
          setPrompts([]);
          setMessages([]);
        }
      }
      return;
    }
    const previousTopic = topics.find((topic) => topic.id === topicId);
    setTopics((current) => current.map((topic) => topic.id === topicId
      ? { ...topic, ...patch, updated_at: new Date().toISOString() }
      : topic));
    setTopicBusy(true);
    if (patch.archived && activeTopicId === topicId) {
      pendingActiveArchive.current = {
        topicId,
        nextId: topics.find((topic) => !topic.archived && topic.id !== topicId && topic.projectId === selectedProjectId)?.id ?? null,
      };
    }
    sendTopicMutation(() => updateTopic({ topic_id: topicId, ...patch }), "topic.updated", () => {
      pendingActiveArchive.current = null;
      setTopics((current) => restoreUpdatedTopic(current, topicId, previousTopic));
    });
  }

  function assignTopicProject(projectId: string | null) {
    if (!activeTopic || activeOperation || topicBusy || projectBusy || activeTopic.summary.projectId === projectId) return;
    const previous = activeTopic.summary.projectId;
    const topicId = activeTopic.summary.id;
    setSelectedProjectId(projectId);
    setActiveTopic((current) => current && current.summary.id === topicId
      ? { ...current, summary: { ...current.summary, projectId } }
      : current);
    setTopics((current) => current.map((topic) => topic.id === topicId ? { ...topic, projectId } : topic));
    if (previewMode) return;
    setTopicBusy(true);
    sendTopicMutation(
      () => setTopicProject({ topic_id: topicId, project_id: projectId }),
      "topic.updated",
      () => {
        setSelectedProjectId(previous);
        setActiveTopic((current) => current && current.summary.id === topicId
          ? { ...current, summary: { ...current.summary, projectId: previous } }
          : current);
        setTopics((current) => current.map((topic) => topic.id === topicId ? { ...topic, projectId: previous } : topic));
      },
    );
  }

  function tombstoneTopic(topicId: string) {
    if (activeOperation || topicBusy) return;
    if (previewMode) {
      const remaining = topics.filter((topic) => topic.id !== topicId);
      setTopics(remaining);
      if (activeTopicId === topicId) {
        const next = remaining.find((topic) => !topic.archived && topic.projectId === selectedProjectId);
        setActiveTopicId(null);
        setActiveTopic(null);
        setPrompts([]);
        setMessages([]);
        if (next) void selectTopic(next.id);
      }
      return;
    }
    const removedTopic = topics.find((topic) => topic.id === topicId);
    const removedIndex = topics.findIndex((topic) => topic.id === topicId);
    setTopics((current) => current.filter((topic) => topic.id !== topicId));
    setTopicBusy(true);
    if (activeTopicId === topicId) {
      pendingActiveDelete.current = {
        topicId,
        nextId: topics.find((topic) => !topic.archived && topic.id !== topicId && topic.projectId === selectedProjectId)?.id ?? null,
      };
    }
    sendTopicMutation(() => deleteTopicBridge({ topic_id: topicId }), "topic.deleted", () => {
      pendingActiveDelete.current = null;
      setTopics((current) => restoreDeletedTopic(current, removedTopic, removedIndex));
    });
  }

  function updateConfiguration(next: ParticipantConfiguration, nextRounds = rounds) {
    if (activeOperation || topicBusy) return;
    const previousConfiguration = configuration;
    const previousRounds = rounds;
    setConfiguration(next);
    setRounds(nextRounds);
    // Topics may truthfully persist an incomplete explicit selection. Only
    // run.start requires a concrete model and any catalog-advertised effort.
    if (activeTopicId && !previewMode) {
      setTopicBusy(true);
      sendTopicMutation(
        () => updateTopic({ topic_id: activeTopicId, rounds: nextRounds, participants: configurationToWire(next) }),
        "topic.updated",
        () => {
          setConfiguration(previousConfiguration);
          setRounds(previousRounds);
        },
      );
    }
  }

  function sendTopicMutation(
    send: () => Promise<string>,
    successEvent: PendingTopicMutation["successEvent"],
    rollback: () => void,
  ) {
    const pending: PendingTopicMutation = { commandId: null, successEvent, rollback };
    pendingTopicMutation.current = pending;
    void Promise.resolve().then(send).then((commandId) => {
      if (pendingTopicMutation.current !== pending) return;
      pending.commandId = commandId;
      const deferred = [...earlyTopicMutationEvents.current.values()];
      earlyTopicMutationEvents.current.clear();
      deferred.forEach(handleOrdinaryEvent);
    }).catch((error) => {
      if (pendingTopicMutation.current !== pending) return;
      pendingTopicMutation.current = null;
      earlyTopicMutationEvents.current.clear();
      rollback();
      setTopicBusy(false);
      setConnectionError(formatError(error));
    });
  }

  function changeRequested(participantId: string, field: keyof RequestedSettings, value: string) {
    if (activeOperation) return;
    const next = mapParticipant(configuration, participantId, undefined, (participant) => {
      let requested = { ...participant.requested, [field]: value };
      if (field === "model") requested = requestForSelectedModel(participant.requested, value, catalog[participant.runtimeId]?.models ?? []);
      return { ...participant, requested, effective: null };
    });
    updateConfiguration(next);
  }

  function changeControl(participantId: string, controlId: string, value: ControlScalar) {
    if (activeOperation) return;
    const next = mapParticipant(configuration, participantId, undefined, (participant) => ({
      ...participant,
      requested: {
        ...participant.requested,
        controls: { ...(participant.requested.controls ?? {}), [controlId]: value },
      },
      effective: null,
    }));
    updateConfiguration(next);
  }

  function changeExecutionProfile(participantId: string, profileId: string) {
    if (activeOperation) return;
    const next = mapParticipant(configuration, participantId, undefined, (participant) => {
      const profile = catalog[participant.runtimeId]?.descriptor.executionProfiles.find((candidate) => candidate.profileId === profileId);
      if (!profile || !profile.availability.available) return participant;
      return {
        ...participant,
        requested: {
          ...participant.requested,
          executionProfile: { profileId, values: { ...profile.values } },
        },
        effective: null,
      };
    });
    updateConfiguration(next);
  }

  function resetParticipant(participantId: string) {
    if (activeOperation) return;
    const next = mapParticipant(configuration, participantId, undefined, (participant) => assignRuntime(participant, participant.runtimeId, unconfiguredRequestForRuntime(catalog[participant.runtimeId])));
    updateConfiguration(next);
  }

  function changeRuntime(participantId: string, runtimeId: RuntimeId) {
    if (activeOperation) return;
    const next = mapParticipant(configuration, participantId, undefined, (participant) => assignRuntime(participant, runtimeId, unconfiguredRequestForRuntime(catalog[runtimeId])));
    updateConfiguration(next);
  }

  function addAuditor(runtimeId: RuntimeId) {
    if (activeOperation) return;
    const next: ParticipantConfiguration = {
      ...configuration,
      auditors: [...configuration.auditors, {
        participantId: `auditor-${Date.now()}`,
        role: "auditor",
        order: configuration.auditors.length,
        runtimeId,
        requested: unconfiguredRequestForRuntime(catalog[runtimeId]),
        effective: null,
      }],
    };
    updateConfiguration(next);
  }

  function removeAuditor(participantId: string) {
    if (activeOperation) return;
    const next = { ...configuration, auditors: configuration.auditors.filter((auditor) => auditor.participantId !== participantId).map((auditor, order) => ({ ...auditor, order })) };
    updateConfiguration(next);
  }

  function moveAuditor(participantId: string, direction: -1 | 1) {
    if (activeOperation) return;
    const auditors = [...configuration.auditors];
    const index = auditors.findIndex((auditor) => auditor.participantId === participantId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= auditors.length) return;
    [auditors[index], auditors[target]] = [auditors[target], auditors[index]];
    updateConfiguration({ ...configuration, auditors: auditors.map((auditor, order) => ({ ...auditor, order })) });
  }

  function swapRoles(auditorId: string) {
    if (activeOperation || topicBusy) return;
    updateConfiguration(swapExecutorWithAuditor(configuration, auditorId));
  }

  async function beginRun(mode: "chat" | "review" = "chat", target?: ConversationMessage) {
    if (!activeTopicId || (mode === "chat" ? !startEnabled : !reviewEnabled || (!target && !prompt.trim()))) return;
    const reviewTarget = target ? reviewTargetForMessage(target) : null;
    if (target && !reviewTarget) return;
    const submittedPrompt = target ? "" : prompt.trim();
    const cycle = Math.max(0, ...prompts.map((item) => item.cycle)) + 1;
    setConnectionError("");
    pendingEvidenceRead.current = null;
    earlyEvidenceEvents.current.clear();
    setEvidence(null);
    setEvidenceSource("unavailable");
    setEvidenceUnavailableMessage("Evidence for the active run will be available after the run closes.");
    setActivities([]);
    setPausedAudit(null);
    if (!target) setPendingPrompt({ id: `pending:${Date.now()}`, text: submittedPrompt, cycle, created_at: new Date().toISOString() });
    runTopicIdRef.current = activeTopicId;
    setConfiguration((current) => ({ executor: { ...current.executor, effective: null }, auditors: current.auditors.map((auditor) => ({ ...auditor, effective: null })) }));
    dispatchRun({ type: "start-requested", rounds });
    setNotice("Validating runtime choices…");
    try {
      await startRun(buildRunInput(activeTopicId, submittedPrompt, rounds, configurationToWire(configuration), mode, reviewTarget ?? undefined));
      if (!target) setPrompt("");
    } catch (error) {
      const message = formatError(error);
      setPendingPrompt(null);
      dispatchRun({ type: "failed", message });
      setConnectionError(message);
      setNotice("Run did not start");
    }
  }

  async function requestStop() {
    if (!canStopRun(runState)) return;
    const runId = runState.phase === "running" ? runState.runId : undefined;
    dispatchRun({ type: "stop-requested" });
    setNotice("Stopping safely…");
    try { await stopRun({ run_id: runId }); } catch (error) {
      const message = formatError(error);
      dispatchRun({ type: "failed", message });
      setConnectionError(message);
    }
  }

  function issueCheckpointCommand(
    action: CheckpointCommandAction,
    topicId: string,
    invoke: () => Promise<string>,
    checkpointId?: string,
  ) {
    if (pendingCheckpointCommand.current) return;
    const pending: PendingCheckpointCommand = {
      action,
      topicId,
      checkpointId,
      commandId: null,
    };
    pendingCheckpointCommand.current = pending;
    earlyCheckpointEvents.current.clear();
    setCheckpointBusy(true);
    setConnectionError("");
    void bindCheckpointCommand({
      pending,
      invoke,
      isCurrent: () => pendingCheckpointCommand.current === pending,
      drainEarly: (commandId) => {
        const events = earlyCheckpointEvents.current.get(commandId) ?? [];
        earlyCheckpointEvents.current.clear();
        return events;
      },
      onEvent: (event) => ordinaryEventHandler.current(event),
      onTransportFailure: (error) => {
        if (pendingCheckpointCommand.current !== pending) return;
        pendingCheckpointCommand.current = null;
        earlyCheckpointEvents.current.clear();
        setCheckpointBusy(false);
        setConnectionError(formatError(error));
      },
    });
  }

  function requestCheckpointDraft() {
    if (!activeTopicId || activeOperation || topicBusy || previewMode || checkpointUnavailableReason) return;
    setNotice("Preparing a context checkpoint…");
    issueCheckpointCommand(
      "draft",
      activeTopicId,
      () => draftTopicCheckpoint({ topic_id: activeTopicId }),
    );
  }

  function activateCheckpoint(checkpointId: string) {
    if (!activeTopicId || activeOperation || topicBusy || previewMode) return;
    setNotice("Activating the Live-approved context checkpoint…");
    issueCheckpointCommand(
      "approve",
      activeTopicId,
      () => approveTopicCheckpoint({ topic_id: activeTopicId, checkpoint_id: checkpointId }),
      checkpointId,
    );
  }

  function restoreFullContext() {
    if (!activeTopicId || activeOperation || topicBusy || previewMode) return;
    setNotice("Restoring the full canonical topic context…");
    issueCheckpointCommand(
      "deactivate",
      activeTopicId,
      () => deactivateTopicCheckpoint({ topic_id: activeTopicId }),
    );
  }

  async function cancelCheckpointDraft() {
    if (!checkpointBusy || pendingCheckpointCommand.current?.action !== "draft" || previewMode) return;
    setNotice("Stopping checkpoint generation safely…");
    try {
      await stopRun({});
    } catch (error) {
      setConnectionError(formatError(error));
    }
  }

  async function resolvePausedAudit(resolution: "retry_failed" | "continue_without_failed") {
    if (!pausedAudit || resolvingAudit) return;
    setResolvingAudit(true);
    try { await resolveAuditFailure({ run_id: pausedAudit.run_id, failure_id: pausedAudit.failure_id, resolution }); }
    catch (error) { setResolvingAudit(false); setConnectionError(formatError(error)); }
  }

  async function decidePermission(decision: PermissionDecision) {
    const current = permissions[0];
    if (!current || permissionSubmitting) return;
    setPermissionSubmitting(true);
    setPermissionError("");
    permissionInvokeInFlight.current = true;
    try {
      const commandId = await respondToPermission({ permission_id: current.permission_id, decision });
      permissionInvokeInFlight.current = false;
      const early = earlyCommandEvents.current.get(commandId);
      if (early) {
        earlyCommandEvents.current.delete(commandId);
        if (early.event === "command.result") setPermissionError("");
        else {
          const message = stringField(early.payload, "message") || "The permission decision was not accepted; the action remained denied.";
          setPermissions((queue) => dismissPermissionRequest(queue, current.permission_id));
          setPermissionSubmitting(false);
          setPermissionError("");
          setConnectionError(message);
        }
      } else pendingPermissionCommand.current = { commandId, permissionId: current.permission_id };
    } catch (error) {
      permissionInvokeInFlight.current = false;
      setPermissionError(formatError(error));
      setPermissionSubmitting(false);
    }
  }

  return (
    <>
      <div
        className="app-shell"
        id="application-surface"
        data-sidebar-collapsed={sidebarVisibility === "collapsed"}
      >
        <TopicSidebar
          topics={topics}
          activeTopicId={activeTopicId}
          query={topicQuery}
          archivedView={archivedView}
          searchOccurrences={searchOccurrences}
          searching={searchingTopics}
          busy={topicBusy || activeOperation}
          appearance={appearance}
          collapsed={sidebarVisibility === "collapsed"}
          projects={projects}
          selectedProjectId={selectedProjectId}
          projectBusy={projectBusy}
          onAppearanceChange={setAppearance}
          onCollapsedChange={(collapsed) => setSidebarVisibility(collapsed ? "collapsed" : "expanded")}
          onQueryChange={setTopicQuery}
          onArchivedViewChange={(next) => {
            if (activeOperation || topicBusy) return;
            const view = transitionTopicView(
              { archived: archivedView, query: topicQuery, busy: topicBusy },
              next,
              previewMode,
            );
            setArchivedView(view.archived);
            setTopicQuery(view.query);
            setTopicBusy(view.busy);
          }}
          onSelect={(topicId) => void selectTopic(topicId)}
          onSelectOccurrence={(occurrence) => void selectSearchOccurrence(occurrence)}
          onProjectSelect={selectProject}
          onOpenProject={openProjectFolder}
          onNewTopic={() => void createTopic()}
          onRename={(topicId, title) => patchTopic(topicId, { title })}
          onPin={(topicId, pinned) => patchTopic(topicId, { pinned })}
          onArchive={(topicId, archived) => patchTopic(topicId, { archived })}
          onDelete={tombstoneTopic}
        />

        <section
          className="workspace"
          data-geometry="workspace"
          style={{ "--composer-overlay-height": `${composerOverlayHeight}px` } as CSSProperties}
        >
          <div className="workspace-top">
            <WorkspaceHeader
              executor={executorSeat}
              auditors={auditorSeats}
              activeRun={activeOperation}
              onSeatClick={(participantId, anchor) => setSeatPopover({ participantId, anchor })}
              onManageParticipants={() => setManageOpen(true)}
              onAddAuditor={() => setManageOpen(true)}
              onSwapRoles={swapRoles}
            />
            <TopicProjectContext
              projects={projects}
              activeTopicProjectId={activeTopic?.summary.projectId ?? null}
              activeTopic={Boolean(activeTopic)}
              disabled={activeOperation || topicBusy}
              projectBusy={projectBusy}
              onAssignTopic={assignTopicProject}
            />
          </div>

          <main className="conversation-scroll" id="app-content">
            <Conversation
              reviewDisabled={!reviewEnabled}
              reviewUnavailableReason={reviewIssues.map((issue) => issue.message).join(" ")}
              onReview={(message) => void beginRun("review", message)}
              prompts={allPrompts}
              messages={messages}
              runtimeDisplayNames={runtimeDisplayNames}
              runtimeNames={runtimeNames}
              auditOrder={configuration.auditors.map((auditor) => auditor.participantId)}
              activities={activities}
              pausedAudit={pausedAudit}
              resolvingAudit={resolvingAudit}
              onResolveAudit={(resolution) => void resolvePausedAudit(resolution)}
            />
          </main>

          <section ref={composerDockRef} className="composer-dock" aria-label="Live prompt">
            <RunStatusSurface
              persistent={persistentStatus}
              toast={toast}
              onDismissPersistent={connectionError && governanceCorePhase !== "failed" ? () => setConnectionError("") : undefined}
              onPersistentAction={governanceCorePhase === "failed" ? retryGovernanceCore : undefined}
              onDismissToast={() => setToast(null)}
            />
            <form className="live-composer" data-geometry="live-composer" onSubmit={(event) => { event.preventDefault(); void beginRun(); }}>
              <span className="live-composer__label">Live</span>
              <textarea
                value={prompt}
                disabled={activeOperation || !activeTopicId}
                rows={2}
                placeholder={activeTopicId ? "Ask a follow-up or request changes…" : "Create or select a topic to begin…"}
                aria-label="Prompt"
                onChange={(event) => setPrompt(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && startEnabled) {
                    event.preventDefault(); void beginRun();
                  }
                }}
              />
              <footer className="live-composer__footer">
                <div className="composer-tools">
                  <span className={`run-phase run-phase--${runState.phase}`}>{formatRunState(runState)}</span>
                </div>
                <div className="composer-submit-row">
                  {!activeOperation ? <button type="button" className="button button--quiet" disabled={!reviewEnabled || !prompt.trim()} title={reviewIssues.map((issue) => issue.message).join(" ") || "Proposal → independent review → synthesis"} onClick={() => void beginRun("review")}>Start full review</button> : null}
                  <span className="keyboard-hint">↵</span>
                  {activeRun ? (
                    <button className="composer-submit composer-submit--stop" type="button" disabled={!canStopRun(runState)} onClick={() => void requestStop()} aria-label="Stop the active run" title="Stop"><Square size={15} fill="currentColor" aria-hidden="true" /></button>
                  ) : checkpointCancelable ? (
                    <button className="composer-submit composer-submit--stop" type="button" onClick={() => void cancelCheckpointDraft()} aria-label="Stop checkpoint generation" title="Stop checkpoint generation"><Square size={15} fill="currentColor" aria-hidden="true" /></button>
                  ) : (
                    <button className="composer-submit" type="submit" disabled={!startEnabled} aria-label="Start dialectic" title="Start dialectic"><ArrowUp size={18} aria-hidden="true" /></button>
                  )}
                </div>
              </footer>
            </form>
            {configurationIssues.length > 0 && !previewMode ? (
              <div className="validation-summary" role="status"><strong>Start is unavailable</strong><ul>{configurationIssues.map((issue, index) => <li key={`${issue.field}-${issue.code}-${index}`}>{issue.message}</li>)}</ul></div>
            ) : null}
            <div className="composer-secondary-actions">
              <ContextCheckpointControl
                checkpoints={activeTopic?.contextCheckpoints ?? []}
                activeCheckpointId={activeTopic?.activeContextCheckpointId ?? null}
                unavailableReason={checkpointUnavailableReason}
                controlsDisabled={activeRun || checkpointBusy || topicBusy || previewMode || governanceCorePhase !== "ready" || !activeTopicId}
                busy={checkpointBusy}
                cancelable={checkpointCancelable}
                busyAction={pendingCheckpointCommand.current?.action ?? null}
                onDraft={() => void requestCheckpointDraft()}
                onActivate={(checkpointId) => void activateCheckpoint(checkpointId)}
                onDeactivate={() => void restoreFullContext()}
                onCancel={() => void cancelCheckpointDraft()}
              />
              <details className="evidence-drawer"><summary><ShieldCheck size={16} aria-hidden="true" /><span>Latest run evidence</span><ChevronDown size={14} aria-hidden="true" /></summary><EvidencePanel evidence={evidence} source={evidenceSource} unavailableMessage={evidenceUnavailableMessage} runtimeNames={Object.fromEntries(Object.values(catalog).map((entry) => [entry.runtimeId, entry.descriptor.display.name]))} /></details>
            </div>
          </section>
        </section>

        {popoverParticipant && seatPopover ? (
          <ParticipantPopover
            participant={popoverParticipant}
            catalog={catalog}
            anchor={seatPopover.anchor}
            disabled={activeOperation || topicBusy}
            onClose={() => setSeatPopover(null)}
            onRequestedChange={(field, value) => changeRequested(popoverParticipant.participantId, field, value)}
            onControlChange={(controlId, value) => changeControl(popoverParticipant.participantId, controlId, value)}
            onExecutionProfileChange={(profileId) => changeExecutionProfile(popoverParticipant.participantId, profileId)}
            onReset={() => resetParticipant(popoverParticipant.participantId)}
          />
        ) : null}

        <ParticipantManager
          open={manageOpen}
          configuration={configuration}
          catalog={catalog}
          rounds={rounds}
          disabled={activeOperation || topicBusy}
          refreshing={refreshing}
          issues={configurationIssues}
          onClose={() => setManageOpen(false)}
          onRoundsChange={(nextRounds) => updateConfiguration(configuration, nextRounds)}
          onRefresh={() => void refreshCapabilities()}
          onRuntimeChange={changeRuntime}
          onAddAuditor={addAuditor}
          onRemoveAuditor={removeAuditor}
          onMoveAuditor={moveAuditor}
        />
      </div>

      <PermissionModal request={permissions[0] ?? null} descriptor={permissions[0] ? catalog[permissions[0].runtime_id]?.descriptor : undefined} queuedCount={permissions.length} submitting={permissionSubmitting} error={permissionError} onDecision={(decision) => void decidePermission(decision)} />
    </>
  );
}

export function ContextCheckpointControl({
  checkpoints,
  activeCheckpointId,
  unavailableReason,
  controlsDisabled,
  busy,
  cancelable,
  busyAction,
  onDraft,
  onActivate,
  onDeactivate,
  onCancel,
}: {
  checkpoints: TopicContextCheckpoint[];
  activeCheckpointId: string | null;
  unavailableReason: string | null;
  controlsDisabled: boolean;
  busy: boolean;
  cancelable: boolean;
  busyAction: CheckpointCommandAction | null;
  onDraft: () => void;
  onActivate: (checkpointId: string) => void;
  onDeactivate: () => void;
  onCancel: () => void;
}) {
  const drafts = checkpoints.filter((checkpoint) => checkpoint.status === "draft");
  const active = checkpoints.find((checkpoint) => checkpoint.checkpointId === activeCheckpointId);
  const contextLabel = busy
    ? busyAction === "approve"
      ? "Context · Activating"
      : busyAction === "deactivate"
        ? "Context · Restoring"
        : "Context · Preparing"
    : active
      ? "Context · Active"
      : drafts.length > 0
        ? `Context · ${drafts.length} draft${drafts.length === 1 ? "" : "s"}`
        : "Context";
  return (
    <details className="checkpoint-control">
      <summary><Minimize2 size={16} aria-hidden="true" /><span>{contextLabel}</span><ChevronDown size={14} aria-hidden="true" /></summary>
      <section className="checkpoint-panel" aria-label="Topic context checkpoints">
        <header><strong>Compact topic context</strong><small>Original topic history remains immutable.</small></header>
        {active ? (
          <article className="checkpoint-card checkpoint-card--active">
            <strong>Active checkpoint</strong>
            <p>{active.summary}</p>
            <small>{formatBytes(active.beforeUtf8Bytes)} → {formatBytes(active.afterUtf8Bytes)} · Live approved</small>
            <CheckpointEvidence checkpoint={active} />
            <button className="button button--secondary" type="button" disabled={controlsDisabled} onClick={onDeactivate}>Restore full context</button>
          </article>
        ) : <p className="checkpoint-panel__status">Full canonical topic context is active.</p>}
        {drafts.map((checkpoint) => (
          <article className="checkpoint-card" key={checkpoint.checkpointId}>
            <strong>Draft — review before activation</strong>
            <p>{checkpoint.summary}</p>
            <small>{formatBytes(checkpoint.beforeUtf8Bytes)} → {formatBytes(checkpoint.afterUtf8Bytes)} · {checkpoint.sourceEntryCount} source entries</small>
            <CheckpointEvidence checkpoint={checkpoint} />
            <button className="button button--permission" type="button" disabled={controlsDisabled} onClick={() => onActivate(checkpoint.checkpointId)}>Approve and use</button>
          </article>
        ))}
        {busy && cancelable ? (
          <button className="button button--secondary" type="button" onClick={onCancel}>
            <Square size={13} fill="currentColor" aria-hidden="true" />Stop checkpoint generation
          </button>
        ) : busy ? (
          <p className="checkpoint-panel__status" role="status">Applying the checkpoint change…</p>
        ) : (
          <button className="button button--quiet" type="button" disabled={unavailableReason !== null} onClick={onDraft}>
            <Minimize2 size={14} aria-hidden="true" />Create checkpoint draft
          </button>
        )}
        {unavailableReason ? <p className="checkpoint-panel__eligibility" role="status">{unavailableReason}</p> : null}
        <p className="checkpoint-panel__note">Provider-native compaction events are recorded only as turn evidence; they never change this topic checkpoint.</p>
      </section>
    </details>
  );
}

function CheckpointEvidence({ checkpoint }: { checkpoint: TopicContextCheckpoint }) {
  const runtimeId = typeof checkpoint.creator.runtime_id === "string"
    ? checkpoint.creator.runtime_id
    : "Not reported";
  return (
    <details className="checkpoint-evidence">
      <summary>Checkpoint evidence</summary>
      <dl>
        <div><dt>Source range</dt><dd>{checkpoint.sourceStartAnchor} → {checkpoint.sourceEndAnchor}</dd></div>
        <div><dt>Source entries</dt><dd>{checkpoint.sourceEntryCount}</dd></div>
        <div><dt>Source SHA-256</dt><dd><code>{checkpoint.sourceDigest}</code></dd></div>
        <div><dt>Creator runtime</dt><dd>{runtimeId}</dd></div>
        <div><dt>Fresh provider turn</dt><dd>{checkpoint.creator.fresh_session === true ? "Yes" : "Not certified"}</dd></div>
        <div><dt>Created</dt><dd>{formatEvidenceTimestamp(checkpoint.createdAt)}</dd></div>
        <div><dt>Approved by Live</dt><dd>{checkpoint.approvedAt ? formatEvidenceTimestamp(checkpoint.approvedAt) : "Not yet"}</dd></div>
      </dl>
    </details>
  );
}

function configurationToWire(configuration: ParticipantConfiguration): TopicParticipantInput[] {
  return [configuration.executor, ...configuration.auditors]
    .sort((left, right) => left.role === right.role ? left.order - right.order : left.role === "executor" ? -1 : 1)
    .map((participant) => ({
      participant_id: participant.participantId,
      role: participant.role,
      order: participant.order,
      runtime_id: participant.runtimeId,
      requested: {
        model: participant.requested.model,
        effort: participant.requested.effort,
        service_tier: participant.requested.serviceTier,
        controls: participant.requested.controls,
        execution_profile: participant.requested.executionProfile ? {
          profile_id: participant.requested.executionProfile.profileId,
          values: participant.requested.executionProfile.values,
        } : undefined,
      },
    }));
}

function configurationFromWire(participants: TopicParticipantInput[]): ParticipantConfiguration {
  const executor = participants.find((participant) => participant.role === "executor");
  const auditors = participants.filter((participant) => participant.role === "auditor").sort((a, b) => a.order - b.order);
  if (!executor) return createDefaultParticipantConfiguration();
  return {
    executor: participantFromWire(executor),
    auditors: auditors.map(participantFromWire),
  };
}

function participantFromWire(participant: TopicParticipantInput): Participant {
  return {
    participantId: participant.participant_id,
    role: participant.role,
    order: participant.order,
    runtimeId: participant.runtime_id,
    requested: {
      model: participant.requested.model,
      effort: participant.requested.effort,
      serviceTier: participant.requested.service_tier,
      controls: participant.requested.controls,
      executionProfile: participant.requested.execution_profile ? {
        profileId: participant.requested.execution_profile.profile_id,
        values: participant.requested.execution_profile.values,
      } : undefined,
    },
    effective: null,
  };
}

function mapParticipant(
  configuration: ParticipantConfiguration,
  participantId: string | undefined,
  fallbackRole: Participant["role"] | undefined,
  update: (participant: Participant) => Participant,
): ParticipantConfiguration {
  if (participantId === configuration.executor.participantId || (!participantId && fallbackRole === "executor")) {
    return { ...configuration, executor: update(configuration.executor) };
  }
  return {
    ...configuration,
    auditors: configuration.auditors.map((auditor) => auditor.participantId === participantId || (!participantId && fallbackRole === "auditor" && configuration.auditors.length === 1) ? update(auditor) : auditor),
  };
}

function findParticipant(configuration: ParticipantConfiguration, participantId: string): Participant | null {
  return configuration.executor.participantId === participantId ? configuration.executor : configuration.auditors.find((auditor) => auditor.participantId === participantId) ?? null;
}


function formatRunState(state: RunState): string {
  switch (state.phase) {
    case "idle": return "Ready";
    case "starting": return "Starting";
    case "running": return `Round ${state.currentRound} of ${state.rounds}`;
    case "stopping": return "Stopping";
    case "stopped": return state.reason === "plan-warning" ? "Stopped for plan warning" : "Stopped";
    case "completed": return "Completed";
    case "failed": return "Failed safely";
  }
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function safeLocalStorage(): Storage | null {
  try {
    return typeof globalThis.localStorage === "undefined" ? null : globalThis.localStorage;
  } catch {
    return null;
  }
}

function browserSystemAppearance(): EffectiveAppearance {
  return globalThis.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function browserAccessibilityDisplayState(): AccessibilityDisplayState {
  return {
    increaseContrast: Boolean(globalThis.matchMedia?.("(prefers-contrast: more)").matches),
    reduceTransparency: Boolean(globalThis.matchMedia?.("(prefers-reduced-transparency: reduce)").matches),
    differentiateWithoutColor: false,
    reduceMotion: Boolean(globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches),
  };
}

function seatSummary(participant: Participant, catalog: CapabilityCatalog, activity?: ParticipantActivity): SeatSummary {
  const capabilities = catalog[participant.runtimeId];
  const model = capabilities?.models.find((candidate) => candidate.id === participant.requested.model);
  const effort = model?.efforts.find((candidate) => candidate.id === participant.requested.effort);
  const tier = serviceTierOptions(model?.serviceTiers ?? []).find((candidate) => candidate.id === participant.requested.serviceTier && candidate.id !== NATIVE_DEFAULT_SERVICE_TIER);
  const modelLabel = model?.label ?? (participant.requested.model || "Select model");
  const effortLabel = model?.efforts.length
    ? effort?.label ?? "Select effort"
    : undefined;
  return {
    id: participant.participantId,
    runtimeId: participant.runtimeId,
    agentSystem: capabilities?.descriptor.display.name ?? participant.runtimeId,
    modelLine: [modelLabel, effortLabel, tier?.label].filter(Boolean).join(" · "),
    activity: activity ? { status: activity.status, label: shortActivityLabel(activity), nativeSummary: activity.native_summary } : undefined,
  };
}

function latestActivity(activities: ParticipantActivity[], participantId: string): ParticipantActivity | undefined {
  return [...activities].reverse().find((activity) => activity.participant_id === participantId && activity.status !== "completed");
}

function shortActivityLabel(activity: ParticipantActivity): string {
  if (activity.status === "paused") return "Paused for Live";
  if (activity.status === "failed") return "Failed safely";
  if (activity.stage === "answer") return "Answering…";
  if (activity.stage === "proposal") return "Proposing…";
  if (activity.stage === "audit") return "Reviewing…";
  return "Synthesizing…";
}

function seatInlineLabel(seat: SeatSummary): string {
  return `${seat.agentSystem} · ${seat.modelLine}`;
}

function focusSearchAnchor(anchor: string): void {
  const nodes = document.querySelectorAll<HTMLElement>("[data-source-anchor]");
  const target = [...nodes].find((node) => node.dataset.sourceAnchor === anchor);
  if (!target) return;
  target.scrollIntoView({ block: "center", behavior: "smooth" });
  target.classList.add("search-target");
  target.focus({ preventScroll: true });
  globalThis.setTimeout(() => target.classList.remove("search-target"), 2_400);
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(value < 10_240 ? 1 : 0)} KB`;
}

function formatEvidenceTimestamp(value?: string): string {
  if (!value) return "Not reported";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function upsertTopic(topics: TopicSummary[], next: TopicSummary): TopicSummary[] {
  return topics.some((topic) => topic.id === next.id) ? topics.map((topic) => topic.id === next.id ? next : topic) : [next, ...topics];
}

function eventMatchesTopic(
  payload: Record<string, unknown>,
  activeTopicId: string | null,
  runTopicId: string | null,
): boolean {
  const eventTopicId = typeof payload.topic_id === "string" ? payload.topic_id : runTopicId;
  return Boolean(activeTopicId && eventTopicId && eventTopicId === activeTopicId);
}

const PREVIEW_CATALOG: CapabilityCatalog = {
  codex: {
    runtimeId: "codex",
    descriptor: previewDescriptor("codex", "openai", "codex", "Codex", "X", "blue", "gpt-5.6-sol", "ultra"),
    availability: { available: true },
    accountRoute: "chatgpt:plus",
    runtimeVersion: "0.145.0",
    models: [{
      id: "gpt-5.6-sol",
      label: "GPT-5.6 Sol",
      description: "Codex model advertised by the local runtime",
      availability: { available: true },
      efforts: [{ id: "ultra", label: "Ultra", availability: { available: true } }],
      serviceTiers: [{ id: NATIVE_DEFAULT_SERVICE_TIER, label: "Standard", availability: { available: true } }],
    }],
  },
  "claude-code": {
    runtimeId: "claude-code",
    descriptor: previewDescriptor("claude-code", "anthropic", "claude-code", "Claude Code", "C", "amber", "opus", "xhigh", true),
    availability: { available: true },
    accountRoute: "claude.ai:firstParty:pro",
    runtimeVersion: "claude-code 2.1.220",
    models: [{
      id: "opus",
      label: "Opus",
      description: "Best for everyday, complex tasks",
      availability: { available: true },
      efforts: [{ id: "xhigh", label: "Extra high", availability: { available: true } }],
      serviceTiers: [],
    }],
  },
};

function previewDescriptor(
  runtimeId: string,
  vendorId: string,
  agentSystemId: string,
  name: string,
  mark: string,
  accentToken: string,
  model: string,
  effort: string,
  withThinking = false,
): ProviderDescriptor {
  return {
    schemaVersion: 1,
    descriptorVersion: 1,
    runtimeId,
    vendorId,
    agentSystemId,
    relayProviderId: runtimeId,
    display: { name, shortName: name, mark, iconToken: "terminal", accentToken },
    authentication: { label: "Subscription route", authority: "preview", notObservableLabel: "Not observable" },
    versionEvidence: { label: "Runtime version", authority: "preview", notObservableLabel: "Not observable" },
    defaultSelection: { model, effort, serviceTier: NATIVE_DEFAULT_SERVICE_TIER, executionProfile: "inherit-native" },
    controlSchema: withThinking ? [{
      controlId: "thinking",
      label: "Thinking",
      group: "turn",
      kind: "select",
      description: "Native adaptive thinking control.",
      authority: "preview",
      defaultValue: "adaptive",
      options: [
        { value: "adaptive", label: "On (adaptive)", availability: { available: true } },
        { value: "disabled", label: "Off", availability: { available: true } },
      ],
      minValue: null,
      maxValue: null,
    }] : [],
    supportedContentTypes: ["markdown"],
    executionProfiles: [{ profileId: "inherit-native", label: "Inherit native settings", description: "Use native settings.", availability: { available: true }, values: {} }],
    runtimeFacilities: [],
    permissionPresentations: [],
    connect: { label: `Connect ${name}`, helpText: `Authenticate ${name}, then refresh choices.`, action: "refresh-capabilities" },
  };
}

const PREVIEW_PARTICIPANTS = configurationToWire(reconcileConfiguration(createDefaultParticipantConfiguration(), PREVIEW_CATALOG));
const PREVIEW_NOW = "2026-08-03T03:25:00Z";
const PREVIEW_PROJECTS: ProjectSummary[] = [
  { id: "project-dialektike", name: "dialektike", available: true, registeredAt: PREVIEW_NOW },
];
const PREVIEW_DETAIL: TopicDetail = {
  summary: { id: "api-rate-limit", title: "API rate limit strategy", pinned: true, archived: false, created_at: PREVIEW_NOW, updated_at: PREVIEW_NOW, projectId: "project-dialektike" },
  rounds: 1,
  participants: PREVIEW_PARTICIPANTS,
  prompts: [{ id: "preview:prompt", text: "Design a secure, rate-limited API endpoint for password reset requests.", cycle: 1, created_at: PREVIEW_NOW }],
  messages: [
    { id: "preview:proposal", participant_id: "executor-1", role: "executor", runtime_id: "codex", stage: "proposal", text: "I’ll design a secure, rate-limited `POST /v1/auth/password-reset` endpoint.\n\n### Key points\n\n- Uniform response to prevent enumeration\n- Single-use token, expiring in 15 minutes\n- Per-IP and per-email throttling", cycle: 1, round: 1, created_at: PREVIEW_NOW, token_count: 1142 },
    { id: "preview:audit", participant_id: "auditor-1", role: "auditor", runtime_id: "claude-code", stage: "audit", verdict: "challenge", text: "**CHALLENGE**\n\nTighten the IP rate limit and add email-domain throttling. Require token invalidation on successful reset and log only a token hash for forensics.", cycle: 1, round: 1, created_at: PREVIEW_NOW, token_count: 382 },
    { id: "preview:synthesis", participant_id: "executor-1", role: "executor", runtime_id: "codex", stage: "synthesis", text: "I’ll incorporate the review: reduce IP throttling, add domain-level limits, invalidate tokens on use, and log token hashes only.", cycle: 1, round: 1, created_at: PREVIEW_NOW, token_count: 605 },
  ],
  contextCheckpoints: [],
  activeContextCheckpointId: null,
};

const PREVIEW_TOPICS: TopicSummary[] = [
  PREVIEW_DETAIL.summary,
  { id: "onboarding", title: "Rewriting onboarding flow", pinned: true, archived: false, updated_at: "2026-08-02T03:25:00Z", projectId: "project-dialektike" },
  { id: "retention", title: "Data retention policy", pinned: false, archived: false, updated_at: "2026-08-01T03:25:00Z", projectId: null },
  { id: "archived-pricing", title: "Pricing experiment design", pinned: false, archived: true, updated_at: "2026-07-24T03:25:00Z", projectId: null },
];

function previewDetailFor(topicId: string): TopicDetail {
  if (topicId === PREVIEW_DETAIL.summary.id) return PREVIEW_DETAIL;
  const summary = PREVIEW_TOPICS.find((topic) => topic.id === topicId) ?? { id: topicId, title: "Untitled topic", pinned: false, archived: false, projectId: null };
  return { summary, rounds: 1, participants: PREVIEW_PARTICIPANTS, prompts: [], messages: [], contextCheckpoints: [], activeContextCheckpointId: null };
}

function previewSearch(query: string): TopicSearchOccurrence[] {
  const needle = query.normalize("NFKC").toLocaleLowerCase();
  const documents = [
    { topic: PREVIEW_DETAIL.summary, sourceKind: "title", sourceAnchor: `topic:${PREVIEW_DETAIL.summary.id}:title`, stage: undefined, text: PREVIEW_DETAIL.summary.title },
    ...PREVIEW_DETAIL.prompts.map((prompt) => ({ topic: PREVIEW_DETAIL.summary, sourceKind: "live_prompt", sourceAnchor: prompt.id, stage: "prompt", text: prompt.text })),
    ...PREVIEW_DETAIL.messages.map((message) => ({ topic: PREVIEW_DETAIL.summary, sourceKind: "message", sourceAnchor: message.id, stage: message.stage, text: message.text })),
  ];
  return documents.flatMap((document, index) => {
    const normalized = document.text.normalize("NFKC").toLocaleLowerCase();
    const start = normalized.indexOf(needle);
    if (start < 0) return [];
    const end = Math.min(document.text.length, start + query.length);
    return [{
      occurrenceId: `preview:${index}:${start}`,
      topicId: document.topic.id,
      topicTitle: document.topic.title,
      archived: document.topic.archived,
      sourceKind: document.sourceKind,
      sourceAnchor: document.sourceAnchor,
      sourceField: "text",
      stage: document.stage,
      matchStartUtf8: new TextEncoder().encode(document.text.slice(0, start)).length,
      matchEndUtf8: new TextEncoder().encode(document.text.slice(0, end)).length,
      prefixTruncated: start > 0,
      suffixTruncated: end < document.text.length,
      segments: [
        { text: document.text.slice(Math.max(0, start - 56), start), highlighted: false },
        { text: document.text.slice(start, end), highlighted: true },
        { text: document.text.slice(end, Math.min(document.text.length, end + 72)), highlighted: false },
      ].filter((segment) => segment.text.length > 0),
    } satisfies TopicSearchOccurrence];
  });
}
