# Spike v2.6 — Execution manifest v9 (DRAFT — awaiting Codex static audit R13, then Live's approval)

Nothing below runs until Live approves this exact list. Anything not listed is not authorized.
This manifest MIRRORS `spike/v2/run_contract.py` (CASE `spike-v2.6`) — the single
machine-readable contract the legs execute, `verify_run.py` checks, and `synthetic_check.py`
proves passable. Seven phases: five Claude, two Codex.

**Incident-001 (2026-07-14, evidence preserved in `evidence/incidents/`):** the first live
attempt failed fail-safe. This manifest version exists because of it: execution is now
RUNNER-ENFORCED — Live types exactly ONE command, and `spike/v2/run_manifest.py` does the
rest (preflight once, per-phase source attestation, isolated per-run evidence directory
`evidence/runs/<run-id>/`, stop on first failure, cards inherited to Live's terminal,
never answered automatically).

Permission semantics per **governance 0002 (+ R8 correction appendix)**: native runtime
approval requests are relayed to Live once, verbatim, through the shared PermissionRelay
(`core/relay.py`); natively auto-permitted actions are audit-logged only; no prompts are
manufactured. Both legs run a **labeled controlled spike ExecutionProfile** — deterministic
for this manifest, explicitly NOT Live's native defaults (governance 0003; platform default
is inherit-native-settings).

## The ONE command Live runs (after approving with the audited hash)

```bash
./venv/bin/python spike/v2/run_manifest.py --expected-commit <R13-audited-hash>
```

The hash is supplied EXTERNALLY in Live's execution-approval command — deliberately not
written in this file (a committed file cannot contain its own commit hash; the binding is
Live's approval text → HEAD). Stop reading terminal output only at cards; everything else
is automatic, and the runner stops itself on any failure.

## Preconditions (enforced IN CODE — runner/legs abort, fail closed, if unmet)

1. **Preflight gate, run ONCE by the runner before any quota use:** exact
   `git rev-parse HEAD` == approved hash AND worktree clean including untracked files
   (checked FIRST, short-circuiting); the run's evidence directory does not pre-exist;
   `codex --version` token EXACTLY 0.139.0; positive first-party Claude auth; all spike
   modules compile; both committed invariant suites pass; the synthetic evidence-layout
   suite passes (the verifier provably CAN pass). All `git` integrity commands fail closed
   on nonzero exit (R11 backlog).
2. **Per-phase source attestation (incident-001 TOCTOU closure):** before EVERY phase the
   runner re-checks HEAD == approved hash and that nothing changed outside this run's own
   evidence directory. Phases REFUSE to start without the runner
   (`DIALEKTIKE_RUN_DIR` unset → abort).
3. Claude leg reduces its own environment to the allowlist (`HOME PATH USER LOGNAME SHELL
   TMPDIR LANG LC_ALL LC_CTYPE TERM`) and ABORTS if any `ANTHROPIC_*`, `CLAUDE_CODE_USE_*`,
   or `OPENAI_API_KEY` selector is present; the SAME environment serves `claude auth status`
   and the SDK subprocess. `claude auth status` must return JSON with `loggedIn: true`,
   `authMethod: "claude.ai"`, `apiProvider: "firstParty"` (positive evidence) and no
   API-key/Console/Bedrock/Vertex/Foundry marker.
4. Codex `account/read` must return `account.type == "chatgpt"`, AND the effective
   `modelProvider` (required ThreadStart/Resume response field) must be in the pinned
   first-party allowlist `{"openai"}` (R8 P0-3) — checked before any turn.
5. `codex --version` token must EXACTLY equal 0.139.0 (the vendored-schema version).
6. A pre-turn **SafetyAttestation** is written per phase; the Codex attestation refuses
   the turn unless the server echoes `approvalPolicy:"untrusted"`,
   `approvalsReviewer:"user"`, the isolated cwd, an allowlisted provider, AND the
   effective sandbox OBJECT is the strictest profile:
   `{"type": "readOnly", "networkAccess": false}` — the requested wire string
   `"read-only"` and the echoed object are DIFFERENT representations, validated
   separately (incident-001 defect 4); writable types and network access are rejected.

## Destructive setup steps (disclosed)

ONLY the phases `auto-read`, `approval-allow`, `approval-deny` clean `spike/v2/staging/`
before running; `verdict`/`resume` only ensure the directory EXISTS (the SDK requires its
cwd to exist — incident-001 defect 1). Cleanup byte-hash-snapshots prior content to
evidence first and ABORTS on deletion errors. Evidence directories are never cleaned.

## Live model calls — the phases the runner executes (in this exact order)

| # | Phase | Model / plan | Expected turns | Worst case | Cards for Live |
| --- | ------- | ------------ | -------------- | ---------- | -------------- |
| 1 | claude verdict | Claude haiku | 1 | 4 | 0 expected |
| 2 | claude resume | Claude haiku | 1 | 4 | 0 expected |
| 3 | claude auto-read | Claude haiku | 2 | 4 | **0 expected** — native Read auto-permitted, audit-logged |
| 4 | claude approval-allow | Claude haiku | 2 | 4 | 1 × native `Write {file_path: <abs staging>/approved.txt, content: "dialektike spike v2.6"}` |
| 5 | claude approval-deny | Claude haiku | 2 | 4 | 1 × native `Write {file_path: <abs staging>/denied.txt, content: "dialektike spike v2.6"}` |
| 6 | codex verdict | Codex (ChatGPT plan) | 1 | 1 | 0 expected (see card policy) |
| 7 | codex resume | Codex (ChatGPT plan) | 1 | 1 | 0 expected (see card policy) |

**The exact native action under approval test:** the built-in Claude Code `Write` tool,
with the ABSOLUTE contract-derived path embedded in the prompt (incident-001 defect 2:
the model was never told its workspace and targeted filesystem root). Disposable targets:
`spike/v2/staging/approved.txt` (allow run — must exist afterwards with exactly the
content `dialektike spike v2.6`) and `spike/v2/staging/denied.txt` (deny run — must NOT
exist afterwards, zero Write completions in the hooks). Nothing else is written.

**Card policy (incident-001 lesson — MATCH-based, never phase-name-based):** every card
carries `manifest_match: True|False` and `manifest_expected` annotations, computed
deterministically from the run contract.

> **Answer `a` (allow) ONLY when the card shows `manifest_match: True`** — which can only
> happen in the two approval phases for the exact Writes above; allow the approval-allow
> card, deny the approval-deny card (that IS its test). **For ANY card showing
> `manifest_match: False`, answer `d` (deny)** — the runner will stop the run at the
> failed phase. In incident-001 the card already displayed the root-path mismatch
> (`path_confined: False`); this policy makes that information decisive.

**The auto-read pass condition (GO clarification 2):** zero permission decisions AND
positive completion proof — exactly one PostToolUse-hook `tool_completed` record for the
exact `Read` of `staging/brief.txt`, a non-error stream tool result, and the model's reply
quoting the brief marker. Absence of a card alone is insufficient.

**Turn arithmetic, honest bounds:** Claude expected ≈ 8 turns, worst case 20
(5 phases × `max_turns=4`); Codex expected 2, worst case 2. Non-model RPCs per Codex phase:
`initialize`, `account/read`, `thread/start` or `thread/resume`, `turn/start`.

**Card policy (per 0002):**

- Claude phases: exactly the 2 cards listed — each is the native runtime's own
  `can_use_tool` ask relayed once. Any OTHER Claude card is off-script: answer **deny**
  (hash-chained; the phase then fails its exact-fingerprint proof and the run review).
- **Durable exactly-once (R9):** the relay atomically claims each request's correlation
  key in the chained log BEFORE the card appears; an exact wire retransmission is answered
  from the recorded decision with NO second card (audited as `replay_returned`); a
  correlation key reused with different content fails the phase. If you ever see two cards
  with the same correlation line, that is a defect — deny and stop the run.
- Codex phases: **0 cards expected** (read-only sandbox, empty cwd, plain audit prompt,
  verdict via the registered dynamic tool). If the native runtime raises an approval request
  (`item/commandExecution/requestApproval`, `item/fileChange/requestApproval`, legacy
  `execCommandApproval`/`applyPatchApproval`, `item/permissions/requestApproval`), it is
  FORWARDED verbatim through the shared relay — correct behaviour, not a defect. Recommended
  answer for anything unexpected in this spike: **deny**. Auto-permitted actions produce NO
  card and are audit-logged (`native_auto_permitted` records + raw evidence).
- Unknown server requests and non-approval interactive requests
  (`item/tool/requestUserInput`, `mcpServer/elicitation/request`,
  `account/chatgptAuthTokens/refresh`, `attestation/generate`, anything else) are declined
  fail-closed on the wire, audit-logged, and are **phase-fatal + verifier-fatal** (R8 f.7
  conceded): they cannot coexist with a PASS. If one appears: investigate, re-authenticate
  (`codex login`) if applicable, and rerun after review.

## Files created (inside the repo)

- `spike/v2/staging/`: `brief.txt` (platform-seeded), `approved.txt` (only if Live allows)
- `evidence/runs/<run-id>/` (ISOLATED per run — incident-001): `runner_manifest.json` +
  `spike-v2-claude/`, `spike-v2-codex/` holding exactly the tracked inventory in
  `run_contract.py` (per-phase billing/env/safety attestations, shadow warnings, run
  manifests, results, snapshots, item summaries, client health, effective configs) + the
  hash-chained `decisions.jsonl` (hashes and HASHED runtime ids only — no payloads)
- `evidence/**/raw/` (git-ignored at any depth): verbatim payloads, server requests, event
  streams, stderr, malformed-stdout captures, turn captures (assistant text +
  ResultMessage.result/structured_output/stop_reason/errors/usage, saved BEFORE any
  validation — incident-001 defect 3), failure tracebacks, `state.json` (raw ids)
- `spike/v2/codex-empty-cwd/` (empty isolated working directory)
- Failed runs preserve themselves in their own `evidence/runs/<run-id>/`; incident evidence
  lives in `evidence/incidents/` and is never cleaned.

## Out-of-repo side effects (disclosed)

- `~/.claude/`: session/history records per Claude phase (subscription runtime's storage).
- `~/.codex/`: session/rollout records; `codex app-server` may update project-trust
  configuration for the isolated cwd. No other home-directory writes expected.
- Both plans' usage meters advance (expected ≈ 10 short turns total; Claude on haiku).
- `synthetic_check.py` (precondition 1) uses a system temp directory, removed afterwards.

## Verification after the run (non-model)

Run automatically by the runner (only after all 7 phases pass), pointed at this run's
evidence directory. Manual re-verification of any run:

```bash
DIALEKTIKE_EVIDENCE_ROOT=evidence/runs/<run-id> ./venv/bin/python spike/v2/verify_run.py
```

Exits nonzero unless the FULL contract holds: both chains verify; strict tracked-evidence
inventory (decision logs REQUIRED, duplicate-suffixed artefacts fail, raw/ exempt from the
duplicate scan but referenced raw event streams must exist with matching hashes); the
relay LEDGER is clean — no correlation conflicts, unique decision keys, every correlation
id a SHA-256 hash (raw runtime ids structurally rejected), claims ↔ decisions a
fingerprint-matched bijection, every replay accounted against a recorded decision WITH the
identical answer, and on the Codex side every relayable wire request decided exactly once;
the Codex verdict is bound to the HASH-CHAINED item/tool/call record (raw payload hash +
arguments exact), not merely to editable evidence files; exactly two
exact-fingerprint Claude decisions with zero decisions in verdict/resume/auto-read;
auto-read completion positively proven; the two deterministic pre-clean snapshots exact;
approved/denied filesystem effects exact; positive billing evidence per phase on both
legs; provider allowlist; controlled-profile labels; SafetyAttestations clean; client
healthy with zero unknown/non-approval requests; Codex verdict via bound dynamicToolCall
with call and completed item JOINED on their schema-required arguments (call/item ids
recorded hashed as an observation — the schema does not promise their equality). Every
phase also prints an ANCHOR RECEIPT; Live pastes the receipts into the next audit round.
