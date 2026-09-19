import {
  Archive,
  ArchiveRestore,
  Check,
  MessageCircle,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pin,
  Plus,
  Search,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import type { ProjectSummary, TopicSearchOccurrence, TopicSummary } from "../protocol/messages";
import type { AppearancePreference } from "../state/appearance";
import { AppearanceControl } from "./AppearanceControl";
import { ProjectSidebarSection } from "./ProjectControls";
import { TopicOverflowMenu, topicMenuDomId } from "./TopicOverflowMenu";

export type { TopicSummary } from "../protocol/messages";

interface TopicSidebarProps {
  topics: TopicSummary[];
  activeTopicId: string | null;
  query: string;
  archivedView: boolean;
  searchOccurrences?: TopicSearchOccurrence[];
  searching?: boolean;
  busy?: boolean;
  appearance?: AppearancePreference;
  collapsed?: boolean;
  projects?: ProjectSummary[];
  selectedProjectId?: string | null;
  projectBusy?: boolean;
  onQueryChange: (value: string) => void;
  onSelect: (topicId: string) => void;
  onSelectOccurrence?: (occurrence: TopicSearchOccurrence) => void;
  onNewTopic: () => void;
  onArchivedViewChange: (archived: boolean) => void;
  onRename: (topicId: string, title: string) => void;
  onPin: (topicId: string, pinned: boolean) => void;
  onArchive: (topicId: string, archived: boolean) => void;
  onDelete: (topicId: string) => void;
  onAppearanceChange?: (appearance: AppearancePreference) => void;
  onCollapsedChange?: (collapsed: boolean) => void;
  onProjectSelect?: (projectId: string | null) => void;
  onOpenProject?: () => void;
}

interface OpenTopicMenu {
  topic: TopicSummary;
  anchor: HTMLButtonElement;
}

export function TopicSidebar({
  topics,
  activeTopicId,
  query,
  archivedView,
  searchOccurrences = [],
  searching = false,
  busy = false,
  appearance = "system",
  collapsed = false,
  projects = [],
  selectedProjectId = null,
  projectBusy = false,
  onQueryChange,
  onSelect,
  onSelectOccurrence = () => undefined,
  onNewTopic,
  onArchivedViewChange,
  onRename,
  onPin,
  onArchive,
  onDelete,
  onAppearanceChange = () => undefined,
  onCollapsedChange = () => undefined,
  onProjectSelect = () => undefined,
  onOpenProject = () => undefined,
}: TopicSidebarProps) {
  const [openMenu, setOpenMenu] = useState<OpenTopicMenu | null>(null);
  const [renaming, setRenaming] = useState<TopicSummary | null>(null);
  const [deleting, setDeleting] = useState<TopicSummary | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const renameInput = useRef<HTMLInputElement>(null);
  const deleteCancel = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (renaming) {
      renameInput.current?.focus();
      renameInput.current?.select();
    }
  }, [renaming]);

  useEffect(() => {
    if (deleting) {
      deleteCancel.current?.focus();
    }
  }, [deleting]);

  useEffect(() => {
    if (busy) {
      setOpenMenu(null);
      setRenaming(null);
      setDeleting(null);
    }
  }, [busy]);

  useEffect(() => {
    if (collapsed) {
      setOpenMenu(null);
      setRenaming(null);
      setDeleting(null);
    }
  }, [collapsed]);

  const visible = topics
    .filter((topic) => topic.archived === archivedView)
    .filter((topic) => topic.projectId === selectedProjectId);
  const pinned = visible.filter((topic) => topic.pinned);
  const recent = visible.filter((topic) => !topic.pinned);
  const occurrenceGroups = groupOccurrencesByTopic(searchOccurrences.slice(0, 100));

  function beginRename(topic: TopicSummary) {
    setOpenMenu(null);
    setRenaming(topic);
    setRenameValue(topic.title);
  }

  function submitRename() {
    if (!renaming) {
      return;
    }
    const title = renameValue.trim();
    if (title && title !== renaming.title) {
      onRename(renaming.id, title);
    }
    setRenaming(null);
  }

  return (
    <aside
      className={`topic-sidebar ${collapsed ? "topic-sidebar--collapsed" : ""}`}
      aria-label="Topic sidebar"
      data-sidebar-visibility={collapsed ? "collapsed" : "expanded"}
    >
      <div className="topic-sidebar__header">
        {collapsed ? null : (
          <div className="wordmark" aria-label="Dialektikḗ">
            dialektikḗ
          </div>
        )}
        <button
          className="sidebar-collapse-button"
          type="button"
          aria-label={collapsed ? "Expand topic sidebar" : "Collapse topic sidebar"}
          aria-controls="topic-navigation"
          aria-expanded={!collapsed}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => onCollapsedChange(!collapsed)}
        >
          {collapsed
            ? <PanelLeftOpen size={18} aria-hidden="true" />
            : <PanelLeftClose size={18} aria-hidden="true" />}
        </button>
      </div>

      <button
        className="new-topic-button"
        type="button"
        aria-label="New topic"
        title={collapsed ? "New topic" : undefined}
        onClick={onNewTopic}
        disabled={busy}
      >
        <Plus size={17} aria-hidden="true" />
        <span className={collapsed ? "sr-only" : undefined}>New Topic</span>
      </button>

      <label className="topic-search">
        <Search size={16} aria-hidden="true" />
        <span className="sr-only">Search topics</span>
        <input
          type="search"
          value={query}
          placeholder={archivedView ? "Search archived…" : "Search topics…"}
          disabled={busy}
          onChange={(event) => onQueryChange(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape" && query) {
              event.preventDefault();
              onQueryChange("");
            }
          }}
        />
        <kbd>⌘K</kbd>
      </label>

      <ProjectSidebarSection
        projects={projects}
        selectedProjectId={selectedProjectId}
        disabled={busy}
        projectBusy={projectBusy}
        onSelectProject={onProjectSelect}
        onOpenFolder={onOpenProject}
      />

      {query.trim() ? (
        <section className="topic-search-results" aria-label="Search results">
          <header>
            <strong>{searching ? "Searching…" : `${searchOccurrences.length} occurrence${searchOccurrences.length === 1 ? "" : "s"}`}</strong>
            <button className="icon-button" type="button" aria-label="Close search results" onClick={() => onQueryChange("")}><X size={14} aria-hidden="true" /></button>
          </header>
          <div role="listbox" aria-label="Matching topic content">
            {occurrenceGroups.map((group) => (
              <section className="topic-search-results__group" role="group" aria-label={group.title} key={group.topicId}>
                <header>
                  <strong>{group.title}</strong>
                  {group.archived ? <small>Archived</small> : null}
                </header>
                {group.occurrences.map((occurrence) => (
                  <button
                    key={occurrence.occurrenceId}
                    type="button"
                    role="option"
                    aria-selected="false"
                    disabled={busy}
                    onClick={() => onSelectOccurrence(occurrence)}
                  >
                    <span className="topic-search-results__heading">
                      <strong>{occurrence.speaker || stageLabel(occurrence)}</strong>
                      <small>{[stageLabel(occurrence), formatSearchTimestamp(occurrence.timestamp)].filter(Boolean).join(" · ")}</small>
                    </span>
                    <span className="topic-search-results__snippet">
                      {occurrence.prefixTruncated ? "…" : ""}
                      {occurrence.segments.map((segment, index) => segment.highlighted
                        ? <mark key={index}>{segment.text}</mark>
                        : <span key={index}>{segment.text}</span>)}
                      {occurrence.suffixTruncated ? "…" : ""}
                    </span>
                  </button>
                ))}
              </section>
            ))}
            {!searching && searchOccurrences.length === 0 ? <p>No matching topic content</p> : null}
          </div>
        </section>
      ) : null}

      <nav id="topic-navigation" className="topic-navigation" aria-label={archivedView ? "Archived topics" : "Topics"}>
        {archivedView ? (
          <TopicGroup
            label="Archived"
            icon={<Archive size={15} aria-hidden="true" />}
            topics={visible}
            activeTopicId={activeTopicId}
            openMenuId={openMenu?.topic.id ?? null}
            onOpenMenu={setOpenMenu}
            onSelect={onSelect}
            disabled={busy}
          />
        ) : (
          <>
            {pinned.length > 0 ? (
              <TopicGroup
                label="Pinned"
                icon={<Pin size={15} aria-hidden="true" />}
                topics={pinned}
                activeTopicId={activeTopicId}
                openMenuId={openMenu?.topic.id ?? null}
                onOpenMenu={setOpenMenu}
                onSelect={onSelect}
                disabled={busy}
              />
            ) : null}

            <div className="topic-divider" />

            <TopicGroup
              label="Recent"
              topics={recent}
              activeTopicId={activeTopicId}
              openMenuId={openMenu?.topic.id ?? null}
              onOpenMenu={setOpenMenu}
              onSelect={onSelect}
              disabled={busy}
            />
          </>
        )}
      </nav>

      <div className="topic-sidebar__footer">
        <button
          type="button"
          className={`sidebar-footer-button ${archivedView ? "sidebar-footer-button--active" : ""}`}
          disabled={busy}
          onClick={() => {
            setOpenMenu(null);
            onArchivedViewChange(!archivedView);
          }}
          aria-pressed={archivedView}
        >
          {archivedView ? (
            <ArchiveRestore size={16} aria-hidden="true" />
          ) : (
            <Archive size={16} aria-hidden="true" />
          )}
          <span className={collapsed ? "sr-only" : undefined}>{archivedView ? "Back to Topics" : "Archived"}</span>
        </button>
        <AppearanceControl value={appearance} onChange={onAppearanceChange} />
      </div>

      {openMenu ? (
        <TopicOverflowMenu
          topic={openMenu.topic}
          anchor={openMenu.anchor}
          onClose={(restoreFocus) => {
            const anchor = openMenu.anchor;
            setOpenMenu(null);
            if (restoreFocus) globalThis.setTimeout(() => anchor.focus(), 0);
          }}
          onRename={beginRename}
          onPin={onPin}
          onArchive={onArchive}
          onDelete={(topic) => {
            setDeleting(topic);
          }}
        />
      ) : null}

      {renaming ? (
        <div className="sidebar-dialog-backdrop" role="presentation">
          <form
            className="sidebar-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="rename-topic-title"
            onSubmit={(event) => {
              event.preventDefault();
              submitRename();
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                setRenaming(null);
              }
            }}
          >
            <label>
              <span id="rename-topic-title">Rename topic</span>
              <input
                ref={renameInput}
                value={renameValue}
                maxLength={160}
                onChange={(event) => setRenameValue(event.currentTarget.value)}
              />
            </label>
            <div>
              <button type="button" className="icon-button" aria-label="Cancel rename" onClick={() => setRenaming(null)}>
                <X size={16} aria-hidden="true" />
              </button>
              <button type="submit" className="icon-button" aria-label="Save topic name" disabled={!renameValue.trim()}>
                <Check size={16} aria-hidden="true" />
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {deleting ? (
        <div className="sidebar-dialog-backdrop" role="presentation">
          <section
            className="sidebar-dialog sidebar-delete-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-topic-title"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                setDeleting(null);
              }
            }}
          >
            <h2 id="delete-topic-title">Delete “{deleting.title}”?</h2>
            <p>The topic will be removed from Dialektikḗ. Immutable owner-only governance evidence is retained.</p>
            <div>
              <button ref={deleteCancel} type="button" className="button button--secondary" onClick={() => setDeleting(null)}>Cancel</button>
              <button type="button" className="button button--danger" onClick={() => {
                onDelete(deleting.id);
                setDeleting(null);
              }}>Delete topic</button>
            </div>
          </section>
        </div>
      ) : null}
    </aside>
  );
}

function TopicGroup({
  label,
  icon,
  topics,
  activeTopicId,
  openMenuId,
  onOpenMenu,
  onSelect,
  disabled,
}: {
  label: string;
  icon?: ReactNode;
  topics: TopicSummary[];
  activeTopicId: string | null;
  openMenuId: string | null;
  onOpenMenu: (menu: OpenTopicMenu | null) => void;
  onSelect: (topicId: string) => void;
  disabled: boolean;
}) {
  return (
    <section className="topic-group" aria-labelledby={`topics-${label.toLocaleLowerCase()}`}>
      <h2 id={`topics-${label.toLocaleLowerCase()}`}>
        {icon}
        {label}
      </h2>
      <div className="topic-list">
        {topics.length > 0 ? (
          topics.map((topic) => {
            const active = topic.id === activeTopicId;
            return (
              <div
                className={`topic-item ${active ? "topic-item--active" : ""}`}
                data-source-anchor={`topic:${topic.id}:title`}
                key={topic.id}
              >
                <button
                  className="topic-item__select"
                  type="button"
                  aria-current={active ? "page" : undefined}
                  disabled={disabled}
                  onClick={() => onSelect(topic.id)}
                >
                  <span className="topic-item__icon" aria-hidden="true">
                    {topic.pinned ? <Pin size={14} /> : <MessageCircle size={15} />}
                  </span>
                  <span className="topic-item__copy">
                    <strong>{topic.title}</strong>
                    <small>{topic.active_run ? "Active run" : relativeTime(topic.updated_at ?? topic.created_at)}</small>
                  </span>
                </button>
                <button
                  type="button"
                  className="topic-item__menu-button"
                  aria-label={`Actions for ${topic.title}`}
                  aria-haspopup="menu"
                  aria-expanded={openMenuId === topic.id}
                  aria-controls={openMenuId === topic.id ? topicMenuDomId(topic.id) : undefined}
                  disabled={disabled}
                  onClick={(event) => onOpenMenu(openMenuId === topic.id ? null : { topic, anchor: event.currentTarget })}
                >
                  <MoreHorizontal size={16} aria-hidden="true" />
                </button>
              </div>
            );
          })
        ) : (
          <p className="topic-empty">{label === "Archived" ? "No archived topics" : "No matching topics"}</p>
        )}
      </div>
    </section>
  );
}

function relativeTime(value?: string): string {
  if (!value) {
    return "Saved locally";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const difference = Date.now() - date.getTime();
  if (difference < 60_000) {
    return "Just now";
  }
  if (difference < 3_600_000) {
    return `${Math.max(1, Math.floor(difference / 60_000))} min ago`;
  }
  if (difference < 86_400_000) {
    return `${Math.floor(difference / 3_600_000)} hr ago`;
  }
  if (difference < 172_800_000) {
    return "Yesterday";
  }
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function groupOccurrencesByTopic(occurrences: TopicSearchOccurrence[]): Array<{
  topicId: string;
  title: string;
  archived: boolean;
  occurrences: TopicSearchOccurrence[];
}> {
  const groups = new Map<string, {
    topicId: string;
    title: string;
    archived: boolean;
    occurrences: TopicSearchOccurrence[];
  }>();
  for (const occurrence of occurrences) {
    const group = groups.get(occurrence.topicId) ?? {
      topicId: occurrence.topicId,
      title: occurrence.topicTitle,
      archived: occurrence.archived,
      occurrences: [],
    };
    group.occurrences.push(occurrence);
    groups.set(occurrence.topicId, group);
  }
  return [...groups.values()];
}

function stageLabel(occurrence: TopicSearchOccurrence): string {
  return (occurrence.stage ?? occurrence.sourceKind).replaceAll("_", " ");
}

function formatSearchTimestamp(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}
