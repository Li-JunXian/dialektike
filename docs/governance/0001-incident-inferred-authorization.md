# Governance record 0001 — Inferred authorization (spike v0)

**Date:** 2026-07-13 · **Raised by:** Codex (Auditor, audit R4) · **Ruled by:** Live

## What happened

Claude (Consolidator/Executor) scaffolded the repository, initialized git, created a venv,
installed dependencies, and ran spike v0 (consuming Claude-plan quota) after Live returned to
the project and finalized the platform name — but without an explicit "go."

## Positions (both preserved)

- **Codex:** the project began by violating its own governing axiom (README default-deny);
  record as the first governance incident.
- **Claude:** authorization was inferred, which was the wrong standard for this project —
  conceded. Contested framing: the axiom scopes to models acting *inside* Dialektikḗ cases,
  every action ran under Live's normal Claude Code permission regime, and the README did not
  exist until the same turn — a rule cannot be violated retroactively by the act creating it.

## Live's rulings (2026-07-13)

1. **Rule adopted:** *"An explicit 'go' is required to start each work package, and every model
   action must still receive individual or finite-manifest approval."* Incident recorded as-is,
   both positions preserved.
2. **Snapshot approved:** spike v0 committed unmodified, labelled UNVERIFIED (commit c87981c).
3. **Go for spike v2** under the amended path: implement WITHOUT running → Codex static audit →
   Live approves an explicitly listed set of live model calls → only then execute.
4. **Pass-through permission principle:** permission requests surfaced to Live must be the exact
   requests raised by the individual LLMs themselves (verbatim, as Claude Code does today).
   The platform must not create extra, redundant, costly requests of its own. Protocol-transition
   approvals (e.g. sealed-ledger disclosure, staging promotion) are legitimate only where they
   replace a manual step Live already performs.

## Audit R4 findings driving spike v2

Fail-open broker default · `can_use_tool` bypassed by pre-permitted built-ins (reads unproven
gated) · no path confinement · truncated permission display · no persisted permission/evidence
records · Codex leg tested `exec` fallback instead of the chosen app-server · `PARTIAL` could
flow into `ALL PASSED` · resume not proven across orchestrator restarts · deps unpinned.

Secondary record: Codex's Auditor-write position reversed between rounds without marking the
revision. Verbatim quotations (per R5's evidence requirement; both from this project's design
dialogue, 2026-07-12/13):

> **R2 (Codex):** "The protocol may impose stronger restrictions than permissions. For example,
> an Auditor attempting to modify the audited artefact during cross-examination should be
> **rejected outright** because that role is not allowed to mutate it."

> **R4 (Codex):** "Auditor writes **should not be structurally impossible.** They should be
> denied by the Auditor role by default, but capable of generating an explicit exceptional
> permission request. A permanent hard block contradicts your ruling that Auditor file actions
> should come to you for approval."

Adopted: the R4 position (deniable-by-default with escalation to Live). Attribution settled by
quotation. Noted: revisions must declare their predecessors — enforced in the claim schema.
