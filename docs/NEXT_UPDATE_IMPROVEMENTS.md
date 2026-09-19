# Dialektikḗ next-update improvement backlog

Status: implemented, packaged, independently audited, and accepted. Claude Code
returned `ACCEPT` with no blocking defect after reproducing the final R10–R12
and turn-timeout evidence. Live accepted M2 and directed the work to move to the
next deliverables on 2026-08-31.

Captured from Live's packaged-app review on 2026-08-04

Ordering: deliberately unprioritized

Live explicitly authorized this implementation pass. The acceptance checks
below remain the audit rubric; this file records partial items truthfully rather
than treating code presence as acceptance.

## Implementation disposition

| Item | Current implementation result |
| --- | --- |
| R0 | Shared safe typed-block transport, descriptor-enforced adapter facade, protocol parser, inert fallback, and renderer are implemented. One raw canonical fixture crosses both reply assemblers, topic append/replay, JSONL, the TypeScript parser, rendered DOM, and a byte-preserving copy-path test. Bounded logical permission events above 1 MiB use ordered integrity-checked chunks while every physical JSONL record remains within the 1-MiB limit. Packaged light/dark screenshots remain. |
| R1 | Implemented. A 162-width browser sweep measured at most `0.00390625px` centre/lane drift and no horizontal overflow. A real-Chrome regression now exercises all 164 width/height configurations both ordinarily and under long-content/active-scrollbar stress. Packaged WKWebView capture remains a manual item because macOS denied narrow Automation access. |
| R2 | Implemented as a transparent overlay with bottom reachability; Reduce Transparency selects an opaque semantic surface. |
| R3 | Implemented with participant management in the seat header, transient completion toast, and persistent compact governance states. |
| R4 | Implemented with a viewport portal, required action order, confirmation, command-correlated optimistic rollback on protocol or transport rejection, Escape/outside-click, and keyboard tests. Menu focus remains on the selected action across the two-second parent refresh. Packaged VoiceOver remains a manual acceptance check. |
| R5 | Implemented end to end: backend-authoritative NFKC+casefold occurrence search, canonical JSONL fields, safe segmented snippets grouped by topic, stage/speaker/time metadata, archived results, stable anchors, title/message navigation, and tombstone exclusion. Canonical Unicode reordering and fold expansions preserve conservative deduplicated source spans, pathological combining input is bounded, and the legacy topic matcher delegates to the same contract. Packaged interaction remains part of final acceptance. |
| R6 | Implemented through the generic descriptor/control contract: model/effort/tier, thinking, typed ExecutionProfiles, runtime facilities, requested/effective evidence, and the explicit not-observable boundary. The installed-SDK shadow matrix covers direct and inherited auto-allow and auto-deny paths; the SDK warning remains explicitly advisory. Codex audit provenance distinguishes relayed allow from relayed denial for all supported approval methods. |
| R7 | Implemented end to end as an append-only topic checkpoint draft → Live approval → activation/deactivation lifecycle, including safe cancellation, a persistent active/draft indicator, inspectable source/creator evidence, and no fake provider `/compact`. Claude's installed SDK `PreCompact` hook and Codex's current `contextCompaction` item are recorded separately as provider-session-only turn evidence and never activate a topic checkpoint. Packaged interaction remains part of final acceptance. |
| R8 | The trusted generic plug-in contract is implemented and synthetically proven, including topic persistence and verified evidence. Each registered adapter's emitted relay identity is bound to its reviewed descriptor. Permission-presentation JSON Pointers traverse both objects and canonical array indices without inherited-property access. Approved descriptor paths reject symlinked components, and unavailable-provider UI consumes descriptor-owned connection metadata. A real third-vendor seat is not advertised because no third adapter/runtime has been reviewed, installed, and authenticated by Live. |
| R9 | Semantic System/Light/Dark tokens, measured contrast tests, pre-hydration macOS/persisted appearance selection, CSS↔TypeScript token-parity enforcement, Increase Contrast, Reduce Transparency, reduced motion, and non-colour role/status cues are implemented. The reported dark interactive surfaces use semantic tokens and Tauri grants only the exact theme read/write capabilities. Packaged multi-appearance screenshots remain manual. |
| R10 | Implemented and integrated. New, reset, and runtime-changed seats have no model or effort selection; concrete models and all advertised efforts require Live's choice. Runtime pseudo-default models are excluded. The whole runtime assignment can be swapped between the Executor and one Live-chosen Auditor while stable seats and history remain fixed. Unit and in-app Browser interaction checks pass. |
| R11 | Implemented and integrated. General and folder-backed Projects, the trusted native picker, exact risk disclosure, owner-only canonical path registry, path-free WebView protocol, persisted topic links, identical Project cwd for every participant/checkpoint, and unavailable-folder fail-closed behavior pass Python, Rust, frontend, and browser checks. |
| R12 | Implemented and integrated. The topic sidebar is narrower, collapses to an accessible compact rail, remembers the local preference, retains essential controls, and keeps workspace-centered geometry responsive. The four-test real-Chrome suite passes its 164-viewport ordinary and long-content matrix. |

## 2026-08-16 packaged follow-up

- Removed the inactive attachment affordance; this version remains truthfully
  text-only.
- Eliminated the startup race that could show “sidecar is not running” while the
  sidecar was healthy. Initialization now owns the first discovery/topic load,
  and Retry never replays a model run.
- Restored pointer interaction for `Context`, aligned frontend and backend
  checkpoint eligibility, and made draft/approve/deactivate recovery strictly
  request-correlated through every success, rejection, cancellation, setup
  failure, and event-before-invoke path.
- Renamed the disclosure to `Latest run evidence` and added a strict historical
  loader for the selected topic's exact latest linked run. It revalidates the
  owner-only decision ledger, remains bounded and symlink-safe, and never calls
  a provider model.
- Source verification was green at this historical checkpoint. Later passes
  rebuilt and verified the corrected frozen sidecar, application, and DMG; the
  current hashes are recorded in `docs/UPGRADE_AUDIT_HANDOFF.md`.

## 2026-08-21 focused-work follow-up

- Removed model and effort presets from initial, reset, and runtime-changed
  seats. New Topic retains the runtime seats but deliberately starts with blank
  model/effort selections; only Run remains unavailable until Live makes every
  required concrete selection. `Default (recommended)`-style runtime aliases remain
  discovery evidence, not explicit model versions.
- Added a trusted whole-seat Swap control. One Auditor swaps directly; with
  several Auditors Live chooses the target. Runtime, model, effort, tier,
  controls, ExecutionProfile, and effective-setting evidence move together,
  while stable seat ids, roles, ordering, and history do not.
- Added folder-backed Projects and General. The exact native-working-directory
  risk is disclosed before a trusted macOS picker opens. The selected path never
  crosses the WebView; Rust passes the canonical existing directory directly to
  the supervised sidecar and only safe Project summaries return to the UI. Each
  registration also binds an owner-only filesystem identity captured from an
  opened directory; same-path replacement fails closed until Live explicitly
  reselects it.
- New Topic inherits the selected Project. Every model turn, retry, Synthesis,
  and topic-context-checkpoint turn for that topic uses the same revalidated
  canonical directory. A missing or changed folder fails closed, and a run
  cannot supply its own working directory.
- Narrowed the expanded topic sidebar and added a persisted, accessible compact
  rail. The roundtable remains centered in the workspace at either width.
- This follow-up preserves native permission parity. Auto-permitted operations
  in a Project folder receive no fabricated Dialektikḗ card and remain
  audit-logged; provider-authored permission requests still reach Live once.
- Source behavior was inspected against the implementation. Refreshed
  cross-suite results, browser evidence, and frozen sidecar/app/DMG hashes are
  recorded in the current audit handoff and `design-qa.md`. Claude Code's final
  audit returned `ACCEPT`; Live subsequently accepted M2.

## Post-acceptance carry-forward

These are hardening and product opportunities, not reopened M2 defects:

- Replace the participant topic-projection dictionary spread with an exact
  allowlist before future participant fields can be added.
- Move the remaining hard-coded colour declarations behind the semantic token
  layer so future selectors cannot bypass appearance controls structurally.
- Packaged Light/Dark, Increase Contrast, Reduce Transparency, and VoiceOver
  observations remain deliberately unclaimed; acceptance does not rewrite them
  as tests that were performed.
- A real third-vendor seat still requires a Live-approved adapter, official
  installed runtime, and positively certified subscription-backed account.

## Product rules that apply to every item

- Preserve one Executor and one or more independent Auditors.
- Keep Live as the sole arbiter and the only person who answers a permission
  request surfaced by a provider.
- Display only capabilities positively discovered from an authenticated native
  runtime. Never invent a model, effort, speed, mode, or provider option.
- Require Live to choose a concrete model and each advertised effort. Do not
  treat a provider's pseudo-default selector as a model version, and use
  `Native default` for Speed as the no-override path, beside any discovered
  optional tiers and as the sole choice when none are exposed.
- Make provider support genuinely plug-in. A future provider must be addable by
  supplying a trusted adapter module, declarative registration/packaging
  metadata, and provider conformance tests—without adding provider-ID branches
  to the shared domain, orchestration, transport, or frontend code. Adapter code
  is privileged: Live explicitly approves it for inclusion, it is statically
  registered and frozen into the sidecar at build time, and the application
  bundle's code-signing seal covers it. The release application never discovers,
  downloads, or executes adapter code from user-writable or external locations.
  The signing seal is an integrity control, not a substitute for source review
  or proof of publisher identity. Declarative provider metadata is validated
  inert data, never executable content.
- In this document, “all my LLMs” means every native LLM runtime for which a
  compliant Dialektikḗ adapter and an authenticated subscription route exist.
  An unintegrated model or a web application with no supported native runtime is
  not silently treated as available.
- Keep the append-only Dialektikḗ transcript and governance evidence canonical.
- Match native wording and interaction patterns only where the underlying
  provider exposes equivalent semantics; otherwise use an honest Dialektikḗ
  fallback.
- Treat the annotated lines and boxes in Live's screenshots as review markup,
  not interface elements to reproduce.

## R0 — Safe rich-response fidelity

Area: backend and frontend

### Pre-implementation architectural fact

Dialektikḗ already carries ordered typed content blocks end to end through the
Python domain, adapters, orchestration, sidecar events, topic persistence,
TypeScript protocol, and renderer. The current Codex and Claude Code adapters
emit Markdown blocks only. The frontend already renders Markdown/GFM, syntax-
highlighted code, and mathematics; provider-specific structured content is not
yet mapped comprehensively, and an unknown block needs a readable fallback.
The packaged Content Security Policy currently permits only local/data images
and must remain restrictive unless Live separately approves a remote-media
policy.

### Requested outcome

Extend the shared rendering contract beyond today's safe Markdown baseline so
Codex, Claude Code, and future participants can display provider-authored
content as faithfully as Dialektikḗ can safely support. Do not promise arbitrary
or exact native-client parity.

### Acceptance checks

- Publish a capability matrix for CommonMark/GFM, tables, task lists, nested
  fences, code, diffs, mathematics, diagrams, citations, files, images, audio,
  video, tool activity, and editor references.
- Pass one byte-identical UTF-8 conformance fixture through every provider
  adapter; compare the stored text, ordered typed blocks, rendered DOM, and
  screenshots.
- Preserve ordered typed blocks without flattening them into executable HTML.
- Let each provider descriptor declare the typed content it can emit; keep the
  provider wire-to-block mapping inside that provider's adapter.
- Render supported types with equivalent semantics across providers; show an
  inert readable fallback for unknown types.
- Keep raw HTML and script URLs inert. Do not fetch model-authored remote media
  without an explicit safe policy and Live-visible consent.
- Test nested backtick and tilde fences, long unbroken text, Unicode
  normalization, bidirectional text, wide tables, code copying, and both light
  and dark appearances.

## R1 — Exact centre geometry

Area: frontend

Evidence: Live's red centre-line annotation on the conversation screenshot.

### Requested outcome

Make the Live seat, the conversation split, the Live prompt cards, and the
composer share the exact horizontal centre of the workspace to the right of the
sidebar. Give the Executor and Auditor lanes mirrored inner gutters.

### Acceptance checks

- Define the tested packaged-app range as 720–3840 CSS pixels wide, with 720×640
  as the minimum window. Measure 720×640, every responsive breakpoint at −1/0/+1
  pixels, 880×720, 1180×820, 1488×1058, and a horizontal sweep in 20-pixel
  increments through that range.
- At every tested size, the Live seat centre, centre of the middle gutter, Live
  prompt centre, and composer centre differ by no more than one CSS pixel.
- The distance from the Executor lane's content edge to the centre boundary
  equals the distance from that boundary to the Auditor lane's content edge.
- Proposal and Synthesis continue to fill the left half; all Auditors continue
  to fill the right half.
- Long code, tables, citations, or prose cannot shift the grid boundary.
- Add automated geometry assertions and instrument the packaged WKWebView. Test
  the scrollbar, grid, and wrapper hypotheses rather than assuming one of them
  caused the observed drift; compare a packaged-app screenshot after measuring.

## R2 — Transparent composer dock

Area: frontend

Evidence: Live's green-hatched annotation around the bottom composer dock.

### Requested outcome

Remove the opaque full-width dock surface. Let the conversation remain visible
behind that region, following the visual behaviour of the native Codex and
Claude Code chat surfaces, while keeping the composer itself legible.

### Acceptance checks

- Only the composer capsule and controls receive a readable surface treatment;
  the surrounding dock is transparent.
- Replace the dedicated opaque third layout row with an overlay or sticky dock
  architecture so conversation content can actually pass behind the transparent
  region.
- Scrolling content remains visible behind the dock without making the composer
  text or controls illegible.
- Bottom scroll padding keeps the final response and its controls reachable
  above the composer.
- Light mode, dark mode, and Increase Contrast retain a clear composer boundary.
  When macOS Reduce Transparency is enabled, use an opaque semantic surface
  instead of promising transparency. Implement this item on R9's tokens and
  accessibility-state handling.

## R3 — Recover the status-row space

Area: frontend

Evidence: Live's blue-box annotation around the full-width cycle-status row.

### Requested outcome

Remove the persistent full-width row from the chat viewport. Put participant
management with the participant seats and reduce ordinary completion status to
a compact, non-blocking presentation.

### Acceptance checks

- `Manage participants` is a compact control in the participant header, next to
  the seat configuration it affects.
- `Cycle completed and saved` is a transient accessible status/toast and does
  not consume permanent vertical space.
- Running, paused, permission-waiting, plan-limit, and failed states remain
  persistent until resolved; they may use a compact banner above the composer.
- Removing the row increases the visible conversation area without hiding any
  governance state.

## R4 — Reliable topic overflow menus

Area: frontend

### Requested outcome

Make every topic's ellipsis button open a correctly anchored menu using familiar
LLM-chat conventions.

### Acceptance checks

- The menu contains `Rename`, `Pin` or `Unpin`, `Archive` or `Unarchive`, and
  `Delete` in that order, showing only actions valid for the topic's state.
- The menu stays within the window, appears above neighbouring content, and is
  not clipped by the sidebar scroll container.
- Mouse, keyboard, and VoiceOver users can open it, move through it, activate an
  item, and dismiss it with Escape or an outside click.
- Delete is visually separated, requires confirmation, and retains immutable
  governance evidence under the existing tombstone policy.
- Each action updates the sidebar immediately and survives an application
  restart.

## R5 — Full-text topic search with results

Area: backend and frontend

### Pre-implementation architectural fact

The Python topic store already searches titles and visible conversation text
with Unicode `casefold()`. The frontend then incorrectly re-filters those
backend results by title with locale-sensitive lowercasing, which drops valid
content-only matches. The backend currently returns topics, not occurrence
records or snippets, and neither layer has a declared normalization contract.

### Requested outcome

Search topic titles and conversation contents case-insensitively, then show a
result dropdown that lets Live jump directly to an occurrence.

### Acceptance checks

- Index topic titles, Live prompts, Proposals, Audits, Synthesis responses, and
  other stored visible response text; never index owner-only raw evidence into
  user-visible snippets.
- Define matching as NFKC normalization followed by Unicode case folding. Apply
  this to a derived search representation only; preserve the authored text
  byte-for-byte for storage and display.
- Make the backend the sole matching authority. Return structured occurrence
  records with stable topic/message anchors and enough source mapping to
  highlight the authored text; the frontend must not repeat matching with a
  different locale-sensitive algorithm.
- Show results grouped by topic with the topic title, stage/speaker, a short
  highlighted snippet, timestamp when available, and archived status.
- Selecting a hit opens the correct topic, scrolls to the occurrence, and gives
  it a temporary non-colour-only highlight.
- Search includes archived topics by default with a visible archived badge;
  tombstoned topics remain excluded.
- Results update after append, rename, archive, unarchive, and tombstone events,
  and the index can be rebuilt from the canonical append-only topic store.
- Query text and result snippets remain local and owner-only.

## R6 — Claude Code-native capability controls

Area: backend and frontend

Evidence: Live's Claude Code screenshots showing model selection, effort,
Thinking, Modes (`Manual`, `Edit automatically`, `Plan`, `Auto`), output styles,
agents, hooks, memory, permissions, MCP servers, and plugins.

### Pre-implementation architectural fact

The shipped Claude adapter supplies `can_use_tool` and PostToolUse auditing but
leaves `setting_sources`, `permission_mode`, `allowed_tools`, `skills`, and
`sandbox` at the SDK defaults. `setting_sources=None` delegates to the native
user/project/local settings sources, consistent with governance 0003's default
`inherit-native` ExecutionProfile. `can_use_tool` receives only actions the
native permission engine classifies as requiring a decision; native auto-
permitted actions produce no synthetic card and remain audited. The SDK cannot
enumerate the complete effective external allow-rule set.

### Requested outcome

Retain the current Codex-faithful model/effort/speed picker. Give Claude Code a
provider-capability-driven control surface that reflects the authenticated
installed runtime instead of forcing Claude's options into Codex's three fields
or adding another hard-coded Claude-only frontend branch.

### Acceptance checks

- Re-capture the installed official Codex and Claude Code controls read-only at
  implementation time; wording and grouping must not come from memory.
- Separate per-turn controls such as model, effort, thinking, and supported mode
  from runtime-wide facilities such as output styles, agents, hooks, memory,
  permissions, MCP servers, and plugins.
- Represent permission-affecting choices as a typed `ExecutionProfile`, separate
  from model, effort, and thinking. Extend the request/effective protocol rather
  than presenting switches that the adapter cannot transmit or verify.
- Every selectable value comes from a live capability probe or a schema-pinned
  runtime contract and is accepted or echoed by that runtime.
- Unsupported and subscription-ineligible values are absent or clearly disabled
  with the native reason; no cosmetic switch may imply a capability.
- Keep `inherit-native` as the explicit default. Record the requested SDK
  options and their authority; when the runtime cannot echo a value or expose
  loaded external rules, display `not observable` rather than claiming an
  effective value.
- Enumerate and test all callback-shadowing or native-auto-permit mechanisms in
  the installed runtime, including permission modes such as `acceptEdits` and
  `bypassPermissions`, whole-tool `allowed_tools`, skills-derived entries,
  settings permission rules, PreToolUse allows, and sandbox auto-allow. Do not
  treat the SDK's shadowing warning as a complete detector.
- An isolated profile using `setting_sources=[]`, or any mode that bypasses
  Dialektikḗ's governed permission path, requires a separate ruling from Live
  and must disclose which native facilities it disables or auto-approves.
- Prove that a known native `Ask` reaches Live exactly once, while a native
  auto-permit raises no fabricated card and leaves a truthful completion audit.
- Store requested and effective values separately and show the effective model,
  effort, mode, thinking state, and service tier after each turn when the runtime
  can certify them.

## R7 — Honest context compaction

Area: backend and frontend

### Pre-implementation architectural fact

Dialektikḗ currently owns conversation history and rebuilds provider input from
the canonical topic context. Codex turns use ephemeral provider threads; there
is therefore no long-lived Codex thread inside the current topic to compact.
The bundled Codex app-server schema does expose `thread/compact/start`, and the
Claude Agent SDK exposes auto-compaction state and pre-compact hooks, but those
native mechanisms are not automatically useful while Dialektikḗ sessions remain
ephemeral.

### Requested outcome

Add a compact action that reduces future context safely and visibly without
pretending to compact a provider session that does not persist.

### Acceptance checks

- Provide one topic-level `Compact context` action and make its scope explicit.
- Generate a reviewable compaction checkpoint from Dialektikḗ's canonical prior
  Live prompts and completed Synthesis responses; Live approves it before it
  affects future turns.
- Keep the complete original transcript and governance evidence immutable.
- Future turns use the approved checkpoint plus post-checkpoint context, with a
  visible indicator and an option to inspect or stop using the checkpoint.
- Record the source range, summary, creator/runtime evidence, timestamp, and
  before/after context estimate without exposing hidden chain-of-thought.
- Use native provider compaction only if a future adapter keeps a persistent
  provider session and positively advertises that operation; otherwise do not
  relay a fake `/compact` prompt.
- Record any observable native compaction inside an individual fresh provider
  turn as turn evidence only. It neither creates nor mutates Dialektikḗ's topic
  checkpoint; for Codex, use the current `contextCompaction` item contract rather
  than depending on the deprecated notification.
- A failed or unavailable compaction leaves the active context unchanged.

## R8 — Provider plug-in contract and additional vendor-backed Auditors

Area: backend and frontend

### Pre-implementation architectural fact

The core `ProviderAdapter` and orchestration path are provider-oriented, but the
shipped product is not yet plug-in. Production IDs, adapter composition,
relay-to-runtime mapping, Rust permission validation, TypeScript parsers,
labels, controls, and permission layouts enumerate Codex and Claude Code. The
latent `GEMINI_CLI` enum has no adapter or authenticated catalog and is not a
supported or available seat. With Codex occupying the Executor seat and Claude
Code occupying Auditor 1, the current `No additional authenticated vendor is
available` state is therefore truthful.

### Requested outcome

Make Dialektikḗ genuinely plug-and-play for Live's supported LLM runtimes, then
make the path to multiple independent Auditors obvious when additional vendor
runtimes are installed and authenticated.

### Acceptance checks

- Introduce a trusted, versioned provider descriptor and registration contract.
  Runtime, vendor, and agent-system identities are validated opaque identifiers;
  successful authenticated adapter discovery is the sole source of availability.
- Let the descriptor provide display metadata, vendor identity, authentication
  and version evidence, model capabilities, a constrained typed control schema,
  supported content types, and constrained permission-presentation data.
  Descriptors are data only: never load provider-supplied executable UI or HTML.
- Make shared Python composition, the relay presenter, sidecar protocol, Rust
  boundary, TypeScript parsers, participant management, labels, controls,
  evidence views, and permission presentation consume descriptors generically.
  Distinct-seat validation uses `vendor_id`, not `runtime_id`.
- Adding a provider may add its adapter module, declarative registration and
  packaging entry, and provider conformance fixtures. It must require no new
  provider-ID conditionals in the shared domain, orchestrator, registry,
  transport, Rust boundary, or frontend.
- Require Live's explicit review and approval before a production adapter is
  statically registered, frozen into the sidecar, and covered by the application
  bundle's code-signing seal. Runtime discovery may find authenticated provider
  capabilities and consume constrained descriptors, but the release application
  must never discover, download, or load executable adapter code from user-
  writable or external locations. Registration descriptors cannot be Python
  entry points, executable UI, HTML, scripts, or code-bearing expressions.
  Development-mode source loading is not release trust evidence.
- Prove the contract first with an unanticipated synthetic provider identifier
  flowing end to end through discovery, catalog, controls, topic persistence,
  run/activity, permission request and decision, evidence, and labels without
  editing shared code.
- Then add at least one Live-approved real third-vendor adapter, with first-party
  subscription/authentication gates, capability discovery, permission relay,
  plan-limit handling, cancellation, evidence, and conformance tests.
- Replace the passive empty state with `Connect another provider`, explaining
  that same-vendor model variants cannot occupy another seat.
- When a provider becomes available, show `Add Auditor` both in the seat header
  and participant manager; adding it creates a real ordered seat immediately.
- Support adding, removing, and reordering multiple Auditors, while keeping one
  Executor and rejecting duplicate vendors before a run starts.
- All Auditors receive the same frozen proposal independently and may run in
  parallel; Synthesis begins only after all successful Audits or Live's explicit
  failed-auditor resolution.

## R9 — Evidence-based visual comfort and accessibility

Area: frontend

### Research conclusion

There is no single universally or medically certified "eye-healthy" colour
palette. Authoritative guidance instead supplies measurable accessibility and
ergonomic criteria. The next update must not market a palette as medically
protective; it should implement and test those criteria.

### Authoritative baseline

- [W3C WCAG 2.2 text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html): at least 4.5:1 for ordinary text and 3:1 for large text.
- [W3C WCAG 2.2 non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html): meaningful controls, states, focus cues, and graphics need at least 3:1 against adjacent colours.
- [Apple Human Interface Guidelines — Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode): use adaptive semantic colours, test every appearance, avoid naive inversion, and soften bright content in dark surroundings.
- [Apple Dark Interface evaluation criteria](https://developer.apple.com/help/app-store-connect/manage-app-accessibility/dark-interface-evaluation-criteria): test Dark Mode with Increase Contrast and account for Reduce Transparency.
- [OSHA workstation environment](https://www.osha.gov/etools/computer-workstations/workstation-environment): glare, excessive brightness, and harsh contrast with the surroundings can contribute to fatigue; favour diffuse, non-reflective presentation.
- [OSHA monitor guidance](https://www.osha.gov/etools/computer-workstations/components/monitors): readable sizing, viewing clarity, periodic eye rest, and avoiding glare matter in addition to palette choice.

### Requested outcome

Create a calm, low-glare visual system that follows macOS appearance and
accessibility settings while preserving strong readability.

### Acceptance checks

- Introduce semantic colour tokens and `System`, `Light`, and `Dark` appearance
  choices; `System` follows macOS automatically.
- Meet WCAG 2.2 AA text contrast: at least 4.5:1 for ordinary text and 3:1
  for large text, where large means at least 18 pt (24 CSS px) normally or
  14 pt (18.66 CSS px) when bold.
- Give active controls, states, focus cues, and meaningful non-text graphics at
  least 3:1 contrast against adjacent colours. Record and test the applicable
  exemptions for inactive/disabled components, purely decorative content, and
  logotypes rather than claiming those exempt elements meet a threshold.
- Offer an enhanced-contrast path and respond correctly to Increase Contrast and
  Reduce Transparency; never rely on colour alone for status or role.
- Avoid pure high-luminance panels and excessive glow in dark surroundings;
  avoid muddy low-contrast grey-on-grey text in either appearance.
- Use restrained, low-saturation role accents for Executor and Auditor identity,
  while text, icons, labels, and verdicts remain independently legible.
- Measure every token pair automatically and visually test the full packaged app
  in light, dark, increased-contrast, and reduced-transparency states.
- Validate long-reading comfort with real Proposal/Audit/Synthesis content at
  supported window sizes. Screenshots alone may establish visible risks but may
  not be used to claim medical benefit or full accessibility compliance.

## R10 — Explicit participant choices and whole-seat swap

Area: backend and frontend

### Requested outcome

Do not preselect a model version or effort for Live. Make role reversal a quick,
safe operation that exchanges complete participant assignments rather than
assembling a mixed configuration.

### Acceptance checks

- Initial, reset, and runtime-changed seats show no selected model or effort.
- New Topic remains available and persists blank model/effort selections while
  retaining the chosen runtime seats. Run stays unavailable until every seat
  has a concrete runtime-advertised model and, when that model advertises
  efforts, one valid effort chosen by Live.
- Runtime aliases such as `Default (recommended)` are not rendered or accepted
  as concrete model versions. A model without an effort selector needs no
  fabricated effort.
- Speed exposes `Native default` as the no-override path plus only authenticated
  runtime-advertised optional tiers. It is the sole choice when no optional
  tier exists.
- With one Auditor, Swap is one click; with several, Live chooses the Auditor.
  Swap is disabled during active model or checkpoint work.
- Runtime id, requested model/effort/tier, controls, ExecutionProfile, and
  effective evidence move together. Stable seat ids, roles, order, and history
  remain fixed.
- The complete configuration is revalidated for availability and distinct
  vendors before it is saved or run.

## R11 — Project-bound topics and native working folders

Area: backend, native shell, and frontend

### Requested outcome

Let Live organize topics as focused Projects tied to declared local folders,
with the same native working-directory semantics for every participant and no
generic filesystem capability in the WebView.

### Acceptance checks

- The sidebar provides General plus registered Projects. New Topic inherits the
  selected Project, and Live can relink a settled topic.
- Before the folder picker opens, show exactly: `Participants use this folder as
  their native working directory. Actions the native runtime auto-permits may
  modify it without a Dialektikḗ card; those actions remain audited.`
- Only the trusted macOS native picker supplies a path. The WebView request can
  carry the exact acknowledgement and optional display name but no path; normal
  events return only Project id, name, registration time, and availability.
- Canonical paths remain owner-only. Registration never creates, chmods,
  retargets, or silently replaces the selected external folder. An owner-only
  opened-directory identity detects same-path replacement, while legacy
  unbound registrations stay unavailable until Live explicitly reselects them.
- Every Executor, Auditor, retry, Synthesis, and topic-context-checkpoint turn
  for a Project-bound topic uses the same revalidated canonical directory.
- `run.start` rejects path, project-path, workspace, workspace-dir, and cwd
  injection. A missing, moved, inaccessible, non-canonical, or identity-changed
  folder fails closed before a provider turn.
- General topics preserve isolated generated participant workspaces.
- Native permission parity is unchanged: provider Asks relay once;
  runtime-auto-permitted actions generate no synthetic card and remain audited.

## R12 — Compact collapsible topic navigation

Area: frontend

### Requested outcome

Use a narrower sidebar and an accessible compact rail so focused conversation
work can use more of the window without losing essential navigation controls.

### Acceptance checks

- Ordinary desktop width is 264 CSS pixels expanded and 62 pixels collapsed,
  with proportional responsive values at the minimum supported window.
- A clearly labelled Collapse/Expand control exposes its state to assistive
  technology and remains keyboard operable.
- The owner-local preference survives relaunch when local preference storage is
  available. Storage denial does not disable the current-session control.
- Collapsed mode retains compact New Topic, Archived, and appearance controls;
  expanded Project/topic/search navigation is hidden rather than squeezed.
- Live, the lane split, prompt cards, and composer remain centered in the
  post-sidebar workspace, with no horizontal overflow in either state.

## Implementation dependencies

1. Build the generic provider descriptor/registration contract in R8 before R6,
   so Claude Code controls and all later providers use the same extension path.
2. Define R0's typed content capability declarations through that descriptor.
3. Establish R9's semantic colours and macOS accessibility-state handling before
   completing R2's transparent/opaque composer behaviours or R0's light/dark
   rendering checks.
4. Add R1's packaged-WKWebView measurement harness before claiming the geometry
   defect's root cause or visual completion.
5. Implement the remaining topic, status, and search improvements against those
   shared foundations; add the real third-vendor adapter only after the synthetic
   plug-in conformance proof passes.
6. Treat R10–R12 as one focused-work follow-up: explicit seat choices are saved
   before a Project topic is created, Project security stays below the WebView,
   and sidebar geometry is checked in both expanded and collapsed states.

## Evidence captured in this review

1. Conversation screen with Live's centre line, status-row box, and composer
   dock hatching — useful and sufficient to record R1–R3; not sufficient by
   itself to verify responsive geometry or accessibility.
2. Claude Code Modes and effort menu — useful for R6 wording and information
   architecture; runtime capability probes are still required.
3. Claude Code customization menu — useful for separating per-turn controls
   from runtime-wide configuration in R6.
4. Dialektikḗ participant manager with no additional authenticated vendor —
   confirms the discoverability issue and the real two-provider limitation in
   R8.
