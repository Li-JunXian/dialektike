import { AlertTriangle, Folder, FolderOpen, FolderPlus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT,
  type ProjectSummary,
} from "../protocol/messages";

export const GENERAL_PROJECT_ID = "";

export interface ProjectSelectionProps {
  projects: ProjectSummary[];
  selectedProjectId: string | null;
  activeTopicProjectId: string | null;
  activeTopic: boolean;
  disabled?: boolean;
  projectBusy?: boolean;
  onSelectProject: (projectId: string | null) => void;
  onOpenFolder: () => void;
  onAssignTopic: (projectId: string | null) => void;
}

export function ProjectSidebarSection({
  projects,
  selectedProjectId,
  disabled = false,
  projectBusy = false,
  onSelectProject,
  onOpenFolder,
}: Pick<
  ProjectSelectionProps,
  | "projects"
  | "selectedProjectId"
  | "disabled"
  | "projectBusy"
  | "onSelectProject"
  | "onOpenFolder"
>) {
  const [disclosureOpen, setDisclosureOpen] = useState(false);
  const cancelButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (disclosureOpen) cancelButton.current?.focus();
  }, [disclosureOpen]);

  return (
    <>
      <section className="project-sidebar-section" aria-labelledby="project-sidebar-heading">
        <header>
          <h2 id="project-sidebar-heading">Projects</h2>
          <button
            className="sidebar-icon-button project-add-button"
            type="button"
            aria-label="Open folder as a Project"
            title="Open folder as a Project"
            disabled={disabled || projectBusy}
            onClick={() => setDisclosureOpen(true)}
          >
            <FolderPlus size={15} aria-hidden="true" />
          </button>
        </header>
        <nav className="project-sidebar-list" aria-label="Project filters">
          <ProjectFilterButton
            name="General"
            detail="Topics without a folder"
            selected={selectedProjectId === null}
            disabled={disabled || projectBusy}
            onClick={() => onSelectProject(null)}
          />
          {projects.map((project) => (
            <ProjectFilterButton
              key={project.id}
              name={project.name}
              detail={project.available ? "Folder workspace" : "Folder unavailable"}
              selected={selectedProjectId === project.id}
              available={project.available}
              disabled={disabled || projectBusy}
              onClick={() => onSelectProject(project.id)}
            />
          ))}
        </nav>
        <button
          className="project-open-folder-button"
          type="button"
          disabled={disabled || projectBusy}
          onClick={() => setDisclosureOpen(true)}
        >
          <FolderPlus size={14} aria-hidden="true" />
          <span>{projectBusy ? "Opening folder…" : "Open Folder"}</span>
        </button>
      </section>

      {disclosureOpen ? (
        <div className="project-disclosure-backdrop" role="presentation">
          <section
            className="project-disclosure"
            role="dialog"
            aria-modal="true"
            aria-labelledby="project-disclosure-title"
            aria-describedby="project-disclosure-copy"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                setDisclosureOpen(false);
              }
            }}
          >
            <header>
              <span className="project-disclosure__icon" aria-hidden="true">
                <AlertTriangle size={18} />
              </span>
              <div>
                <p className="eyebrow">Folder workspace</p>
                <h2 id="project-disclosure-title">Open a folder as a Project?</h2>
              </div>
              <button
                className="icon-button"
                type="button"
                aria-label="Close Project disclosure"
                onClick={() => setDisclosureOpen(false)}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </header>
            <p id="project-disclosure-copy">{PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT}</p>
            <p className="project-disclosure__note">
              Dialektikḗ will ask macOS for an existing folder. Canceling the folder chooser changes nothing.
            </p>
            <footer>
              <button
                ref={cancelButton}
                className="button button--secondary"
                type="button"
                onClick={() => setDisclosureOpen(false)}
              >
                Cancel
              </button>
              <button
                className="button button--permission"
                type="button"
                onClick={() => {
                  setDisclosureOpen(false);
                  onOpenFolder();
                }}
              >
                <FolderOpen size={14} aria-hidden="true" />
                Choose folder…
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}

export function TopicProjectContext({
  projects,
  activeTopicProjectId,
  activeTopic,
  disabled = false,
  projectBusy = false,
  onAssignTopic,
}: Pick<
  ProjectSelectionProps,
  | "projects"
  | "activeTopicProjectId"
  | "activeTopic"
  | "disabled"
  | "projectBusy"
  | "onAssignTopic"
>) {
  if (!activeTopic) return null;
  const project = activeTopicProjectId
    ? projects.find((candidate) => candidate.id === activeTopicProjectId)
    : undefined;

  return (
    <section className="topic-project-context" aria-label="Current topic Project">
      <Folder size={14} aria-hidden="true" />
      <div className="topic-project-context__copy">
        <strong>{project?.name ?? (activeTopicProjectId ? "Unavailable Project" : "General")}</strong>
        <small>
          {project
            ? project.available
              ? "Participants use this folder as their working directory"
              : "This folder is unavailable; runs will fail closed"
            : activeTopicProjectId
              ? "The saved Project could not be loaded"
              : "This topic is not linked to a folder"}
        </small>
      </div>
      <label className="topic-project-context__selector">
        <span className="sr-only">Project for current topic</span>
        <select
          aria-label="Project for current topic"
          value={activeTopicProjectId ?? GENERAL_PROJECT_ID}
          disabled={disabled || projectBusy}
          onChange={(event) => onAssignTopic(event.currentTarget.value || null)}
        >
          <option value={GENERAL_PROJECT_ID}>General · no folder</option>
          {projects.map((candidate) => (
            <option
              key={candidate.id}
              value={candidate.id}
              disabled={!candidate.available && candidate.id !== activeTopicProjectId}
            >
              {candidate.name}{candidate.available ? "" : " · unavailable"}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}

function ProjectFilterButton({
  name,
  detail,
  selected,
  available = true,
  disabled,
  onClick,
}: {
  name: string;
  detail: string;
  selected: boolean;
  available?: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={`project-filter ${selected ? "project-filter--selected" : ""}`}
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
    >
      <Folder size={15} aria-hidden="true" />
      <span>
        <strong>{name}</strong>
        <small>{detail}</small>
      </span>
      {!available ? <AlertTriangle size={13} aria-label="Folder unavailable" /> : null}
    </button>
  );
}
