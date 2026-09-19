# Governance record 0002 — Mode A clarification: native-parity permission relay

Date: 2026-07-13 (recorded during WP v2.3, before any re-scoped code was written)
Author of ruling: Live (arbiter). Recorded verbatim by Claude (executor).

## Live's ruling (verbatim)

> Mode A clarification: I do not require every model action to generate a permission
> request. I require Dialektikḗ to relay exactly the permission requests I would
> normally receive in Claude Code or ChatGPT Desktop/Codex, once and without
> modification. Do not create additional prompts for actions the native runtime
> permits automatically. Log those actions for audit only. Re-scope v2.3 accordingly;
> sandbox-exec is not required for manufacturing universal permission gates, and
> native Codex approval requests must be forwarded rather than automatically declined.

## What this supersedes

1. The reading of axiom 2 ("all actions by the LLMs … must all request for my
   permission") as *universal per-action gating*. The governing standard is now
   **native parity**: Dialektikḗ surfaces exactly the permission requests the
   native runtime (Claude Code / ChatGPT Desktop / Codex) would surface, exactly
   once, unmodified (deterministic enrichment still allowed per the exactly-once
   ruling in record 0001). Actions the native runtime auto-permits proceed
   without a Dialektikḗ prompt and are **logged for audit only**.
2. R7 finding P0-1's remedy chain: the six-condition structural-absence gate for
   live Codex turns and the sandbox-exec confinement requirement are withdrawn.
   Live Codex turns are permissible under native permission semantics
   (read-only sandbox, `approvalPolicy: "untrusted"`, `approvalsReviewer: "user"`,
   approvals forwarded to Live).
3. The v2.2 auto-decline responder for Codex approval requests. Auto-declining a
   native approval request is now a defect: it must be **forwarded to Live**.
4. The "ambient item ⇒ hard phase FAIL" detection-net rule. Ambient items
   (commandExecution, fileChange, webSearch, mcpToolCall, collabAgentToolCall,
   imageView, imageGeneration) are recorded verbatim to evidence and summarized
   for audit; they are not, by themselves, failures.

## What stands unchanged

- R7 P0-2 (environment allowlist for the Claude worker; one environment for
  preflight and SDK child; abort on billing/provider selectors).
- R7 P0-3 (no agentMessage fallback: the Codex verdict must arrive via the
  registered dynamicTool, bound to the active thread and turn).
- All R7 P1 correctness findings (strict state machine, exact legacy enums,
  full-fingerprint decision proofs, chain-verified derivation, locked anchoring,
  thread joins, filename sanitization, honest provenance, real post-run verifier).
- Billing axioms (subscription only, fail closed), exactly-once surfacing,
  explicit go per work package, anchor receipts, schema-over-testimony.
- SafetyAttestation (adopted from Codex R7): each leg records its billing route,
  model, effective configuration, and permission-relay wiring before the first
  turn, and refuses to start if a required field cannot be evidenced. The
  "ambient surfaces structurally absent" field is removed per this ruling.

## Relay mappings (schema-pinned, vendor/codex-app-server-0.139.0)

| Native request (server→client) | Live allows → | Live denies → |
| --- | --- | --- |
| `item/commandExecution/requestApproval` | `{"decision":"accept"}` | `{"decision":"decline"}` |
| `item/fileChange/requestApproval` | `{"decision":"accept"}` | `{"decision":"decline"}` |
| `execCommandApproval` (legacy) | `{"decision":"approved"}` | `{"decision":"denied"}` |
| `applyPatchApproval` (legacy) | `{"decision":"approved"}` | `{"decision":"denied"}` |
| `item/permissions/requestApproval` | grant exactly the requested profile, `scope:"turn"` | `{"permissions":{}}` |

Non-approval interactive requests (`item/tool/requestUserInput`,
`mcpServer/elicitation/request`) are NOT approval requests; in the spike they are
declined fail-closed and audit-logged. Forwarding their content flows is alpha
scope. Known unhandled server requests (`account/chatgptAuthTokens/refresh`,
`attestation/generate`) receive a JSON-RPC error and are audit-logged; if one
appears the turn may fail natively — re-authenticate with `codex login` and rerun.

## Correction (appended 2026-07-13, after Codex audit R8 — original text above unerased)

Supersession item 2's parenthetical welded a specific strict configuration
(read-only sandbox, `approvalPolicy: "untrusted"`) into the *definition* of
native parity. That was the recorder's interpretive error, challenged by Codex
in R8 and conceded:

- **Native parity governs RELAY semantics only**: whatever approval requests
  the native runtime raises — under whichever configuration is in effect — are
  forwarded once, verbatim; auto-permitted actions are audit-logged.
- **The configuration itself is a separate, disclosed choice** (an
  ExecutionProfile, governance 0003). The spike uses a labeled controlled
  profile because a strict, deterministic surface is what Live approves via the
  execution manifest; the platform's default profile is *inherit native
  settings*. A stricter profile legitimately produces MORE native asks — those
  are still native runtime requests, not platform-manufactured prompts.

Also corrected in the same round: two per-adapter prompt surfaces violated the
one-relay principle; both adapters now submit normalized native requests to the
shared `core/relay.py` PermissionRelay, and R8 finding 7 is conceded — unknown
or non-approval server requests are declined fail-closed on the wire AND fail
the spike (they cannot coexist with a clean PASS).
