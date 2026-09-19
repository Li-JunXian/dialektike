"""Dialektikḗ spike v2.4 — Codex leg via App Server. IMPLEMENTED, NOT RUN.

Written against the VENDORED, BINARY-GENERATED schema
(vendor/codex-app-server-0.139.0/, hashes in GENERATION.md) — not prose.

PERMISSION SEMANTICS (governance 0002): native approval requests are relayed
to Live through the shared provider-neutral PermissionRelay (core/relay.py,
governance 0003) — once, verbatim, deterministically enriched — and Live's
answer is mapped back onto the wire by THIS adapter (the only wire-specific
part). Natively auto-permitted actions are audit-logged only.

R8 corrections on top of v2.3:
  - Billing binding (P0-3): the effective `modelProvider` must be in the
    pinned first-party allowlist (run_contract.ALLOWED_MODEL_PROVIDERS);
    a nonempty arbitrary provider no longer passes the SafetyAttestation.
  - Finalization order: the client is CLOSED (readers joined, events sealed)
    BEFORE health is asserted and PASS is printed — close() can no longer add
    fatal events after the verdict was announced.
  - Malformed stdout lines are preserved to raw/ and are FATAL (v2.3 silently
    discarded them).
  - audit_items binds to the active thread AND turn ids.
  - Tracked records carry HASHED runtime ids only (annotations contract in
    core/relay.py); raw payloads live in git-ignored raw/.
  - Exactly-once is correlation-keyed: every server request record and every
    relayed decision carry the same deterministic correlation_id, so the
    verifier can prove a bijection, not a bare count match.
  - Unknown server requests and non-approval interactive requests are still
    declined fail-closed on the wire, but are now PHASE-FATAL and fail the
    verifier (R8 finding 7 conceded: they cannot coexist with a clean PASS).

Phases (run_contract.CODEX_PHASES — separate processes): verdict · resume
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "spike" / "v2"))

import run_contract as rc  # noqa: E402
from core.broker import ChainedLog, canonical, sha256_text  # noqa: E402
from core.evidence import EvidenceDir  # noqa: E402
from core.relay import NormalizedRequest, PermissionRelay, terminal_presenter  # noqa: E402

# incident-001: run-scoped evidence isolation, runner-enforced
EVIDENCE = EvidenceDir(rc.required_run_dir(), rc.CODEX_EVIDENCE)
LOG = ChainedLog(EVIDENCE.dir / "decisions.jsonl")

AMBIENT_ITEM_TYPES = {"commandExecution", "fileChange", "webSearch", "mcpToolCall",
                      "collabAgentToolCall", "imageView", "imageGeneration"}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "claim_id": {"type": "string"},
        "verdict": {"type": "string", "enum": sorted(rc.VERDICT_ENUM)},
        "argument": {"type": "string"},
    },
    "required": ["claim_id", "verdict", "argument"],
    "additionalProperties": False,
}
AUDIT_PROMPT = (
    "You are the Auditor in a dialectic protocol. Audit this claim:\n"
    '  C1: "A shared filesystem directory is an acceptable blindness boundary between two models."\n'
    "Submit your verdict by calling the submit_verdict tool with keys claim_id (\"C1\"), "
    "verdict (AGREE | CHALLENGE | INSUFFICIENT EVIDENCE), and argument (one sentence)."
)

# Native approval relay mappings (schema-pinned; governance 0002 table).
# The relay decides allow/deny; this table is the adapter's wire mapping.
RELAY_DECISIONS = {
    "item/commandExecution/requestApproval": ("accept", "decline"),
    "item/fileChange/requestApproval": ("accept", "decline"),
    "execCommandApproval": ("approved", "denied"),   # legacy ReviewDecision enum
    "applyPatchApproval": ("approved", "denied"),    # legacy ReviewDecision enum
}


def preconditions():
    if os.environ.get("OPENAI_API_KEY"):
        sys.exit("ABORT: OPENAI_API_KEY present — cannot certify subscription billing (fail closed)")
    ver = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=15)
    token = ver.stdout.strip().split()[-1] if ver.stdout.strip() else ""
    if token != rc.REQUIRED_CODEX_VERSION:  # R9 f.5: EXACT equality, not substring
        sys.exit(f"ABORT: codex version {token!r} != {rc.REQUIRED_CODEX_VERSION!r} "
                 "(vendored schema would not match)")


def hashed_id_annotations(params: dict) -> dict:
    """R8 finding 6: runtime ids appear in tracked records only as hashes."""
    out = {}
    for key, label in (("threadId", "thread_id_sha256"), ("turnId", "turn_id_sha256"),
                       ("itemId", "item_id_sha256"), ("callId", "call_id_sha256")):
        val = params.get(key)
        if val:
            out[label] = sha256_text(str(val))
    return out


def correlation_id(server_request_id, params: dict) -> str:
    return sha256_text(canonical({"server_request_id": server_request_id,
                                  "params_sha256": sha256_text(canonical(params))}))


class AppServerClient:
    """JSON-RPC 2.0 over `codex app-server` stdio ("jsonrpc" header omitted)."""

    def __init__(self, phase: str):
        self.phase = phase
        # R9 f.6: cards identify the EFFECTIVE model once the server reports it
        self.model_label = rc.CODEX_MODEL_LABEL
        self.proc = subprocess.Popen(
            ["codex", "app-server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._id = 0
        self._send_lock = threading.Lock()
        self._closed = False
        self.events: list[dict] = []
        self.item_events: list[dict] = []      # full ItemCompletedNotification params
        self.tool_calls: list[dict] = []       # full DynamicToolCallParams
        self.unknown_requests: list[str] = []  # methods answered with JSON-RPC error
        self.declined_non_approvals: list[str] = []
        self.fatal: list[str] = []             # handler/protocol faults — phase-fatal
        self.relay_active = threading.Event()  # a card is in front of Live
        self.relay = PermissionRelay(log=LOG, presenter=self._present,
                                     raw_dir=EVIDENCE.raw)
        self.turn_result: dict | None = None
        self.turn_thread_id: str | None = None
        self.turn_done = threading.Event()
        self._reader = threading.Thread(target=self._read_loop)
        self._stderr = threading.Thread(target=self._drain_stderr)
        self._reader.start()
        self._stderr.start()

    def _present(self, req, card):
        """Shared terminal presenter, wrapped so an open card cannot expire
        the turn timeout."""
        self.relay_active.set()
        try:
            return terminal_presenter(req, card)
        finally:
            self.relay_active.clear()

    def _normalized(self, method: str, params: dict, corr: str) -> NormalizedRequest:
        return NormalizedRequest(
            provider="codex", case=rc.CASE, phase=self.phase,
            model=self.model_label, role="auditor", kind=method,
            payload=dict(params), correlation_id=corr,
            annotations=hashed_id_annotations(params),
        )

    def _drain_stderr(self):
        chunks = [line for line in self.proc.stderr]
        if chunks:
            EVIDENCE.save_raw(f"{self.phase}_app-server-stderr.log", "".join(chunks))

    def _read_loop(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # R8: malformed stdout is preserved AND fatal, not discarded
                EVIDENCE.save_raw(f"{self.phase}_malformed_stdout.txt", line)
                self.fatal.append(f"malformed stdout line ({len(line)} chars, preserved to raw/)")
                continue
            self.events.append(msg)
            try:
                self._handle(msg)
            except Exception as exc:  # a handler bug means client state is untrustworthy
                self.fatal.append(f"handler exception on {msg.get('method')!r}: {exc}")
                LOG.append({"kind": "client_handler_error", "method": msg.get("method"),
                            "error": str(exc)})

    def _send(self, obj: dict):
        with self._send_lock:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()

    def request(self, method: str, params: dict) -> int:
        self._id += 1
        self._send({"id": self._id, "method": method, "params": params})
        return self._id

    def notify(self, method: str, params: dict | None = None):
        msg: dict = {"method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def response_for(self, req_id: int, timeout: float = 60) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline or self.relay_active.is_set():
            for ev in self.events:
                if ev.get("id") == req_id and ("result" in ev or "error" in ev):
                    return ev
            time.sleep(0.1)
        raise AssertionError(f"no response for request {req_id} within {timeout}s")

    # -- server→client handling, by EXACT schema method --

    def _handle(self, msg: dict):
        method = msg.get("method", "")
        params = msg.get("params", {}) or {}
        if "id" in msg and method:  # server-initiated request
            corr = correlation_id(msg["id"], params)
            self.relay.audit(self._normalized(method, params, corr), kind="server_request")
            if method == "item/tool/call":
                self._handle_tool_call(msg["id"], params)
            elif method in RELAY_DECISIONS:
                self._relay_native_approval(msg["id"], method, params, corr)
            elif method == "item/permissions/requestApproval":
                self._relay_permissions(msg["id"], params, corr)
            elif method == "mcpServer/elicitation/request":
                # non-approval interactive flow — fail-closed decline (alpha will forward)
                self._send({"id": msg["id"], "result": {"action": "decline", "content": None}})
                self.declined_non_approvals.append(method)
                self.relay.audit(self._normalized(method, params, corr),
                                 kind="non_approval_declined")
            elif method == "item/tool/requestUserInput":
                self._send({"id": msg["id"],
                            "error": {"code": -32601,
                                      "message": "Dialektikḗ fail-closed responder"}})
                self.declined_non_approvals.append(method)
                self.relay.audit(self._normalized(method, params, corr),
                                 kind="non_approval_declined")
            else:  # incl. account/chatgptAuthTokens/refresh, attestation/generate
                self.unknown_requests.append(method)
                self._send({"id": msg["id"],
                            "error": {"code": -32601,
                                      "message": "Dialektikḗ fail-closed responder"}})
                self.relay.audit(self._normalized(method, params, corr),
                                 kind="unknown_request_declined")
            return
        if method == "item/completed":  # canonical item source; params: threadId, turnId, item
            self.item_events.append(params)
        elif method == "turn/completed":
            self.turn_result = params.get("turn", {}) or {}
            self.turn_thread_id = params.get("threadId")
            self.turn_done.set()

    def _handle_tool_call(self, req_id, params: dict):
        self.tool_calls.append(params)
        ok = params.get("tool") == "submit_verdict"
        text = "verdict received by Dialektikḗ" if ok else "unknown tool — fail closed"
        self._send({"id": req_id, "result": {
            "contentItems": [{"type": "inputText", "text": text}], "success": ok}})

    def _relay_native_approval(self, req_id, method: str, params: dict, corr: str):
        """One native request → one card via the shared relay → one wire answer."""
        allow_wire, deny_wire = RELAY_DECISIONS[method]
        decision, _reason = self.relay.relay(self._normalized(method, params, corr))
        wire = allow_wire if decision == "allow" else deny_wire
        self._send({"id": req_id, "result": {"decision": wire}})

    def _relay_permissions(self, req_id, params: dict, corr: str):
        decision, _reason = self.relay.relay(
            self._normalized("item/permissions/requestApproval", params, corr))
        granted = (params.get("permissions") or {}) if decision == "allow" else {}
        self._send({"id": req_id, "result": {"permissions": granted, "scope": "turn"}})

    def close(self, label: str):
        if self._closed:
            return
        self._closed = True
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            pass
        self._reader.join(timeout=10)
        self._stderr.join(timeout=10)
        if self._reader.is_alive() or self._stderr.is_alive():
            self.fatal.append("reader threads did not join — evidence may be incomplete")
        raw_hash = EVIDENCE.save_raw(f"{label}_events.json", self.events)
        EVIDENCE.save_json(f"{label}_events_ref.json",
                           {"events_sha256": raw_hash, "count": len(self.events)})


# -- protocol steps --

def handshake(client: AppServerClient):
    rid = client.request("initialize", {
        "clientInfo": {"name": "dialektike", "title": "Dialektikḗ", "version": "0.0.5"},
        "capabilities": {"experimentalApi": True},   # required for dynamicTools
    })
    resp = client.response_for(rid)
    if "error" in resp:
        raise AssertionError(f"initialize failed: {resp['error']}")
    client.notify("initialized")


def assert_chatgpt_account(client: AppServerClient, phase: str) -> dict:
    """Billing fail-closed: abort unless account.type == 'chatgpt'.
    Evidence is phase-qualified (R8 P0-2)."""
    rid = client.request("account/read", {"refreshToken": False})
    resp = client.response_for(rid)
    if "error" in resp:
        raise AssertionError(f"account/read failed — cannot certify billing (fail closed): {resp['error']}")
    account = (resp.get("result") or {}).get("account") or {}
    if account.get("type") != "chatgpt":
        raise AssertionError(f"account type {account.get('type')!r} != 'chatgpt' — fail closed")
    EVIDENCE.save_json(f"{phase}_billing_evidence.json", {
        "claim": rc.BILLING_CLAIM,
        "account_type": "chatgpt", "plan_type": account.get("planType"),
    })
    return account


def safety_attestation(phase: str, effective: dict, account: dict):
    """Pre-turn SafetyAttestation. R8 P0-3: the effective modelProvider must be
    in the pinned first-party allowlist — nonempty is not evidence.
    Incident-001 / R12 amendment 6: the REQUESTED sandbox is the wire string,
    but the server ECHOES a schema-shaped SandboxPolicy object — the two
    representations are validated separately; writable types and network
    access are explicitly rejected."""
    problems = []
    for key, want in rc.EFFECTIVE_ECHO_STRINGS.items():
        got = effective.get(key)
        if got != want:
            problems.append(f"{key}: requested {want!r}, effective {got!r}")
    if not rc.sandbox_effective_ok(effective.get("sandbox")):
        problems.append(f"sandbox: effective {effective.get('sandbox')!r} is not the "
                        "strictest profile (require type='readOnly', networkAccess false)")
    if str(effective.get("cwd", "")) != str(rc.CODEX_CWD):
        problems.append(f"cwd: expected {rc.CODEX_CWD}, effective {effective.get('cwd')!r}")
    if not effective.get("model"):
        problems.append("model: missing from response (required field)")
    provider = effective.get("modelProvider")
    if provider not in rc.ALLOWED_MODEL_PROVIDERS:
        problems.append(f"modelProvider: {provider!r} not in pinned first-party "
                        f"allowlist {sorted(rc.ALLOWED_MODEL_PROVIDERS)} — "
                        "subscription billing route not proven")
    if account.get("type") != "chatgpt":
        problems.append("billing route not proven as chatgpt subscription")
    att = {
        "phase": phase,
        "billing_route": f"chatgpt subscription (planType={account.get('planType')})",
        "model": effective.get("model"), "model_provider": provider,
        "model_provider_allowlist": sorted(rc.ALLOWED_MODEL_PROVIDERS),
        "sandbox": effective.get("sandbox"), "approval_policy": effective.get("approvalPolicy"),
        "approvals_reviewer": effective.get("approvalsReviewer"),
        "cwd": effective.get("cwd"),
        "profile_label": rc.PROFILE_LABEL,
        "profile_note": rc.PROFILE_NOTE,
        "permission_relay": "native approvals → core/relay.py PermissionRelay "
                            "(exactly-once); wire mapping in this adapter only",
        "auto_permitted_actions": "audit-logged only (governance 0002)",
        "problems": problems,
    }
    EVIDENCE.save_json(f"{phase}_safety_attestation.json", att)
    if problems:
        raise AssertionError(f"SafetyAttestation refuses turn: {problems}")


def start_thread(client: AppServerClient) -> tuple[str, dict]:
    rc.CODEX_CWD.mkdir(parents=True, exist_ok=True)
    rid = client.request("thread/start", {
        "cwd": str(rc.CODEX_CWD),
        **rc.REQUESTED_CODEX_CONFIG,
        "dynamicTools": [{
            "name": "submit_verdict",
            "description": "Submit your structured audit verdict for the claim under review.",
            "inputSchema": VERDICT_SCHEMA,
        }],
    })
    resp = client.response_for(rid)
    if "error" in resp:
        raise AssertionError(f"thread/start failed: {resp['error']}")
    result = resp.get("result") or {}
    thread_id = (result.get("thread") or {}).get("id")
    if not thread_id:
        raise AssertionError(f"no result.thread.id in: {resp}")
    if result.get("model"):
        client.model_label = f"codex ({result['model']})"  # R9 f.6: cards name the model
    raw_hash = EVIDENCE.save_raw("thread_start_response.json", result)
    EVIDENCE.save_json("thread_start_effective.json", {
        k: result.get(k) for k in ("model", "modelProvider", "sandbox", "approvalPolicy",
                                   "approvalsReviewer", "cwd", "serviceTier",
                                   "activePermissionProfile")
    } | {"raw_sha256": raw_hash, "thread": EVIDENCE.hashed_id(thread_id)})
    return thread_id, result


def resume_thread(client: AppServerClient, thread_id: str) -> dict:
    rid = client.request("thread/resume", {"threadId": thread_id})
    resp = client.response_for(rid)
    if "error" in resp:
        raise AssertionError(f"thread/resume failed: {resp['error']}")
    result = resp.get("result") or {}
    resumed_id = (result.get("thread") or {}).get("id")
    if resumed_id != thread_id:  # R7: verify the resumed response's thread id
        raise AssertionError(f"resumed thread {resumed_id!r} != requested {thread_id!r}")
    if result.get("model"):
        client.model_label = f"codex ({result['model']})"  # R9 f.6
    raw_hash = EVIDENCE.save_raw("thread_resume_response.json", result)
    EVIDENCE.save_json("thread_resume_effective.json", {
        k: result.get(k) for k in ("model", "modelProvider", "sandbox", "approvalPolicy",
                                   "approvalsReviewer", "cwd")
    } | {"raw_sha256": raw_hash, "thread": EVIDENCE.hashed_id(thread_id)})
    return result


def run_turn(client: AppServerClient, thread_id: str, prompt: str, timeout: float = 240) -> str:
    client.turn_done.clear()
    rid = client.request("turn/start", {
        "threadId": thread_id,
        "input": [{"type": "text", "text": prompt}],
    })
    resp = client.response_for(rid)
    if "error" in resp:
        raise AssertionError(f"turn/start failed: {resp['error']}")
    turn_id = ((resp.get("result") or {}).get("turn") or {}).get("id")
    if not turn_id:
        raise AssertionError(f"no result.turn.id in: {resp}")
    deadline = time.time() + timeout
    while not client.turn_done.wait(timeout=1):
        # a card in front of Live must not expire the turn (relay may be slow)
        if time.time() > deadline and not client.relay_active.is_set():
            raise AssertionError("turn did not complete within timeout")
    status = (client.turn_result or {}).get("status")
    completed_id = (client.turn_result or {}).get("id")
    if client.turn_thread_id != thread_id:  # bind the notification's thread
        raise AssertionError(f"turn/completed thread {client.turn_thread_id!r} != {thread_id!r}")
    if completed_id != turn_id:
        raise AssertionError(f"completed turn {completed_id!r} != started turn {turn_id!r}")
    if status != "completed":
        raise AssertionError(f"turn status {status!r} != 'completed' — fail closed")
    return turn_id


def bound_items(client: AppServerClient, thread_id: str, turn_id: str) -> list[dict]:
    return [ev["item"] for ev in client.item_events
            if ev.get("threadId") == thread_id and ev.get("turnId") == turn_id
            and isinstance(ev.get("item"), dict)]


def audit_items(client: AppServerClient, phase: str, thread_id: str, turn_id: str):
    """Audit log, NOT a gate (governance 0002). R8 finding 6: only items bound
    to the ACTIVE thread and turn are attributed; anything else is a fault."""
    bound, foreign = [], []
    for ev in client.item_events:
        (bound if ev.get("threadId") == thread_id and ev.get("turnId") == turn_id
         else foreign).append(ev)
    if foreign:
        client.fatal.append(f"{len(foreign)} item event(s) from a foreign thread/turn")
    summary: dict[str, int] = {}
    ambient = []
    for ev in bound:
        item = ev.get("item") or {}
        itype = str(item.get("type", "UNKNOWN"))
        summary[itype] = summary.get(itype, 0) + 1
        if itype in AMBIENT_ITEM_TYPES or itype == "UNKNOWN":
            ambient.append(ev)
    EVIDENCE.save_json(f"{phase}_item_summary.json", {"summary": summary})
    if ambient:
        client.relay.audit(NormalizedRequest(
            provider="codex", case=rc.CASE, phase=phase, model=rc.CODEX_MODEL_LABEL,
            role="auditor", kind="ambient_items", payload={"items": ambient},
            correlation_id=sha256_text(canonical(ambient)),
            annotations={"thread_id_sha256": sha256_text(thread_id),
                         "turn_id_sha256": sha256_text(turn_id),
                         "types": sorted({str((e.get('item') or {}).get('type')) for e in ambient}),
                         "count": len(ambient)},
        ), kind="native_auto_permitted")
        print(f"AUDIT: {len(ambient)} native auto-permitted item(s) logged "
              f"({sorted(summary)}) — no extra prompts created (per governance 0002)")


def _parse_args(raw) -> dict:
    args = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(args, dict):
        raise AssertionError(f"tool arguments not an object: {raw!r}")
    return args


def extract_verdict(client: AppServerClient, thread_id: str, turn_id: str) -> dict:
    """R7 P0-3: dynamic-tool path ONLY, bound to the active thread and turn.
    R9 f.3: the request and the completed item are JOINED on the fields the
    schema REQUIRES on both sides — `tool` and `arguments`
    (DynamicToolCallParams and DynamicToolCallThreadItem both require them).
    `callId == item.id` is NOT stated by the schema, so it is recorded as an
    observation (hashed ids + ids_equal) for the audit round, not asserted —
    schema-over-testimony."""
    calls = [c for c in client.tool_calls
             if c.get("threadId") == thread_id and c.get("turnId") == turn_id]
    if len(calls) != 1 or calls[0].get("tool") != "submit_verdict":
        raise AssertionError(f"expected exactly one bound submit_verdict item/tool/call, "
                             f"got {[(c.get('tool'), c.get('turnId')) for c in client.tool_calls]}")
    items = [i for i in bound_items(client, thread_id, turn_id)
             if i.get("type") == "dynamicToolCall"]
    if len(items) != 1 or items[0].get("tool") != "submit_verdict" \
            or items[0].get("status") != "completed" or items[0].get("success") is not True:
        raise AssertionError(f"expected one completed successful dynamicToolCall item, got {items}")
    args = _parse_args(calls[0].get("arguments"))
    item_args = _parse_args(items[0].get("arguments"))
    if canonical(args) != canonical(item_args):
        raise AssertionError("item/tool/call arguments != dynamicToolCall item arguments — "
                             "the completed item does not evidence the same call (R9 f.3)")
    call_id, item_id = str(calls[0].get("callId")), str(items[0].get("id"))
    EVIDENCE.save_json("verdict_path.json", {
        "path": "dynamicToolCall",
        "call_id_sha256": sha256_text(call_id),
        "item_id_sha256": sha256_text(item_id),
        "ids_equal": call_id == item_id,  # observation for R10 — schema does not promise it
        "call_args_sha256": sha256_text(canonical(args)),
        "item_args_sha256": sha256_text(canonical(item_args)),
        "args_sha256": sha256_text(canonical(args)),
    })
    return args


def validate_verdict(verdict: dict) -> dict:
    if not isinstance(verdict, dict) or set(verdict) != {"claim_id", "verdict", "argument"}:
        raise AssertionError(f"schema violation — {verdict}")
    if verdict["claim_id"] != rc.CLAIM_ID or verdict["verdict"] not in rc.VERDICT_ENUM \
            or not isinstance(verdict["argument"], str) or not verdict["argument"].strip():
        raise AssertionError(f"schema violation — {verdict}")
    return verdict


def assert_client_healthy(client: AppServerClient, phase: str):
    """Runs strictly AFTER close() (R8): includes shutdown faults. Unknown and
    non-approval requests are spike-fatal (R8 finding 7 conceded)."""
    EVIDENCE.save_json(f"{phase}_client_health.json",
                       {"fatal": client.fatal,
                        "unknown_requests": client.unknown_requests,
                        "declined_non_approvals": client.declined_non_approvals})
    if client.fatal:
        raise AssertionError(f"client fatal events: {client.fatal}")
    if client.unknown_requests or client.declined_non_approvals:
        raise AssertionError(
            f"unexpected server requests (declined fail-closed on the wire, but the "
            f"spike expects none): unknown={client.unknown_requests} "
            f"non-approval={client.declined_non_approvals}")


# -- phases --

def phase_verdict():
    client = AppServerClient("verdict")
    closed = False
    try:
        handshake(client)
        account = assert_chatgpt_account(client, "verdict")
        thread_id, effective = start_thread(client)
        safety_attestation("verdict", effective, account)
        turn_id = run_turn(client, thread_id, AUDIT_PROMPT)
        audit_items(client, "verdict", thread_id, turn_id)
        verdict = validate_verdict(extract_verdict(client, thread_id, turn_id))
        client.close("verdict")
        closed = True
        assert_client_healthy(client, "verdict")   # AFTER close (R8)
        EVIDENCE.save_json("verdict_result.json",
                           {**verdict, "thread": EVIDENCE.hashed_id(thread_id)})
        EVIDENCE.record_state("codex_thread_id", thread_id)
        print(f"PHASE verdict PASS — {verdict['verdict']} on C1 via dynamicToolCall; "
              "thread id persisted")
    finally:
        if not closed:
            client.close("verdict")
        print(LOG.anchor_receipt())


def phase_resume():
    thread_id = EVIDENCE.read_state("codex_thread_id")
    client = AppServerClient("resume")
    closed = False
    try:
        handshake(client)
        account = assert_chatgpt_account(client, "resume")
        effective = resume_thread(client, thread_id)
        safety_attestation("resume", effective, account)
        turn_id = run_turn(client, thread_id,
                           "Which claim_id did you audit in this thread? Reply with the ID only.")
        audit_items(client, "resume", thread_id, turn_id)
        if client.tool_calls:  # no dynamic tool is registered for resume — off-script
            raise AssertionError(f"unexpected item/tool/call in resume: "
                                 f"{[c.get('tool') for c in client.tool_calls]}")
        text = "".join(i.get("text", "") for i in bound_items(client, thread_id, turn_id)
                       if i.get("type") == "agentMessage").strip()
        client.close("resume")
        closed = True
        assert_client_healthy(client, "resume")    # AFTER close (R8)
        EVIDENCE.save_text("resume_reply.txt", text)
        if text != rc.CLAIM_ID:  # strict equality, aligned with the Claude leg
            raise AssertionError(f"resume failed — reply: {text!r}")
        print("PHASE resume PASS — exact thread recalled C1 across processes")
    finally:
        if not closed:
            client.close("resume")
        print(LOG.anchor_receipt())


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    if phase not in rc.CODEX_PHASES:
        sys.exit(f"usage: codex_leg.py {{{'|'.join(rc.CODEX_PHASES)}}} — unknown phase fails closed")
    preconditions()
    EVIDENCE.write_manifest(phase, {"leg": "codex", "case": rc.CASE})
    dispatch = {"verdict": phase_verdict, "resume": phase_resume}
    try:
        dispatch[phase]()
    except BaseException as exc:  # noqa: BLE001 — incident-001: failures must be CONTROLLED
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        import traceback
        EVIDENCE.save_raw(f"{phase}_failure_traceback.txt", traceback.format_exc())
        print(f"PHASE {phase} FAIL (controlled): {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
