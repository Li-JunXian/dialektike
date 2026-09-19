# Dialektikḗ upgraded desktop — design QA

## Evidence target

- Approved visual: `desktop/artifacts/reference-roundtable.png`
- Rendered implementation: the Vite desktop preview at port 1420
- Same-frame comparison: `desktop/artifacts/upgrade-reference-comparison.png`
- Primary implementation capture: `desktop/artifacts/upgrade-1488x1058.png`
- Minimum-window capture: `desktop/artifacts/upgrade-720x640.png`
- Interaction captures: `desktop/artifacts/upgrade-search-results.png`,
  `desktop/artifacts/upgrade-topic-menu.png`, and
  `desktop/artifacts/upgrade-provider-controls.png`
- Packaged artifacts: `desktop/src-tauri/target/release/bundle/macos/Dialektikḗ.app`
  and `desktop/src-tauri/target/release/bundle/dmg/Dialektikḗ_0.2.0-alpha.0_aarch64.dmg`

The reference and implementation were captured at the same 1488×1058 viewport
and placed together in one comparison input. The implementation preserves the
reference's calm two-lane hierarchy while adding the approved participant
controls, stage labels, transparent composer overlay, and appearance choices.

## Rendered verification

- Tested 162 viewport widths from 720 through 3840 CSS pixels, including the
  880 and 1080 breakpoints at −1/0/+1, plus 720×640, 880×720, 1180×820,
  1488×1058, and 3840×820.
- Maximum measured difference among the workspace centre, Live seat, Live
  prompt, and composer centre was `0.00390625px`.
- Maximum difference between the conversation lane midpoint and workspace
  centre was `0.00390625px`.
- No tested width produced horizontal document overflow.
- A committed Vitest Browser Mode regression mounts the real application and
  stylesheet in the installed Chrome, exercises all 164 width/height
  configurations, and repeats them after injecting long code, a wide table, a
  long citation, unbroken prose, and enough height to activate the internal
  conversation scrollbar. Both 164-configuration passes succeeded.
- At 1488×1058, the workspace and all Live-centred elements measured exactly
  `894px`; the Executor inner edge was `864.2421875px` and Auditor inner edge
  was `923.7578125px`, an exactly mirrored gutter around the centre.
- Proposal and Audit start in parallel lanes. Synthesis remains on the
  Executor's left rail and starts after the final Audit's lower edge.
- The composer is an overlay rather than an opaque third layout row. The final
  conversation remains scrollable behind it with reserved bottom reachability.
- Content search displayed three structured occurrences for a content-only
  query, with stage labels and authored-text highlights. Selecting a result
  closed the dropdown, opened the topic, and applied a non-colour-only target
  outline to the correct Proposal anchor.
- The topic overflow menu rendered through its portal without clipping, in the
  required Rename, Unpin, Archive, Delete order, with keyboard focus on the
  first action.
- Provider controls rendered through the generic descriptor contract. The
  preview exposed model, effort, speed, execution profile, thinking, and
  owner-visible evidence details without a provider-ID UI branch.
- Recorded preview captures produced no application console errors. The Browser
  Mode harness emits React `act`-environment warning noise that does not fail its
  assertions. Frontend tests separately cover pre-hydration System/Light/Dark selection, exact
  CSS↔TypeScript token parity, contrast, reduced-transparency status, portal
  positioning, semantic status, structured content, generic provider parsing,
  and object/array permission-presentation pointers.
- A second real-Chrome regression forces parent rerenders while the topic menu
  is open and confirms that keyboard focus remains on the selected action.
- A third regression exercises the Context and Latest run evidence summaries
  through the transparent composer overlay.

## 2026-08-21 Projects, explicit choices, and sidebar follow-up

- The supplied Codex desktop screenshot was used as a structural reference for
  the sidebar proportion, collapse affordance, and folder-oriented Project
  hierarchy. Dialektikḗ keeps its own round-table workspace; this is not
  represented as a pixel clone of the Codex screen.
- In the in-app Browser at 1512×982, the expanded sidebar measured `264px` and
  the collapsed rail measured `62px`. The collapsed rail retained New Topic,
  Archived, appearance, and expansion controls while hiding the full Project
  and topic lists.
- At the expanded size, the workspace centre, Live seat, Live prompt, and
  composer all measured at the same horizontal centre. The left/right inner
  conversation gutters differed by only `0.0078125px`; no horizontal document
  overflow was present.
- The Project disclosure displayed the exact native-working-directory warning
  and initially focused Cancel. The path-selecting action remains a trusted
  native control and the folder path is never present in the rendered DOM.
- Both provider pickers omitted pseudo-Default model choices. Codex required a
  concrete model and Ultra selection; Claude Code required a concrete Opus and
  Extra high selection in the discovered preview catalog.
- The one-click Swap control was exercised. It exchanged `Codex · GPT-5.6 Sol
  · Ultra` with `Claude Code · Opus · Extra high` as complete seat
  assignments while the Executor and Auditor rails remained fixed.
- A second Swap check opened an already completed cycle, swapped the current
  seats, and confirmed its historical Proposal remained labelled `Codex`
  rather than being relabelled with the seat's new Claude Code assignment.
- A new topic inherited the selected `dialektike` Project and runtime seats,
  then correctly began with blank model/effort selections. The preview console
  contained only Vite/React development notices and no application error.
- The final real-Chrome Browser Mode suite now passes all four tests. Its
  164-viewport ordinary and long-content matrix covers 720–3840 CSS pixels,
  verifies zero horizontal overflow, exercises the 62px collapse/expand state,
  and confirms Context/Evidence clickability through the composer overlay.

## Pre-follow-up packaged-artifact evidence

- The arm64 frozen sidecar rebuilt after all governed Python and descriptor
  inputs and passed its no-model JSONL and trusted-disclosure smoke tests. Its
  SHA-256 is
  `1fe58a219af04cea039f21beea94258d33e24a7a533cc26a01d3a2f6a7731127`,
  exactly matching the copy sealed into the application bundle.
- The pre-follow-up Tauri application bundle rebuilt from its verified sidecar.
  `codesign --verify --deep --strict` passed; `codesign -dv` reports a thin
  arm64 bundle with ad-hoc hardened-runtime signing and identifier
  `com.live.dialektike`.
- The pre-follow-up Tauri DMG build completed through the native macOS disk-image
  helper. `hdiutil verify` reports a valid checksum. The DMG SHA-256 is
  `9741581af9ba30dbce5208dd6834be47ab02d0a630d1272e107e529f1c3f024b`.
  A read-only mount confirmed that its app executable and sidecar hashes match
  the standalone bundle exactly, and strict signature verification passed on
  the mounted app.
- The application executable SHA-256 is
  `fe4bd24e40a19c08c49e33594170c244b4757f30b6efd2e193c10573e93af0a7`.
- The repository's no-model JSONL and trusted-disclosure smoke functions passed
  when run directly against the sidecar inside that application bundle.
  The packaging invariant suite also passed against those bundle inputs.
- These hashes and checks describe the bundle built before Live's 2026-08-16
  startup/Context/Evidence follow-up. They remain useful provenance but are not
  acceptance evidence for the corrected source.

## Current package status

The accepted source, frozen sidecar, `.app`, and DMG were rebuilt together on
2026-08-24 after the active-turn-timeout correction.

- Frozen sidecar SHA-256:
  `91e1091d42d3aba827f333da567103adcd5743cac463199bb32c2bd3e5ae867b`.
  The standalone sidecar and the copy sealed into the `.app` are byte-identical.
- Application executable SHA-256:
  `a0e821d04c3b129c70fd6594e9bf64518ef64effcbcb994df5bd824e8f6ab8be`.
- DMG SHA-256:
  `58f0597039075ff1cda4a39e081bb423c3e58ec3e9946b2f4d6d92bb01e2c9a4`.
- `codesign --verify --deep --strict` passed for the rebuilt application.
- `hdiutil verify` passed and reported a valid disk-image checksum.
- The packaging invariant that previously detected the stale sidecar now
  passes; the release build also ran the frozen sidecar's no-model JSONL and
  trusted-gate smoke checks before bundling. Claude Code independently
  reproduced the package identity, freshness, and verification evidence before
  returning `ACCEPT` on 2026-08-31.

One visual check remains deliberately unclaimed: automated capture of the
packaged WKWebView. macOS previously denied Apple Events access to System
Events, so no packaged-window screenshot is promoted as evidence. Capturing the
whole desktop would risk unrelated private content and was not used as a
workaround. The final-source browser geometry and interaction evidence above is
current. Live accepted M2 on 2026-08-31 while leaving this manual visual check
truthfully unclaimed.

final result: source verification pass; four-test Browser Mode pass; corrected
package rebuild and cryptographic verification pass; Claude Code `ACCEPT`; Live
M2 acceptance. The manual packaged visual boundary above remains recorded.
