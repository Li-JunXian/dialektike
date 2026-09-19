# Governance record 0003 — modularity: plug-and-play providers, models, efforts, roles

Date: 2026-07-13 (stated by Live alongside the R8 audit round).
Author of requirement: Live (arbiter). Recorded verbatim by Claude (executor).
Provenance note: this file was first written before any work-package go — a
process deviation recorded in [0004](0004-incident-premature-governance-write.md).
Revised and committed inside WP v2.4 per Live's conditional GO.

## Live's requirement (verbatim)

> By the way, I wish to add that this platform should be very modularised and
> customisable where the LLMs are plug-and-play, I can choose what Models I want
> on the platform (e.g. I want Claude and ChatGPT - which I do have the
> subscription plans) and I can choose the models of Claude (e.g. Fable 5,
> Opus 4.8 or etc.) or ChatGPT (e.g. ChatGPT-5.6 Sol, ChatGPT-5.6 Tera or etc.)
> as well as their corresponding levels of Effort (Extra High, Max, Ultra,
> Ultracode or etc.)
> Also I want the platform to allow me to switch the roles of the LLMs anytime
> I want. For instance when I feel that ChatGPT 5.6 Sol performs better at a
> certain task than Claude, I can manually set ChatGPT as the first engineer
> and Claude as the auditor, and vice versa. Completely flexible.

## Interpretation (Codex R8 + R8.1 amendments, endorsed by Live)

Six separated concepts, designed into CLI alpha from the start (not retrofitted):

- **ProviderAdapter** — Claude, Codex, future runtimes. Owns transport,
  authentication proof (subscription billing evidence), capability discovery,
  session lifecycle, event normalization, and wire-specific mappings. Nothing else.
- **ModelProfile** — provider + runtime model id + effort/reasoning level +
  service tier. **Discovered from the runtime where supported** (Codex:
  `model/list` returns required `id`/`model`/`displayName`/
  `supportedReasoningEfforts` — vendored `v2/ModelListResponse.json`); where
  discovery is unsupported, configured IDs are accepted and **validated against
  the runtime before execution**.
- **ExecutionProfile** — filesystem scope, sandbox/permission policy, approval
  configuration. **Kept separate from ModelProfile: changing models must never
  silently change filesystem or permission policy.** The platform's default
  ExecutionProfile is *inherit native settings*; controlled profiles (like the
  spike's) are explicit, labeled options.
- **Participant** — one configured model/session taking part in a case.
  **N ≥ 2 participants supported**, even while the initial UI emphasizes two.
- **RoleAssignment** — participant → role (First Engineer, Auditor, Consolidator,
  Executor, …), versioned per round, recorded as an immutable event. **Switching
  is immediate between turns**; during an active turn Dialektikḗ first cancels or
  completes that turn, then starts a fresh role-bound session so prior role
  instructions cannot contaminate the new role.
- **PermissionRelay** — ONE provider-neutral relay used by every adapter (and
  later the GUI): adapters submit normalized native requests; the relay owns
  presentation, exactly-once semantics, and logging; each adapter retains only
  its wire-specific response mapping. First implementation: `core/relay.py`
  (WP v2.4).

## Scope

Binding on CLI alpha architecture and everything after. The v2.x spike keeps its
pinned models/config for manifest determinism; it does not need to implement
discovery or role switching, but must not entrench structures that contradict
this record (hence the shared relay lands in the spike already).
