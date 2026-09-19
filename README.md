# Dialektikḗ · Διαλεκτική

> Development snapshot: accepted M2 plus the unfinished chat-first/review-on-request increment. Source tests and live adapter checks passed on 17 September 2026; a fresh packaged demonstration and independent code audit remain pending. This is not a newly accepted release.

**A human-governed multi-model dialectic review platform.** Personal, private, local, single-user.

Implements the Multi-LLM Dialectic Cross-Examination Protocol in software: heterogeneous LLMs
(Claude + Codex, via their subscription runtimes) hold structured adversarial roles over versioned
claims; the human arbiter — Live — rules on every claim and answers every native permission
request, relayed exactly once (axiom 2 below).

> διαλεκτική — the art of reaching truth by arguing it through.
> 字诀:锁题 → 列证 → 互审 → 整合(含反驳) → 审核 → 定夺 → 执行 (→ 复盘)

## Axioms (Live's rulings — non-negotiable)

1. Personal tool. No product, no hosted service, no multi-user auth, no billing.
2. **Native permission parity** (governance 0002, superseding the earlier universal-gating
   reading). Provider-generated approval requests are passed through to Live verbatim and
   exactly once, enriched only with deterministic data. Actions the provider runtime permits
   without prompting remain unprompted and are audit-logged. Dialektikḗ creates no synthetic
   action requests; platform-owned transitions (revealing sealed proposals, promoting staged
   changes) carry their own approvals. Permission verbs: *Allow once / Deny / Approve exact
   finite action manifest*. No open-ended session grants. Permission to one model never
   transfers to another. Approving a claim never approves execution.
3. Subscription auth only (Claude plan + ChatGPT plan). Official runtimes own credentials;
   the platform never reads or stores raw credentials.
4. CLI first as the proving instrument; desktop GUI immediately afterward as the primary
   interface. The CLI is kept permanently for diagnostics and recovery.

## Architecture (converged via Mode A dialectic, 2026-07-12/13)

```text
Shared local core/daemon
├── Protocol engine          — 字诀 state machine; sealed rounds enforced in software
├── Claim-and-objection store — immutable, versioned; lineage C4 v1 → O7 → C4 v2 never overwritten
├── Permission relay + broker — ONE provider-neutral PermissionRelay (core/relay.py): native
│                              requests in, exactly-once cards out, hash-chained decision log;
│                              broker manifests layer finite pre-approvals on top
├── Provider adapters        — Claude: Agent SDK (can_use_tool + hooks → relay)
│                              Codex: app-server JSON-RPC (native approvals → relay);
│                              adapters own only wire mapping (governance 0003)
├── CLI client               — permanent
└── Desktop GUI client       — Tauri-wrapped local web UI; part of the control/security plane
```

M2 storage remains the proven owner-only append-only JSON/JSONL evidence plus
raw captures. **SQLite** (authoritative append-only claim ledger) and
content-addressed evidence snapshots remain later protocol-engine scope;
**git** is for approved artefact versions and human-readable exports only.
Models use their runtimes' **native tools inside Live-approved ExecutionProfiles** (default:
inherit native settings; controlled profiles are labeled options — governance 0003). Native
approval asks are relayed; auto-permitted actions are audit-logged (governance 0002).
Writes land in staging; promotion to canonical artefacts is a separate approval (diff shown).

## Roadmap

1. **M1 accepted — CLI MVP** (`6c47d3e`): prompt → Claude → Codex, displayed
   and owner-only saved, with native-parity permission relay and subscription
   gates.
2. **M2 accepted — macOS desktop alpha** (Live, 2026-08-31): Tauri control plane, modular
   participants/adapters, runtime-truthful model/effort/service-tier selectors,
   one Proposal -> independent parallel Audit(s) -> one Synthesis per review
   cycle, canonical topic sessions, role reversal, rounds and Stop; permanent
   CLI retained. The 2026-08-10 upgrade adds safe rich-content transport,
   descriptor-driven provider controls, full-text occurrence search, topic
   context checkpoints, accessible appearances, reliable topic actions, and a
   provider plug-in boundary. The 2026-08-21 workflow update adds explicit
   model/effort selection, Live-controlled whole-seat swapping, folder-backed
   Projects, and compact collapsible navigation.
3. **Next milestone — to be ruled by Live**: the leading bounded candidate is
   one real third-vendor adapter, subject to an official installed runtime and
   positively certified subscription-only account route.
4. **Later protocol engine**: claim ledger, sealed cross-examination,
   adjudication bench, hierarchy and optional strict-audit mode.

## M2 desktop

Build the owner-local Apple-silicon app from the repository root:

```sh
cd desktop
npm run tauri -- build --bundles app,dmg
```

The Tauri release pre-build automatically freezes and smoke-tests the current
Python sidecar before compiling the WebView and native shell, so a stale
sidecar cannot be copied into a new application bundle. The no-model smoke
also proves that authored gate verdicts remain visible while arbitrary
capability failures remain masked. The sidecar can still be rebuilt independently with
`./venv/bin/python scripts/build_macos_sidecar.py` for diagnostics.

The resulting application is
`desktop/src-tauri/target/release/bundle/macos/Dialektikḗ.app`. It is ad-hoc
signed for Live's machine, not notarized for distribution. On startup it
discovers the exact authenticated Codex and Claude Code catalogs; requested
and effective settings remain separate. As of 2026-07-26 the newest installed
Claude Code runtime resolves the native `opus` selector to `claude-opus-5`;
the UI records that effective value rather than retaining the earlier Opus
4.8 label.

Codex and Claude Code are the initial runtime seats, not preselected model
profiles. New Topic retains those runtime seats but begins with blank model and
effort selections. Before starting a run, Live chooses a concrete model and
every effort the selected model advertises. Runtime pseudo-models such as
`Default (recommended)` do not
count as concrete selections. A model with no effort selector needs no invented
effort. `Native default` for Speed means no service-tier override; it remains
available beside discovered optional tiers and is the sole choice when there
are none. Requested and runtime-certified effective values remain
separate evidence.

The upgraded desktop keeps one Executor and supports any number of independent
Auditors from distinct vendors. Available seats come only from statically
reviewed provider adapters whose authenticated discovery succeeds. Shared
Python, Rust, JSONL, and frontend layers consume versioned inert provider
descriptors, so a future provider adds its adapter, approved registration data,
packaging entry, and conformance fixtures without provider-ID branches in the
shared application. No third-vendor seat is claimed in the current bundle:
only Codex and Claude Code have approved, authenticated adapters today.

The Swap control exchanges the Executor's complete runtime assignment with one
Auditor while leaving stable topic seats and history in place. With one Auditor
it is a direct action; with several, Live chooses the Auditor first. Swapping is
locked while a model operation is active and never bypasses the distinct-vendor
or capability checks.

### Projects and focused folders

The sidebar groups topics under `General` or a Live-declared Project. Choose
`Open Folder`, review the working-directory disclosure, and use the native macOS
folder picker. New Topic inherits the currently selected Project; the compact
Project selector above the conversation can relink a settled topic.

For a Project-bound topic, every participant turn and topic-context checkpoint
uses the same revalidated canonical folder as its native working directory.
Provider-native auto-permitted actions may therefore modify that folder without
a Dialektikḗ card, exactly as disclosed; those actions remain audited under
native permission parity. Dialektikḗ does not create, chmod, or silently
retarget the external folder. A missing, moved, inaccessible, or non-canonical
folder blocks the operation until Live reselects or unassigns the Project.

The folder path crosses only the trusted macOS picker → Rust supervisor →
owner-only Python registry path. It is never accepted from or returned to the
WebView; the ordinary UI receives only Project identity, name, registration
time, and availability. General topics continue using isolated generated
workspaces.

The topic sidebar is 264 CSS pixels at ordinary desktop widths and collapses to
62 pixels, with narrower responsive values near the minimum supported window.
Its labelled Collapse/Expand control remembers the owner-local preference and
keeps the main roundtable centered in the workspace that remains.

Topic search covers titles and visible conversation occurrences using a derived
NFKC+casefold index while preserving authored text exactly. `Context` creates a
reviewable Executor checkpoint draft; only Live can activate it, original
history remains append-only, and provider-native compaction never silently
changes the topic checkpoint. `Latest run evidence` is a bounded, read-only
governance summary for the selected topic's newest linked run: it reports gates,
rate observations, permission/audit counts, capture inventory, and a freshly
verified decision-chain result without exposing raw contents or invoking a
model. `System`, `Light`, and `Dark` appearances use
semantic contrast tokens and respond to macOS Increase Contrast, Reduce
Transparency, and Reduce Motion state.

The permanent diagnostic CLI remains:

```sh
./venv/bin/python -m dialektike "your prompt"
```

## Naming

Display **Dialektikḗ** (ḗ = U+1E17: eta transliterated with macron + ancient pitch accent) ·
emblem **Διαλεκτική** · repo & CLI **`dialektike`** (one ASCII spelling everywhere) ·
bundle id `com.live.dialektike`.
