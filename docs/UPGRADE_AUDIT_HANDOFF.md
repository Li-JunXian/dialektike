# Dialektikḗ upgraded-version audit handoff

Status: Claude Code returned `ACCEPT` with no blocking defect after independently
reproducing the final R10–R12 and active-turn-timeout evidence. Live accepted M2
and directed the work to move to the next deliverables on 2026-08-31.

Date: 2026-08-31

Executor: Codex

Auditor: Claude Code

Arbiter and sole permission authority: Live

Baseline commit: `6c47d3e`

Repository state: approved by Live for the local accepted-M2 commit; never push

## Audit target

Cross-examine the implementation against
`docs/NEXT_UPDATE_IMPROVEMENTS.md`, with special attention to the corrections
recorded in `docs/CLAUDE_PERMISSION_SHADOW_MATRIX.md`,
`docs/CONTENT_CAPABILITY_MATRIX.md`, `design-qa.md`, and governance record
`docs/governance/0007-explicit-selections-projects-and-seat-swap.md`.

Return `ACCEPT`, `CHALLENGE`, or `INSUFFICIENT EVIDENCE`. A challenge must name
the governing requirement, concrete evidence and impact, and a minimal correct
patch. Do not add a new criterion mid-pass. Live alone accepts the upgraded
version.

## Implemented result

- R0: safe ordered typed-content transport, descriptor enforcement, inert
  fallbacks, conservative link/media handling, byte-preserving Markdown/code,
  and one shared 3,783-byte UTF-8 fixture across provider reply assembly,
  persistence, JSONL, TypeScript parsing, DOM rendering, and copy behavior.
  Oversized bounded native permission events retain the 1-MiB physical-record
  limit through ordered integrity-checked transport chunks.
- R1: a single exact workspace center, mirrored response lanes, a 162-width
  geometry sweep, no tested horizontal overflow, and a repeatable real-Chrome
  regression over all 164 width/height configurations before and after
  long-content/active-scrollbar stress.
- R2: a transparent overlay composer with bottom reachability and an opaque
  Reduce Transparency fallback.
- R3: participant management moved into the seat header; completion is a
  transient accessible toast while unresolved governance states remain
  persistent.
- R4: viewport-portalled topic actions in Rename, Pin/Unpin, Archive, Delete
  order, with keyboard, outside-click, confirmation, optimistic update, and
  command-correlated rollback behavior. Menu focus survives parent polling and
  rerenders instead of jumping back to the first action.
- R5: backend-authoritative NFKC/casefold content search, topic-grouped
  occurrences, stage/speaker/time metadata, archived results, stable anchors,
  title/message navigation, and tombstone exclusion. Canonical reordering and
  fold expansions preserve conservative, deduplicated authored spans with
  bounded work for pathological combining input.
- R6: generic descriptor-driven provider controls and typed execution profiles;
  requested and runtime-certified effective settings remain distinct. Claude
  native Ask requests relay exactly once, native auto-permits remain no-card
  audit events, direct and inherited auto-allow/auto-deny paths are enumerated,
  and externally inherited permission effects are explicitly reported as not
  observable. Relayed allow and deny provenance is decision-aware. The SDK
  shadow warning is treated only as advisory.
- R7: append-only topic context checkpoints with draft, Live approval,
  activation, inspection, and deactivation. Provider-native per-turn compaction
  evidence remains separate and can never activate a topic checkpoint. Claude
  uses the installed `PreCompact` hook; Codex observes the current
  `contextCompaction` item rather than its deprecated notification.
- R8: trusted opaque-ID provider descriptors, declarative registration, generic
  Python/Rust/TypeScript/frontend handling, adapter-to-descriptor relay identity
  binding, and an unanticipated synthetic provider conformance path that now
  covers all eight named stages, including topic persistence and verified
  evidence. Descriptor JSON Pointers traverse canonical array indices and own
  object fields without inherited-property access; approved descriptor paths
  reject symlinked components; unavailable-provider UI consumes descriptor-owned
  connection metadata. No real third-vendor seat is advertised because no third
  adapter/runtime has been reviewed, installed, and authenticated by Live.
- R9: semantic System/Light/Dark appearances, measured contrast invariants,
  parser-blocking pre-hydration selection, exact CSS↔TypeScript token parity,
  Increase Contrast, Reduce Transparency, reduced motion, and non-colour role
  and state cues. All reported dark interactive states use semantic tokens, and
  the desktop capability grants only the exact theme read/write permissions.
- R10: explicit concrete model and advertised-effort selection with runtime
  pseudo-default models excluded; a Live-controlled whole-seat
  Executor↔Auditor swap preserves stable seat identity and moves every runtime
  setting together.
- R11: General and folder-backed Projects, a trusted macOS picker with exact
  risk disclosure, no path capability in the WebView, owner-only canonical
  storage, persisted topic links, one identical Project cwd for every
  participant/checkpoint, and unavailable-folder fail-closed behavior.
- R12: a narrower responsive sidebar with an accessible, persisted compact rail
  and workspace-centered geometry in both states.

## Interim Auditor findings disposition

- Pre-hydration light flash: accepted as an R9 continuation. A same-origin
  parser-blocking bootstrap now applies the stored or macOS System appearance
  before the stylesheet/application module paints; explicit Light on a dark
  system and explicit Dark on a light system are covered.
- CSS/TypeScript token drift: accepted as an R9 continuation. Tests parse the
  actual light and dark CSS declarations and require exact equality with the
  measured TypeScript palettes.
- Synthetic geometry-only tests: accepted as an R1 continuation. The pure
  evaluator tests remain, with a separate Playwright-backed Vitest Browser Mode
  run against the real App and CSS. The packaged WKWebView visual capture is
  still truthfully manual.
- Frozen legacy Broker: challenged as a defect. `core.broker` must remain frozen
  because production audit-chain primitives are defined there; manifest mode
  represents prior Live authorization under governance 0001 and no production
  path constructs `Broker`. A new AST packaging invariant prevents any such
  import/construction from entering frozen production modules.
- Array JSON Pointer: accepted as an R8 continuation. Canonical in-range array
  indices now resolve; leading-zero, unsafe, out-of-range, and inherited fields
  fail closed while the full verbatim card remains available.

## Final Auditor provider findings disposition

- Claude shadow matrix omissions: accepted as an R6 continuation. The matrix
  now includes inherited `permissions.defaultMode`, `dontAsk`, auto-mode denial,
  inherited allow/deny rules, and allow/deny-capable `PreToolUse` hooks. Its
  completeness check is coupled to the installed SDK's typed permission modes;
  inherited state remains truthfully not observable.
- Synthetic provider proof gap: accepted as an R8 continuation. A no-model
  conformance run now crosses discovery, catalog, controls, topic persistence,
  run/native activity, permission request and decision, verified evidence, and
  descriptor-owned labels through shared code.
- Unbound relay provider identity: accepted as an R8 continuation. Every static
  registration now fails closed unless the constructed adapter's declared relay
  identity equals its reviewed descriptor, and adapters use that bound value
  when constructing native permission requests.
- Codex native compaction observation: accepted as an R7 continuation. Current
  schema `contextCompaction` completion items are counted in bounded turn
  evidence with an explicit statement that no topic checkpoint was mutated.

## Final Auditor correction findings disposition

- Dark interactive-state gaps, topic-menu focus resets, and dead fail-closed
  permission cards: accepted as existing R9/R4/governance continuations and
  corrected. The three surviving light-only hover/active states now use semantic
  appearance tokens; a real-Chrome rerender regression preserves the selected
  menu item; sidecar rejection or supervisor exit removes an unusable permission
  card and clears the inert application surface while transport failure remains
  retryable.
- Topic mutation recovery: accepted as an R4 continuation. Rename, pin, archive,
  delete, and participant edits are correlated to their command IDs, including
  the early-event race, and roll back only their own optimistic change on a
  protocol or transport failure.
- Codex decision provenance: accepted as a governance audit continuation.
  Relayed allows and denials are now recorded distinctly for every supported
  approval wire method; native auto-permits remain separately classified.
- Oversized permission events: accepted as a transport correctness continuation.
  The physical JSONL limit remains 1 MiB; larger bounded logical events use
  ordered SHA-256-verified chunks and are reassembled and revalidated in Rust
  before any WebView delivery. A duplicated 600-KiB native/card payload is
  covered.
- Theme capabilities: accepted as an R9 continuation. The Tauri capability is
  limited to `allow-theme` and `allow-set-theme`; no broad window default was
  introduced.
- Unicode search and provider-package hardening: accepted as R5/R8
  continuations. Search now shares one NFKC/casefold contract, maps canonical
  reordering conservatively in bounded work, deduplicates fold-expansion hits,
  and excludes symlinked descriptor files or parent directories.
- Provider plug-in presentation: accepted as an R8 continuation. Unavailable
  runtimes surface descriptor-owned connection metadata, and the synthetic
  provider proof includes all eight required stages without a provider-ID
  branch.
- Pre-hydration appearance, CSS↔TypeScript token parity, and array JSON Pointer
  traversal were accurate findings when filed, then corrected and independently
  reverified during the correction pass. The frozen Broker finding remains
  rejected for the governance and production-reachability reasons above.
- An independent read-only integration review found no remaining concrete code
  defect across the correction pass. It did not replace Live's packaged workflow
  or macOS accessibility judgment.

## Live packaged follow-up correction

Live's 2026-08-16 packaged review exposed a stale startup warning and two
misleading composer controls. The follow-up correction is implemented and has
received a final read-only adversarial recheck with no remaining concrete code
blocker:

- Startup now has one protocol-readiness owner. Topic listing, discovery, and
  search cannot run before the sidecar acknowledges initialization; a process-
  running notification is not treated as protocol readiness. A safe Retry
  reconnects, rediscovers capabilities, and reloads saved topics without ever
  replaying a model run.
- The inactive paperclip was removed. Attachments remain outside this version's
  text-only prompt contract rather than being presented as a broken control.
- `Context` is operable through the transparent composer overlay and explains
  why checkpoint creation is unavailable. Drafting requires an unarchived,
  settled topic with a completed, non-partial Executor Synthesis. Draft,
  approval, and deactivation commands are request-correlated, including the
  event-before-invoke race; only the matching terminal event or rejection can
  release their busy state. The backend likewise guarantees one safe terminal
  failure and clears all checkpoint state even if run-store setup fails.
- `Evidence` is now labelled `Latest run evidence`. It is a bounded, read-only
  projection of runtime/account gates, rate observations, permission/audit
  counts, raw-capture inventory, and decision-chain verification. On topic
  selection or relaunch, the app requests only that topic's exact latest linked
  run. The backend performs owner-only, symlink-safe, size-bounded reads and
  recomputes the decision chain before returning the strict summary; no model is
  called and no raw path, filename, payload, or unknown field crosses into the
  WebView. Topic and request correlation prevents stale cross-topic results.

## 2026-08-21 focused-work follow-up

The new scope for this audit is deliberately bounded to the latest Live ruling:

- Initial, reset, and runtime-changed seats carry no model or effort selection.
  Topic creation persists that honest incomplete state; only Run rejects
  incomplete settings. Provider pseudo-default
  models cannot satisfy the concrete-model check; models without efforts do not
  acquire an invented value. `Native default` remains the truthful Speed
  no-override path, alongside authenticated optional tiers and as the sole
  choice when a model advertises none.
- The seat header exposes Swap below Live. One Auditor swaps directly; multiple
  Auditors produce a chooser. The complete runtime/requested/effective
  assignment moves while stable ids, roles, order, and history remain fixed.
- Projects are registered through one trusted Tauri command. The WebView passes
  only the exact acknowledgement and optional name; Rust opens the native
  folder picker, canonicalizes the existing directory, and sends its path
  directly to the sidecar. The owner-only registry binds device/inode and an
  available birth-time identity from an opened no-follow directory descriptor;
  Project list/registration events remain path- and identity-free.
- New Topic inherits the selected Project; a settled topic can be reassigned.
  At Run and checkpoint boundaries the sidecar derives the workspace from only
  that persisted topic link. Every participant/checkpoint receives the same
  canonical cwd. Path injection and unavailable folders fail closed before a
  provider turn. Replacing a folder at the same path also fails closed; legacy
  unbound records require explicit Live re-selection.
- The sidebar uses responsive expanded/collapsed widths, labelled controls, and
  owner-local preference storage. Collapsed mode retains essential icon
  controls and the roundtable remains centered in the remaining workspace.

### Refreshed integrated evidence

- Every standalone Python invariant script except the deliberately stale-artifact
  check passed before packaging. After the release rebuilt the sidecar,
  `tests/m2_packaging_invariants.py` also passed, including sidecar freshness.
  `tests/project_workspace_invariants.py` passed all nine tests, including
  same-path replacement before and during a run.
- Frontend unit suite: 24 files, 119 tests passed. This includes explicit
  selection, runtime-default rejection, whole-seat Swap, Project disclosure and
  filtering, immutable historical labels, sidebar preference, geometry,
  recovery, protocol, and rendering.
- The in-app Browser exercised both provider selectors, proved no pseudo-Default
  option was rendered, selected Codex GPT-5.6 Sol/Ultra and Claude Code
  Opus/Extra high, performed a whole-seat Swap, created a topic inheriting the
  selected Project, and found no application console error. At 1512×982 the
  expanded/collapsed sidebar measured 264/62px and the mirrored lane-gutter
  difference was `0.0078125px`.
- The real-Chrome Browser Mode suite passed 4/4 tests. Its ordinary and
  long-content matrix covers 164 viewport configurations over 720–3840 CSS
  pixels with zero horizontal overflow and also exercises collapse/expand and
  Context/Evidence clickability.
- Rust suite: 16/16 passed, including blank topic/run-bound selection behavior,
  WebView path exclusion, Project-event validation, native picker
  canonicalization, and supervisor transport tests.
- Frontend production TypeScript/Vite build, Python compilation, Rust tests and
  formatting, and `git diff --check` passed. Vite emitted only its non-blocking
  greater-than-500-kB chunk advisory.
- The Tauri release command rebuilt and smoke-tested the frozen sidecar before
  producing both bundles. Sidecar SHA-256:
  `119f5cf93b564f0eb88e2e6b31da63b9ab4a6891d2833dcb282d1ac3ff24b3f5`;
  the standalone and `.app` copies are identical. App executable SHA-256:
  `927735a4b5aa5a720926249e901755801896bedd66ad0b633e1931ff9e821a50`.
  DMG SHA-256:
  `864bcaf4e84bad9080391021edf8574b30bd989871bdaa7c9100a79008921465`.
  Strict deep code-signature verification and `hdiutil verify` both passed.
- Exact browser measurements, package paths, prior provenance, and the remaining
  manual visual boundary are recorded in `design-qa.md`.

## Prior source verification (through 2026-08-16)

- All 16 non-packaging standalone Python invariant suites passed. The focused
  historical-Evidence/checkpoint suites passed 7/7, 6/6, and 4/4 after the
  follow-up correction.
- The packaging invariant suite also passed its source/configuration/freshness
  checks. This does not substitute for the separately blocked frozen-binary
  smoke or a rebuilt application bundle.
- Frontend unit suite: 22 files, 101 tests passed.
- The last completed real-browser geometry/interaction run passed 2 tests after
  328 rendered geometry evaluations (164 viewport configurations in ordinary
  state and 164 under stress), plus the topic-menu focus-preservation rerender
  regression. A third real-browser Context/Evidence overlay interaction test is
  committed, but the final three-test rerun could not bind its local test port
  after the Codex approval service reported the session usage limit; it remains
  explicitly unclaimed.
- Frontend production build passed. Vite emitted only its non-blocking
  greater-than-500-kB chunk advisory.
- `npm audit` reports zero known dependency vulnerabilities.
- Rust protocol/accessibility/supervisor suite: 11 tests passed.
- `cargo fmt --check`, `python -m compileall -q core dialektike tests`, and
  `git diff --check` passed.
- Canonical response fixture: 3,783 UTF-8 bytes; SHA-256
  `51a9b9c21de835584af106221bb10c867101ec0c9acdaa16f2d28c04cbc88330`.
- The release command rebuilt a new standalone sidecar candidate, but its
  PyInstaller smoke could not initialize a macOS semaphore inside the sandbox.
  The required outside-sandbox build approval was then rejected because this
  Codex session had reached its usage limit. Consequently the existing `.app`
  and DMG intentionally remain labelled pre-follow-up artifacts: no new hash,
  signature, disk-image, or packaged-smoke claim is made here.
- Browser-rendered reference comparison, primary/minimum layouts, search,
  topic-menu, and provider-control captures are in `desktop/artifacts/` and
  summarized in `design-qa.md`.

## 2026-08-24 active-turn timeout correction

- The failed packaged run `2026-08-23T16-09-43.662038Z-34a426` was not a
  billing, rate-limit, permission, or sidecar-startup failure. Its Codex parent
  remained active until roughly ten seconds before Dialektikḗ's former fixed
  600-second wall-clock cutoff, which then terminated the still-working turn.
- The 600-second boundary is now an exact-parent inactivity limit. Only
  schema-pinned activity carrying the matching `(threadId, turnId)` refreshes
  it; retryable parent errors count, while child turns, global rate snapshots,
  and terminal errors do not. A separate 3600-second active-runtime hard cap
  remains, and both bounds exclude Live's permission-card time by comparing in
  active-time monotonic coordinates.
- Idle/hard expiry sends one native `turn/interrupt` and drains the exact
  parent for five bounded seconds before closing. Live's Stop uses the same
  one-interrupt/bounded-drain discipline. The turn id is retained immediately
  after `turn/start`, so authoritative parent commentary is saved and emitted
  as a partial response on later failure.
- Only the typed timeout crosses the trusted display boundary, using fixed
  authored wording. Transport details remain owner-only; arbitrary adapter
  failures remain masked. Runtime-gate wording is unchanged.
- Focused evidence: 15/15 timeout invariants and 21/21 M2 control-flow tests
  passed. M1, M2 adapter, provider-contract, frontend (119/119), and Rust
  (16/16) checks also passed. A separate adversarial code review returned
  ACCEPT after its three edge-case challenges were covered.
- The frozen sidecar was rebuilt and smoke-tested, then the signed app and DMG
  were rebuilt. Standalone and bundled sidecar SHA-256:
  `91e1091d42d3aba827f333da567103adcd5743cac463199bb32c2bd3e5ae867b`.
  App executable SHA-256:
  `a0e821d04c3b129c70fd6594e9bf64518ef64effcbcb994df5bd824e8f6ab8be`.
  DMG SHA-256:
  `58f0597039075ff1cda4a39e081bb423c3e58ec3e9946b2f4d6d92bb01e2c9a4`.
  Strict deep signature verification, packaging freshness, bundled-sidecar
  identity, and `hdiutil verify` all passed. The pre-fix running process was
  quit and the corrected bundle relaunched at 2026-08-24 01:05 Asia/Singapore.

## Final audit and Live disposition — 2026-08-31

Claude Code independently reproduced 19/19 Python suites, 119 frontend tests,
the 4/4 real-Chrome suite, 16/16 Rust tests, `npm audit` with zero findings,
compilation/format/diff checks, artifact freshness, exact sidecar/app/DMG
hashes, sidecar bundle identity, and strict code-signature verification. Its
technical verdict was `ACCEPT` with no blocking defect.

The audit retained two non-blocking hardening notes: the participant topic
projection should become an exact allowlist before its schema grows, and the
remaining hard-coded colours should move behind the semantic token layer.

Live then approved the M2 progress and directed transition to the next
deliverables. The following boundaries remain truthful rather than being
retroactively claimed as completed observations:

- Packaged Light/Dark, Increase Contrast, Reduce Transparency, and VoiceOver
  checks remain manual and unclaimed.
- A separate post-timeout Project-folder model run was not added to the recorded
  evidence before Live's acceptance.
- Plug-in readiness is proven with an unanticipated synthetic provider, not a
  fabricated real seat. Adding a real third vendor requires Live to approve its
  adapter and an authenticated subscription-backed runtime.
