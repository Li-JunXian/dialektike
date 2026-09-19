# Spike v2.x — implemented, NOT RUN

Status: v2.5 static corrections committed; awaiting Codex static audit (R10), then Live's
approval of `EXECUTION_MANIFEST.md` (v7). Every live model call is gated behind that
manifest plus the non-model `preflight.py`.

## What this spike proves (one structured run per subscription)

- one schema-shaped verdict turn per runtime (Claude via Agent SDK, Codex via app-server
  JSON-RPC against the vendored 0.139.0 schema), verdict bound to the active thread/turn;
- session/thread resume across separate processes with identity assertions;
- **native permission parity** (governance 0002): the ONLY cards are the native runtimes'
  own approval requests, relayed exactly once through the shared provider-neutral
  `core/relay.py` PermissionRelay; natively auto-permitted actions (a workspace Read)
  produce ZERO cards and are audit-logged with hook-proven completion;
- a native Write approved and a native Write denied at the card, with filesystem proof;
- subscription-only billing, positively evidenced per phase on both legs.

## The moving parts

| File | Role |
|---|---|
| `run_contract.py` | THE contract: phases, roles, tool sets, exact expected actions, evidence inventory. Everything else derives from it. |
| `claude_leg.py` | Claude adapter: native tools under a LABELED controlled profile (`setting_sources=[]`, per-phase `tools`), `can_use_tool` → relay, PostToolUse hooks → audit records, env allowlist + positive billing gate. |
| `codex_leg.py` | Codex adapter: app-server client, native approvals → relay (wire mapping only), pinned first-party `modelProvider`, close-before-health, malformed stdout fatal. |
| `core/relay.py` (repo root) | Provider-neutral PermissionRelay: durable idempotent exactly-once (claim → card → decision in the hash-chained log; replays answered from the record; conflicts fatal). |
| `verify_run.py` | Post-run verifier: full-contract, ledger bijection, strict evidence inventory. Parameterizable roots. |
| `synthetic_check.py` | Fabricates a complete run's evidence through the real relay code path; proves the verifier CAN pass and fails correctly under every mutation. |
| `preflight.py` | Non-model gate run immediately before manifest command 1. |
| `EXECUTION_MANIFEST.md` | The exact list Live approves. Nothing else runs. |

## Exactly-once (Live's ruling, as of governance 0002 + R9)

One native request → one card → one durable decision. The relay claims each correlation
key atomically in the chained log BEFORE presenting; an exact wire retransmission gets the
recorded answer with no second card; a correlation key reused with different content fails
the phase. Dedup is keyed on wire-request identity — if the native runtime genuinely asks
again, Live is asked again, exactly as the native UI would.

## Superseded designs (kept for the record, do not resurrect)

- v2–v2.3's `tools=[]` + platform MCP substitute tools ("universal gating") — replaced by
  native parity per governance 0002; the R4-era finding that `can_use_tool` doesn't gate
  pre-permitted reads is now the *expected* native behaviour, audit-logged via hooks.
- The v2.2 auto-decline responder for Codex approvals — native requests are forwarded.
- The sandbox-exec confinement investigation and the six-condition structural-absence gate.
