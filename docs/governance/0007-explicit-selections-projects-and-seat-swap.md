# Governance record 0007 — explicit selections, Projects, and seat swapping

Date: 2026-08-21

Authority: Live (arbiter)

## Ruling

Live removed preselected model and effort defaults from the Dialektikḗ desktop
workflow, requested a quick Executor↔Auditor swap, approved folder-bound
Projects for focused work, and approved a narrower collapsible topic sidebar.
This record supersedes only the default requested profiles in governance 0005;
it does not rewrite that historical decision or weaken its capability-truth
rules.

## Explicit participant choices

- The initial Codex and Claude Code seats have no selected model or effort.
  Creating a topic persists that honest incomplete state. Starting a run fails
  closed until Live chooses one concrete runtime-advertised model for every
  seat and, when that model advertises efforts, one compatible effort.
- Resetting a seat or changing its runtime clears model and effort. Selecting a
  model also leaves effort unset for a separate explicit choice. A model that
  advertises no effort selector requires none; Dialektikḗ does not invent one.
- A runtime pseudo-option such as `Default (recommended)` is not a concrete
  model version. It may remain runtime discovery evidence but is not offered or
  accepted as an explicit model selection.
- Service tier remains a separate native capability. `Native default` means no
  service-tier override is sent and remains the ordinary included path beside
  any explicitly advertised optional tiers. If the runtime advertises no
  optional tiers, it is the sole truthful Speed choice. Optional tiers are
  shown only from authenticated discovery and retain their availability and
  billing evidence.
- Defaults for other reviewed provider controls and the `inherit-native`
  ExecutionProfile remain separate from model and effort; this ruling does not
  turn those settings into fabricated selections.

## Live-controlled seat swap

Only Live may activate the Swap control, and it is disabled during a model
operation. With one Auditor the control swaps directly; with several Auditors
Live first chooses which seat to exchange with the Executor.

The swap moves the complete runtime assignment: runtime id, requested model,
effort, service tier, provider controls, ExecutionProfile, and any attached
effective-setting evidence. Stable participant ids, seat roles, ordering, and
historical messages do not move. This prevents a hybrid configuration assembled
from two providers and preserves historical references to each seat. The
different-vendor invariant is revalidated before persistence or execution.

The in-app participant swap does not, by itself, reassign Codex's and Claude
Code's repository-engineering roles. Those remain under Live's separate role
ruling.

## Folder-backed Projects

A Project is an owner-local grouping whose topics may share one existing folder
as their native working directory. General remains the no-folder grouping and
uses Dialektikḗ's isolated generated participant workspaces.

Before macOS opens the trusted native folder picker, Live sees and accepts this
exact disclosure:

> Participants use this folder as their native working directory. Actions the
> native runtime auto-permits may modify it without a Dialektikḗ card; those
> actions remain audited.

The WebView may submit only that exact acknowledgement and an optional display
name. It cannot submit a path. Rust opens the native picker, canonicalizes the
chosen existing directory, and passes the result directly to the supervised
sidecar. The Python owner-only Project registry stores the canonical path;
ordinary WebView events contain only Project id, name, registration time, and
current availability.

New Topic inherits the Project currently selected in the sidebar and retains
the runtime seats, but begins with blank model/effort selections. Live may later
link or unlink a settled topic. At run or checkpoint start, the sidecar
derives the workspace only from that persisted topic link, revalidates the
canonical directory, and supplies the same exact working directory to every
Executor, Auditor, retry, Synthesis, and topic-context-checkpoint turn. A run
payload cannot provide `path`, `project_path`, `workspace`, `workspace_dir`, or
`cwd`.

Dialektikḗ does not create, chmod, retarget, or silently replace Live's
external folder. If the folder is missing, moved, inaccessible, or no longer
canonical, the operation fails closed and the UI asks Live to reselect or
unassign the Project. The owner-only registry binds stable filesystem identity
from an opened no-follow directory descriptor, so replacing a directory at the
same canonical path also fails closed. A legacy registration without that
identity remains unavailable until Live explicitly reselects it.

Native permission parity remains unchanged: a provider-authored Ask reaches
Live exactly once, while an action the official runtime auto-permits receives no
fabricated Dialektikḗ card and remains audit-logged.

## Sidebar consequence

The expanded topic sidebar is intentionally narrower and has an accessible
Collapse/Expand control. The owner-local preference survives relaunch when
storage is available; a denied preference store does not disable the current
session's control. Collapsed mode retains compact New Topic, Archived, and
appearance controls while hiding the expanded navigation content. Workspace
centering remains measured relative to the remaining workspace in both states.

The current M2 directive and acceptance bar are in
[`DIRECTIVE.md`](../../DIRECTIVE.md).
