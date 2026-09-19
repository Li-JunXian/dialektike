# Codex App Server 0.139.0 — protocol notes (SUPERSEDED by the generated schema)

**Canonical source: `vendor/codex-app-server-0.139.0/`** — generated 2026-07-14 by
`codex app-server generate-json-schema --out vendor/codex-app-server-0.139.0 --experimental`
(codex-cli 0.139.0; per-file SHA-256 hashes in `GENERATION.md`). Schema over testimony —
the doctrine adopted after R6.

Prose corrected by the schema (kept as a record of why prose is not evidence):

| Claim source | Said | Schema says |
| ------------ | ---- | ----------- |
| README (fetched) | `sandbox: "readOnly"` | `SandboxMode = "read-only"` |
| README (fetched) | method `thread/new` mentioned in overview prose | `thread/start` |
| Codex audit R6 | approval policy `"unlessTrusted"` | `AskForApproval = "untrusted" \| "on-failure" \| "on-request" \| "never"` |
| README (fetched) | items on `turn/completed` | canonical items via `item/completed` (R6, consistent with schema notifications) |
| Codex audit R5/R6 | item `collabToolCall` | `collabAgentToolCall` (+ `imageGeneration` also ambient) |
| Codex audit R6 / v2.2 code | legacy `execCommandApproval`/`applyPatchApproval` answered `"decline"` | legacy `ReviewDecision = "approved" \| "approved_for_session" \| "denied" \| "timed_out" \| "abort"` — `"decline"` belongs ONLY to the item/*/requestApproval enums (R7 caught this) |
| v2.2 code | server requests limited to the six handled methods | `ServerRequest` also defines `account/chatgptAuthTokens/refresh` and `attestation/generate` (fail-closed error + audit log if seen) |

Key schema-pinned contracts used by `spike/v2/codex_leg.py`:

- `initialize` params: `clientInfo{name,title,version}`, `capabilities{experimentalApi:bool, …}`
- `thread/start` → `result.thread.id`; params incl. `sandbox`, `approvalPolicy`,
  `approvalsReviewer ("user"|"auto_review"|"guardian_subagent")`, `dynamicTools[DynamicToolSpec]`, `config`
- `turn/start` → `result.turn.id`; `turn/completed` params.turn.status ∈
  `completed|interrupted|failed|inProgress`
- Server request `item/tool/call` params: `callId, threadId, turnId, tool, arguments` →
  response `{contentItems: [{type:"inputText"|"inputImage", …}], success: bool}`
- Approval responses: commandExecution/fileChange `{"decision": "accept"|…|"decline"}`;
  permissions `{"permissions": GrantedPermissionProfile}`; elicitation `{"action": …}`
- `account/read {refreshToken:bool}` → `result.account` oneOf
  `{type:"apiKey"}` | `{type:"chatgpt", email, planType}` — billing gate requires `"chatgpt"`
- `ThreadItem.type` full set: userMessage, agentMessage, reasoning, plan, hookPrompt,
  contextCompaction, dynamicToolCall, commandExecution, fileChange, webSearch, mcpToolCall,
  collabAgentToolCall, imageView, imageGeneration, enteredReviewMode, exitedReviewMode

v2.3 additions (all read off the generated schema):

- `ItemCompletedNotification` REQUIRES `threadId`, `turnId`, `item` — items are bindable.
- `DynamicToolCallParams` REQUIRES `callId`, `threadId`, `turnId`, `tool`, `arguments`.
- dynamicToolCall ThreadItem REQUIRES `id`, `status` (`inProgress|completed|failed`),
  `tool`, `arguments`; `success` is nullable bool.
- `ThreadStartResponse`/`ThreadResumeResponse` REQUIRE effective `model`, `modelProvider`,
  `sandbox`, `approvalPolicy`, `approvalsReviewer`, `cwd`, `thread` — the SafetyAttestation
  evidence base.
- `ThreadStartParams.config` is schema-opaque (`additionalProperties: true`): the v2.2
  feature-disable keys were unverifiable and are DROPPED per governance 0002.
- Approval relay decisions (0002): new-style command/fileChange `accept`/`decline`
  (+ `acceptForSession`, `cancel`, amendment objects exist but are not offered);
  legacy `approved`/`denied`; permissions response `{permissions: GrantedPermissionProfile,
  scope: "turn"|"session"}`; `CommandExecutionRequestApprovalParams` carries `command`,
  `cwd`, `reason`, `availableDecisions` for the card.
- Wire method names verified from `ClientRequest.json`: `thread/start`, `thread/resume`,
  `turn/start`, `account/read` (v2.2's names were correct).
