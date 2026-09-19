# Governance record 0008 — M2 acceptance

Date: 2026-08-31

Authority: Live (arbiter)

## Ruling

After Claude Code's final read-only audit returned `ACCEPT` with no blocking
defect, Live approved the M2 progress and directed the work to move to the next
deliverables. This is the acceptance ruling for the macOS desktop alpha.

M2 is preserved in the local accepted-M2 commit that follows this record. It is
never pushed to a remote. M1 remains frozen at `6c47d3e`.

## Evidence disposition

The acceptance relies on the reproduced source, frontend, real-browser, Rust,
packaging, freshness, signature, and disk-image evidence recorded in
`docs/UPGRADE_AUDIT_HANDOFF.md`. Acceptance does not fabricate evidence that was
not collected:

- packaged Light/Dark, Increase Contrast, Reduce Transparency, and VoiceOver
  checks remain manual and unclaimed;
- a separate post-timeout Project-folder model run was not added to the recorded
  evidence before acceptance; and
- the provider extension contract has a synthetic conformance proof, while the
  accepted bundle contains only the two real reviewed providers, Codex and
  Claude Code.

Claude Code recorded two non-blocking hardening notes for later work: replace
the participant topic-projection dictionary spread with an exact allowlist
before that schema grows, and move the remaining hard-coded colours behind the
semantic token layer.

## Next milestone boundary

Live has authorized transition to the next deliverables but has not yet selected
a third official runtime. No provider is to be invented, installed, or assumed.
A real third-vendor adapter is the leading bounded candidate only after Live
identifies the runtime and its subscription-only route can be positively
certified. Attachments, richer native content, dynamic plug-in loading, and the
later claim-ledger/adjudication engine remain separate possible scopes.
