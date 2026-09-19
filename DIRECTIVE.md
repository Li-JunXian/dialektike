# DIRECTIVE — Milestone 2: macOS desktop alpha

## Current increment — ruled 2026-09-09

M2 remains accepted. Live has authorized **chat first, review on request** as
the first increment toward his default AI conversation application. Ordinary
Send now requires one selected speaker only; independent review is explicit
and targets an existing answer. This supersedes mandatory review and
synthesis-only follow-up context for ordinary conversation in the historical
M2 requirements below. See [record 0009](docs/governance/0009-chat-first-review-on-request.md)
for scope and acceptance. The full transition remains incomplete.

Ruled by Live on 2026-07-24; interaction and protocol correction approved on
2026-08-03; explicit participant choices, Project workspaces, role swapping,
and compact navigation approved on 2026-08-21. Claude Code returned `ACCEPT`
on the final R10–R12 and turn-timeout audit, and Live accepted M2 and directed
the work to move to the next deliverables on 2026-08-31.

**Executor:** Codex (`codex`; GPT-5.6 Sol, effective effort recorded at runtime)

**Auditor:** Claude Code (`claude-code`; native `opus` selector, exact
effective model and effort authority recorded at runtime)

**Arbiter and sole permission authority:** Live

Roles remain switchable only by Live. Codex writes M2; Claude Code cross-examines
plans, diffs, and evidence and returns `ACCEPT`, `CHALLENGE`, or
`INSUFFICIENT EVIDENCE`. Claude Code does not edit M2 unless Live explicitly
authorizes a specific correction or reassigns the engineering role. Inside a
Dialektikḗ topic, Live may use the trusted Swap control to exchange the complete
runtime assignments of the Executor and one chosen Auditor; that UI operation
does not reassign the repository-engineering responsibilities above.

This directive supersedes the former roadmap split that put controls in M2 and
the desktop GUI in M6. M1 is accepted and frozen at commit
`6c47d3e06c49a50a51bbddf83657f2d31b2cedff`.

## Mission — the only bar for M2

On Live's Apple M2 Pro MacBook Pro (16 GB, macOS Tahoe 26.5.2), the Dialektikḗ
desktop app:

1. discovers the choices actually advertised or verifiably accepted by the
   authenticated Claude Code and Codex subscription runtimes;
2. lets Live assign exactly one Executor and one or more independent Auditors,
   explicitly select a compatible concrete model and every advertised effort
   for each participant, choose any native service tier, swap the Executor with
   a chosen Auditor, set the number of review rounds, start a run, and stop an
   active run; every active participant must come from a different vendor;
3. begins with Codex and Claude Code runtime seats but no preselected model or
   effort, and displays and records the exact requested and effective settings
   evidenced by each runtime;
4. displays and owner-only saves every voice and all M1 gate, rate-limit,
   permission, raw-capture, and hash-chain evidence;
5. preserves the permanent CLI as a diagnostics and recovery interface;
6. provides owner-local topic sessions with working create, select, rename,
   pin/unpin, archive/unarchive, and tombstone-delete controls; and
7. lets Live group topics into Projects backed by a declared local folder, or
   keep them in General with an isolated generated workspace.

Done is a live demonstration of the desktop app, judged by Live. The demo
includes explicit participant selection, a Live-controlled role swap, automatic
same-round Executor synthesis, more than one review round, topic persistence
and controls, a Project-bound topic, the compact sidebar, Stop, and any
permission request that the native runtimes genuinely raise. No synthetic
permission request is created merely to make the demo convenient.

## Lean review protocol — corrected 2026-08-03

One review run is deliberately small and deterministic:

1. The Executor produces one **Proposal**.
2. Every configured Auditor independently cross-examines the same frozen
   Proposal. Auditor turns start concurrently, use stable seat order for display
   and synthesis, and never receive peer audits.
3. After every Auditor has completed, the Executor produces one **Synthesis**.

The Synthesis becomes the frozen proposal for the next configured review round.
Thus one review round is `Proposal -> parallel Audit(s) -> Synthesis`; two review
rounds add `parallel Audit(s) -> Synthesis` once more and do not create a
redundant second Proposal.

If an Auditor fails, the run pauses before Synthesis. Only Live may choose to
retry the failed Auditor or continue without that audit. The failed attempt and
Live's resolution remain append-only evidence. Stop remains available while the
run is paused.

## Topic and session semantics — corrected 2026-08-03 and 2026-08-21

- Dialektikḗ is the canonical cross-provider conversation. Provider-native
  sessions are fresh, role-bound, and ephemeral where the official runtime
  supports that contract; there is no claim that one Dialektikḗ topic mirrors
  into either provider's official application history.
- Every topic owns its participant configuration and ordered cycles. Changing a
  seat affects future cycles only and never rewrites history.
- A topic may belong to General or one registered Project. New Topic inherits
  the currently selected Project; the topic's Project may later be changed by
  Live while no model operation is active.
- A registered Project identifies one existing folder chosen by Live through
  the trusted native macOS folder picker. Dialektikḗ stores its canonical path
  owner-only and exposes only the Project id, name, registration time, and
  availability to the WebView. The folder path never enters or returns through
  a WebView command or event.
- Every participant turn and topic-context checkpoint in a Project-bound topic
  receives that same revalidated canonical folder as its native working
  directory. If it moves, disappears, becomes inaccessible, or ceases to be the
  canonical target, the operation fails closed. A run cannot supply or override
  its own path.
- A follow-up Live message appends a new cycle. Its lean model context contains
  prior Live messages and prior Executor Syntheses; historic Audits stay visible
  and saved but are not repeatedly sent back to every model.
- Archive is reversible. Delete removes the topic from the ordinary interface
  through an append-only tombstone while retaining owner-only run and governance
  evidence. Evidence purge is a separate destructive operation and is not part
  of M2.

## Desktop interaction ruling — corrected 2026-08-03 and 2026-08-21

- The sidebar is narrow, can be collapsed and restored through a labelled
  control, and remembers that local preference. Its expanded wordmark is
  centred. Topic menus provide Rename, Pin/Unpin, Archive, and Delete; the
  Archived view provides Unarchive and Delete.
- Live sits on the exact horizontal centre of the workspace. The Executor seat
  is centred in the left half. Auditor seats are centred as a group in the right
  half, stacked vertically and internally left-aligned.
- Proposal and Synthesis turns fill the left half. All Auditor turns fill and
  stack within the right half. A Synthesis begins only below the bottom of the
  last Auditor turn.
- The conversation scrolls independently above a bottom-anchored Live composer.
  Stop replaces Send while a run is active.
- Clicking a seat opens a compact provider-native model/effort/service-tier
  selector populated only from authenticated runtime evidence. Participant
  addition, removal, and ordering live in a separate management sheet; technical
  account and effective-setting evidence remains under Details.
- Model and effort are never silently chosen. New, reset, or runtime-changed
  seats show an incomplete selection until Live chooses a concrete model and,
  when that model advertises efforts, an effort. Provider pseudo-options such as
  `Default (recommended)` are not concrete model versions and are not offered as
  a substitute. A model that advertises no effort selector needs no invented
  effort value.
- Swap is disabled during model operations. With one Auditor it is one click;
  with several Auditors Live first chooses the seat. The whole runtime
  assignment moves—runtime, model, effort, tier, controls, execution profile,
  and effective evidence—while stable seat ids, roles, and history remain put.
- Progress uses deterministic protocol stages plus genuine native activity
  events. It never fabricates working narration or exposes hidden reasoning.
- Provider-authored Markdown and structured user-visible blocks retain their
  order and render inertly. Raw HTML remains non-executable.
- Permission requests use provider-specific, native-faithful presentation and
  exact native request content. Raw payload and trusted annotations are behind
  Details. The only decisions remain `Allow once` and `Deny`, on the distinct
  trusted channel, answered personally by Live.
- UI previews never invent an available participant. A third Auditor appears
  only after its real adapter, subscription gate, and capability evidence exist.

## Product and runtime nomenclature

- Human-facing participants: **Executor — Codex** and **Auditor — Claude Code**.
- Stable runtime identifiers: `codex` and `claude-code`.
- Stable role identifiers: `executor` and `auditor`.
- Account routes, runtime versions, requested model/effort/service tier, and
  effective model/effort/service tier are separate recorded fields.
- `chatgpt` is an account/auth route, not the Codex runtime identifier.
- Product labels such as “Ultracode” and “workflows” are not model IDs, effort
  levels, or speed tiers. They are shown only if a runtime exposes a distinct,
  verifiable capability for them.
- Provider drift is never hidden. Live originally requested Claude Opus 4.8,
  but on 2026-07-26 the newest authenticated installed runtime (Claude Code
  2.1.220) advertised `opus` as `claude-opus-5` and no longer advertised 4.8.
  M2 therefore keeps the stable native `opus` selector and exposes the
  effective Opus 5 echo; pinning an obsolete runtime requires a separate Live
  ruling.

## Capability and billing rules

- “All available” means the compatible choices exposed by the authenticated
  runtime for Live's current subscription, not a hard-coded marketing list.
  Codex uses the complete paginated `model/list` result. Claude Code uses the
  Agent SDK initialization catalog returned by `get_server_info()`. Claude
  authentication, that catalog, and every turn are bound to one exact
  Finder-resolved installed Claude Code executable; an extracted bundle copy
  is never treated as equivalent auth evidence. Both catalogs are refreshed
  on app start and revalidated before a new session.
- An explicit unsupported selection fails before the turn. Never silently
  substitute a different model, effort, or service tier.
- A concrete model and each effort advertised for it require Live's explicit
  choice before a run can start. A new topic starts with blank model/effort
  selections while retaining its runtime seats. Runtime-declared defaults for
  separate controls or an ExecutionProfile remain distinct from model/effort
  selection.
- “Speed” means the service-tier request sent to the native runtime. `Native
  default` is the no-override path; it remains available beside discovered
  optional tiers and is the sole choice when none are exposed.
- Any mode billed outside the existing subscription is displayed only as
  unavailable with the billing reason under axiom 1. Claude Fast remains
  unavailable because its runtime identifies it as extra usage from the first
  token. Codex Fast (`priority`) may be selected only when the authoritative
  `account/rateLimits/read` snapshot positively reports no purchased-credit or
  unlimited spend facility; it then consumes the included Plus allowance more
  quickly but cannot spill into pay-as-you-go. The same snapshot is rechecked
  immediately before every Codex turn.

## Architecture boundary

Use the smallest maintainable desktop architecture:

```text
Tauri 2 WebView (React + TypeScript)
        │ narrow typed commands and inert display events
Rust sidecar supervisor
        │ versioned JSONL over child stdin/stdout
Python Dialektikḗ core
        ├── participant/capability registry and round orchestrator
        ├── owner-only run store and M1 evidence
        ├── one provider-neutral PermissionRelay
        ├── Claude Code adapter
        └── Codex adapter
```

Rust owns process lifecycle and IPC plus the trusted native Project-folder
picker. Provider wires, billing/auth gates, roles, rounds, cancellation,
transcripts, Project registration, and permission policy remain in Python. The
WebView receives no generic shell or filesystem capability and cannot supply a
folder path. Model text is inert content; native permission cards use a distinct
trusted modal channel and are answered only by Live.

Keep `dialektike/claude_leg.py` and `dialektike/codex_leg.py` as M1
compatibility facades while extracting modular interfaces. `core/relay.py`
remains authoritative. Continue append-only JSON/JSONL evidence for M2; the
strategic SQLite claim ledger is later scope.

## Roundtable reference ruling

`wenwen-0617/roundtable` is a conceptual reference only. Independently adopt
its useful runtime-state normalization, interruption, restart-recovery, session
handoff, and approval-status UX patterns. Do not copy its source or assets (the
repository has no root license), LAN-exposed unauthenticated server, ambient
credential handling, auto-approvals, truncated permission payloads, hard-coded
model catalogs or role rotation, mutable audit evidence, or unrelated
chat/memory/TTS/game surface.

## Standing authorization and axioms

- Build autonomously to acceptance. Dev calls on both subscriptions may use
  what the work needs within plan limits. Any genuine plan-usage warning stops
  the active run and is saved and reported.
- Claude Code audits at milestone end; the anti-ratchet rule remains binding.
  A disagreement surviving one cross-examination round escalates to Live.
- Subscription plans only: no API keys and no pay-per-token. Official runtimes
  own authentication; Dialektikḗ never reads or stores raw credentials.
- Native permission requests reach Live once and verbatim; auto-permitted
  actions are audit-logged only; cards are answered only by Live personally.
- Local, private, single-user. Never push to a remote.
