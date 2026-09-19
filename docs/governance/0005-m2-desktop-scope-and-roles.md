# Governance record 0005 — M2 desktop scope, roles, and capability truth

Date: 2026-07-24

Authority: Live (arbiter)

## Ruling

Live accepted M1, appointed Codex as M2 Executor and Claude Code as Auditor,
and required M2 itself to be a modular macOS desktop application with
model/effort/speed selection. This expressly supersedes the earlier milestone
ordering in which M2 contained CLI controls and the GUI waited until M6. It
does not weaken any M1 axiom.

The current assignments are:

- Executor: Codex, runtime id `codex`, ChatGPT subscription.
- Auditor: Claude Code, runtime id `claude-code`, Claude subscription.
- Arbiter and sole permission authority: Live.

Role and runtime identity are independent. Live may reassign roles later; a
model cannot reassign itself or the other participant.

## Capability truth

Selectors are populated from runtime evidence, not product-name inference:

- Codex models, compatible reasoning efforts, and service tiers come from the
  complete paginated app-server `model/list` response.
- Claude Code models and advertised effort compatibility come from the Agent
  SDK initialization catalog returned by `get_server_info()`. The first
  assistant message authoritatively echoes the effective model. Until the
  runtime provides a comparable effective-effort acknowledgement, the record
  distinguishes the requested, catalog-validated effort from an echoed value.
  The SDK is explicitly bound to the same Finder-resolved installed Claude
  Code executable whose first-party subscription auth and version were gated;
  a PyInstaller-extracted copy is not accepted as equivalent Keychain
  authority.
- Requested and effective model, effort, and service tier are recorded
  separately. Unsupported explicit choices fail closed; no silent fallback.
- “Ultracode” and “workflows” are product/mode labels, not values smuggled into
  the model, effort, or service-tier fields.
- A faster mode that incurs usage outside either subscription is visible only
  as unavailable under axiom 1, with the reason retained. Claude Fast is extra
  usage from its first token and remains unavailable. Codex Fast is allowed
  only while `account/rateLimits/read` positively proves the account has no
  purchased-credit or unlimited spend facility; that guard is repeated
  immediately before the turn, so its increased usage can only deplete the
  included plan allowance.

The default requested profiles are:

```text
Executor: codex       / gpt-5.6-sol / ultra / native standard tier
Auditor:  claude-code / opus / xhigh / native default tier
```

These are requests, not evidence of what ran. Every run must show the runtime's
effective values or stop before substantive execution when they cannot be
verified.

## Provider-drift addendum — 2026-07-26

Live's original default named Claude Opus 4.8. During final packaged-runtime
verification, the newest authenticated installed Claude Code runtime
(2.1.220) authoritatively advertised `opus` as `claude-opus-5`; 4.8 was absent
from its catalog. A live no-tool `opus`/`xhigh` probe echoed
`claude-opus-5`. Dialektikḗ must not silently pin an obsolete runtime or
mislabel that result as 4.8, so the requested default remains the stable
native `opus` selector and the UI records the effective model. Live retains
the final ruling on this drift.

## Implementation consequence

M2 uses a thin Tauri 2 + React/TypeScript macOS shell over a supervised,
versioned-JSONL Python sidecar. The existing Python governance core and CLI
remain authoritative and permanent. The GUI is part of the control/security
plane, but receives neither generic shell access nor provider credentials.

The current M2 directive and acceptance bar are in
[`DIRECTIVE.md`](../../DIRECTIVE.md).
