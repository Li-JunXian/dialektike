"""Dialektikḗ spike v2.6 — Claude leg. IMPLEMENTED, NOT RUN (Live's ruling).

Incident-001 corrections (audit R12, Live's amended GO):
  - Phases REFUSE to start without DIALEKTIKE_RUN_DIR — sequencing and
    evidence isolation are enforced by spike/v2/run_manifest.py, not by an
    operator pasting commands (13 phase starts in incident-001).
  - The staging cwd EXISTS for every phase (v2.4 regression: the SDK requires
    cwd to exist; only cleaning phases created it).
  - Prompts carry the exact contract-derived ABSOLUTE paths — the model was
    never told its workspace and resolved names to filesystem root.
  - The verdict is requested via ClaudeAgentOptions.output_format
    (json_schema, types.py:2042) and ResultMessage.structured_output is
    AUTHORITATIVE; assistant text, ResultMessage.result, subtype, stop
    reason, errors and usage are captured to raw/ BEFORE any validation.
    No fence-stripping, no JSON repair (standing R6 rule).
  - Every card carries manifest-match annotations (expected fingerprint,
    expected target, exact-match flag) — deterministic enrichment; the
    manifest v9 card policy is allow-only-on-MATCH.
  - Failures are CONTROLLED: any exception becomes "PHASE <p> FAIL" with the
    traceback preserved to raw/ (incident-001 had uncaught crashes; the
    outcome was safe but not controlled — the distinction is recorded).

Carried: environment ALLOWLIST scrubbed in THIS process (SDK merges
os.environ into its child — subprocess_cli.py:491), positive-evidence
subscription gate, fingerprint-exact decision proofs from a chain-verified
log via the shared PermissionRelay, resume same-session-id assertion
(fork_session=False — types.py:1943), SafetyAttestation, shadow-warning
hard failure, PostToolUse hook completion proofs.

Phases (run_contract.CLAUDE_PHASES — launched ONLY via run_manifest.py):
  verdict · resume · auto-read · approval-allow · approval-deny
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import traceback
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "spike" / "v2"))

import run_contract as rc  # noqa: E402
from core.broker import ChainedLog, canonical, sha256_text  # noqa: E402
from core.evidence import EvidenceDir  # noqa: E402
from core.relay import (  # noqa: E402
    NormalizedRequest,
    PermissionRelay,
    path_annotations,
)

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

# read BEFORE the environment scrub; not in the allowlist, so the SDK child
# never sees it (incident-001: run-scoped evidence isolation)
RUN_DIR = rc.required_run_dir()
EVIDENCE = EvidenceDir(RUN_DIR, rc.CLAUDE_EVIDENCE)
LOG = ChainedLog(EVIDENCE.dir / "decisions.jsonl")
RELAY = PermissionRelay(log=LOG, raw_dir=EVIDENCE.raw)

FORBIDDEN_AUTH_MARKERS = ("apikey", "api_key", "api key", "console", "bedrock", "vertex", "foundry")

AUDIT_PROMPT = (
    "You are the Auditor in a dialectic protocol. Audit this claim:\n"
    '  C1: "A shared filesystem directory is an acceptable blindness boundary between two models."\n'
    "Return your verdict as structured output with exactly these keys: "
    'claim_id ("C1"), verdict ("AGREE" | "CHALLENGE" | "INSUFFICIENT EVIDENCE"), '
    "argument (one sentence)."
)

VERDICT_OUTPUT_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "claim_id": {"type": "string"},
            "verdict": {"type": "string", "enum": sorted(rc.VERDICT_ENUM)},
            "argument": {"type": "string"},
        },
        "required": ["claim_id", "verdict", "argument"],
        "additionalProperties": False,
    },
}

# ---- billing preconditions (fail closed) ----

ENV_ALLOWLIST = ("HOME", "PATH", "USER", "LOGNAME", "SHELL", "TMPDIR",
                 "LANG", "LC_ALL", "LC_CTYPE", "TERM")
SELECTOR_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_")
SELECTOR_EXACT = ("OPENAI_API_KEY",)


def enforce_minimal_environment(phase: str):
    """Reduce THIS process's environment to the allowlist. The SDK merges the
    full inherited os.environ into its child (subprocess_cli.py:491), so the
    worker environment IS the child environment — one env, one truth. Any
    billing/provider selector aborts rather than being silently dropped."""
    original = dict(os.environ)
    selectors = sorted(k for k in original
                       if k.startswith(SELECTOR_PREFIXES) or k in SELECTOR_EXACT)
    if selectors:
        sys.exit(f"ABORT: billing/provider selectors present {selectors} — "
                 "cannot certify subscription billing (fail closed)")
    kept = {k: v for k, v in original.items() if k in ENV_ALLOWLIST}
    dropped = sorted(set(original) - set(kept))
    os.environ.clear()
    os.environ.update(kept)
    EVIDENCE.save_raw(f"{phase}_env_dropped_names.json", dropped)  # names only, raw/
    EVIDENCE.save_json(f"{phase}_env_attestation.json", {
        "policy": "allowlist", "kept": sorted(kept),
        "dropped_count": len(dropped),
        "dropped_names_sha256": sha256_text(json.dumps(dropped)),
    })


def assert_subscription_auth(phase: str):
    """Runs in the already-minimal environment — the same one the SDK child
    will inherit. Requires POSITIVE evidence; unparseable output fails closed."""
    proc = subprocess.run(["claude", "auth", "status"], capture_output=True,
                          text=True, timeout=30)
    out = (proc.stdout + proc.stderr).strip()
    EVIDENCE.save_raw(f"{phase}_claude_auth_status.txt", out)
    if proc.returncode != 0:
        sys.exit(f"ABORT: `claude auth status` exited {proc.returncode} — unauthenticated (fail closed)")
    try:
        status = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit("ABORT: `claude auth status` output not parseable JSON — cannot "
                 "positively certify subscription billing (fail closed)")
    if not (status.get("loggedIn") is True and status.get("authMethod") == "claude.ai"
            and status.get("apiProvider") == "firstParty"):
        sys.exit(f"ABORT: auth is not first-party claude.ai subscription — "
                 f"authMethod={status.get('authMethod')!r} "
                 f"apiProvider={status.get('apiProvider')!r} (fail closed)")
    lowered = out.lower()
    hits = [m for m in FORBIDDEN_AUTH_MARKERS if m in lowered]
    if hits:
        sys.exit(f"ABORT: auth status suggests API-billing credential source {hits} (fail closed)")
    EVIDENCE.save_json(f"{phase}_billing_evidence.json", {
        "claim": rc.BILLING_CLAIM,
        "auth_method": status.get("authMethod"), "api_provider": status.get("apiProvider"),
        "subscription_type": status.get("subscriptionType"),
        "auth_status_sha256": sha256_text(out), "exit_code": proc.returncode,
    })


def write_safety_attestation(phase: str):
    EVIDENCE.save_json(f"{phase}_safety_attestation.json", {
        "phase": phase,
        "billing_route": "Claude subscription — `claude auth status` verified in minimal allowlist env",
        "model": rc.CLAUDE_MODEL,
        "profile_label": rc.PROFILE_LABEL,
        "profile_note": rc.PROFILE_NOTE,
        "native_tools": rc.PHASE_TOOLS[phase],
        "permission_relay": "can_use_tool → core/relay.py PermissionRelay (exactly-once, native parity)",
        "auto_permitted_actions": "observed via PostToolUse hooks → tool_completed audit records (0002)",
        "workspace": str(rc.STAGING),
        "environment_policy": "allowlist",
    })


# ---- native-parity gate + audit hooks ----

def expected_card_payload(phase: str) -> dict | None:
    """The ONLY card the manifest authorizes for this phase (None = no card)."""
    if phase in ("approval-allow", "approval-deny"):
        return rc.expected_write_payload(phase)
    return None


def normalized(phase: str, tool_name: str, tool_input: dict, kind: str,
               tool_use_id: str, extra_annotations: dict | None = None,
               payload_extra: dict | None = None) -> NormalizedRequest:
    """Runtime identifiers are hashed AT this boundary (R9 f.2); a missing
    tool_use_id is rejected BEFORE hashing (R10 f.4 — sha256("") would
    masquerade as a valid key)."""
    if not tool_use_id:
        raise ValueError(f"{phase}/{kind}: runtime supplied no tool_use_id — "
                         "cannot form an exactly-once correlation key (fail closed)")
    return NormalizedRequest(
        provider="claude", case=rc.CASE, phase=phase, model=rc.CLAUDE_MODEL_LABEL,
        role=rc.PHASE_ROLE[phase], kind=kind,
        payload={"tool": tool_name, "input": dict(tool_input), **(payload_extra or {})},
        correlation_id=sha256_text(tool_use_id),
        annotations={**path_annotations(dict(tool_input), rc.STAGING),
                     "tool": tool_name, **(extra_annotations or {})},
    )


def make_can_use_tool(phase: str):
    expected = expected_card_payload(phase)

    async def can_use_tool(tool_name, tool_input, context):
        payload = {"tool": tool_name, "input": dict(tool_input)}
        # incident-001 / R12 amendment 7: the card itself must say whether
        # this is the manifest-authorized action — deterministic enrichment
        match_notes = {
            "manifest_match": expected is not None and payload == expected,
            "manifest_expected": (canonical(expected) if expected is not None
                                  else "NO CARD IS EXPECTED IN THIS PHASE"),
        }
        req = normalized(phase, tool_name, dict(tool_input),
                         kind="can_use_tool", tool_use_id=context.tool_use_id or "",
                         extra_annotations=match_notes)
        decision, reason = RELAY.relay(req)
        if decision == "allow":
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"Denied by Dialektikḗ relay: {reason}")
    return can_use_tool


def make_hooks(phase: str):
    """PostToolUse fires only after the native runtime EXECUTED a tool — the
    authoritative completion proof for auto-permitted actions."""
    async def post_tool_use(input_data, tool_use_id, context):
        resp = input_data.get("tool_response")
        RELAY.audit(normalized(
            phase, input_data.get("tool_name", ""), dict(input_data.get("tool_input", {})),
            kind="hook:PostToolUse", tool_use_id=tool_use_id or "",
            extra_annotations={"response_sha256": sha256_text(
                json.dumps(resp, sort_keys=True, default=str))},
        ), kind="tool_completed")
        return {}

    async def post_tool_use_failure(input_data, tool_use_id, context):
        error_text = str(input_data.get("error", ""))
        RELAY.audit(normalized(
            phase, input_data.get("tool_name", ""), dict(input_data.get("tool_input", {})),
            kind="hook:PostToolUseFailure", tool_use_id=tool_use_id or "",
            payload_extra={"error": error_text},
            extra_annotations={"error_sha256": sha256_text(error_text)},
        ), kind="tool_failed")
        return {}

    return {"PostToolUse": [HookMatcher(hooks=[post_tool_use])],
            "PostToolUseFailure": [HookMatcher(hooks=[post_tool_use_failure])]}


def options(phase: str, resume_id: str | None = None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=str(rc.STAGING), model=rc.CLAUDE_MODEL, max_turns=4,
        tools=list(rc.PHASE_TOOLS[phase]),  # native built-ins, minimal per-phase set
        allowed_tools=[],                   # nothing auto-allowed past the gate
        setting_sources=[],                 # controlled spike profile — see PROFILE_NOTE
        permission_mode="default",          # native default permission policy
        can_use_tool=make_can_use_tool(phase),
        hooks=make_hooks(phase),
        output_format=VERDICT_OUTPUT_FORMAT if phase == "verdict" else None,
        resume=resume_id,
    )


async def run_turn(phase: str, opts: ClaudeAgentOptions, prompt: str):
    """Returns (text, session_id, tool_uses, tool_results, result_info).
    The COMPLETE turn outcome is captured to raw/ BEFORE any caller parses
    anything (incident-001: the verdict reply was lost in an uncaught crash)."""
    text: list[str] = []
    tool_uses: list[dict] = []
    tool_results: list[dict] = []
    session_id = None
    result_info: dict = {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", CanUseToolShadowedWarning)
        async with ClaudeSDKClient(options=opts) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, TextBlock):
                            text.append(b.text)
                        elif isinstance(b, ToolUseBlock):
                            tool_uses.append({"id": b.id, "name": b.name,
                                              "input": dict(b.input)})
                elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                    for b in msg.content:
                        if isinstance(b, ToolResultBlock):
                            content = b.content if isinstance(b.content, str) \
                                else canonical(b.content)
                            tool_results.append({"tool_use_id": b.tool_use_id,
                                                 "is_error": bool(b.is_error),
                                                 "content_sha256": sha256_text(content or ""),
                                                 "content": content})
                elif isinstance(msg, ResultMessage):
                    session_id = msg.session_id
                    result_info = {
                        "result": msg.result,
                        "structured_output": msg.structured_output,
                        "subtype": msg.subtype,
                        "stop_reason": msg.stop_reason,
                        "is_error": bool(getattr(msg, "is_error", False)),
                        "errors": getattr(msg, "errors", None),
                        "usage": msg.usage,
                        "num_turns": msg.num_turns,
                    }
    # capture-before-parse (R12): whatever happens next, the evidence exists
    EVIDENCE.save_raw(f"{phase}_turn_capture.json", json.dumps(
        {"assistant_text": "".join(text), "tool_uses": tool_uses,
         **result_info}, indent=2, ensure_ascii=False, default=str))
    if result_info.get("is_error"):
        raise AssertionError(f"ResultMessage.is_error set (subtype="
                             f"{result_info.get('subtype')!r}, errors="
                             f"{result_info.get('errors')!r})")
    shadow = [str(w.message) for w in caught if issubclass(w.category, CanUseToolShadowedWarning)]
    EVIDENCE.save_json(f"{phase}_shadow_warnings.json", shadow)
    if shadow:
        raise AssertionError(f"gate is shadowed — isolation failed: {shadow}")
    if not session_id:
        raise AssertionError("no session_id in ResultMessage — cannot certify session")
    return "".join(text).strip(), session_id, tool_uses, tool_results, result_info


# ---- proofs from the chain-verified log ----

ACTION_KINDS = ("permission_decision", "tool_completed", "tool_failed")


def phase_records(phase: str) -> list[dict]:
    return [r for r in LOG.verified_records()
            if r.get("phase") == phase and r.get("kind") in ACTION_KINDS]


def decisions(phase: str) -> list[dict]:
    return [r for r in phase_records(phase) if r["kind"] == "permission_decision"]


def completions(phase: str, tool: str) -> list[dict]:
    return [r for r in phase_records(phase) if r["kind"] == "tool_completed"
            and (r.get("annotations") or {}).get("tool") == tool]


def assert_no_native_actions(phase: str, tool_uses: list[dict]):
    recs = phase_records(phase)
    if recs or tool_uses:
        raise AssertionError(f"{phase}: expected zero native actions, log={recs} "
                             f"stream={tool_uses}")


def assert_decision_proven(phase: str, expected_decision: str):
    """Exactly ONE permission decision in the phase, fingerprint-exact against
    the contract's expected native Write request."""
    recs = phase_records(phase)
    decs = decisions(phase)
    if len(decs) != 1:
        raise AssertionError(f"{phase}: expected exactly 1 permission decision, "
                             f"found {len(decs)} (all action records: {len(recs)})")
    rec = decs[0]
    want = NormalizedRequest(
        provider="claude", case=rc.CASE, phase=phase, model=rc.CLAUDE_MODEL_LABEL,
        role=rc.PHASE_ROLE[phase], kind="can_use_tool",
        payload=rc.expected_write_payload(phase), correlation_id="unused").enrich()
    if rec.get("fingerprint") != want.fingerprint:
        raise AssertionError(f"{phase}: logged fingerprint {rec.get('fingerprint')!r} != "
                             f"expected {want.fingerprint!r} — the model issued a different "
                             "request than the manifest describes")
    if rec.get("decision") != expected_decision:
        raise AssertionError(f"{phase}: decision {rec.get('decision')!r} != {expected_decision!r}")
    if (rec.get("annotations") or {}).get("manifest_match") is not True:
        raise AssertionError(f"{phase}: decided card was not annotated manifest_match=True")


def validate_verdict(verdict) -> dict:
    """STRICT structural validation of the authoritative structured output.
    No fence-stripping, no repair (R6 rule) — a wrong shape fails the phase."""
    if not isinstance(verdict, dict) or set(verdict) != {"claim_id", "verdict", "argument"}:
        raise AssertionError(f"structured output schema violation — {verdict!r}")
    if verdict["claim_id"] != rc.CLAIM_ID or verdict["verdict"] not in rc.VERDICT_ENUM \
            or not isinstance(verdict["argument"], str) or not verdict["argument"].strip():
        raise AssertionError(f"structured output schema violation — {verdict!r}")
    return verdict


def ensure_staging_exists():
    """The SDK requires cwd to exist for EVERY phase (incident-001 defect 1).
    Creation is not cleaning — only STAGING_CLEANING_PHASES delete content."""
    rc.STAGING.mkdir(parents=True, exist_ok=True)


def clean_staging(phase: str):
    """Disclosed destructive step (manifest v9): only for phases in
    run_contract.STAGING_CLEANING_PHASES. Deletion errors ABORT; prior
    content is byte-hash-snapshotted recursively first."""
    assert phase in rc.STAGING_CLEANING_PHASES
    if rc.STAGING.exists():
        snapshot = {str(p.relative_to(rc.STAGING)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(rc.STAGING.rglob("*")) if p.is_file()}
        if snapshot:
            EVIDENCE.save_json(f"{phase}_staging_snapshot_before_clean.json", snapshot)
        shutil.rmtree(rc.STAGING)  # raises on failure — no silent partial state
    rc.STAGING.mkdir(parents=True)


def staging_snapshot() -> dict:
    return {str(p.relative_to(rc.STAGING)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(rc.STAGING.rglob("*")) if p.is_file()}


# ---- phases ----

async def phase_verdict():
    text, session_id, tool_uses, _, result_info = await run_turn(
        "verdict", options("verdict"), AUDIT_PROMPT)
    # structured output is AUTHORITATIVE (R12 amendment 2); captured to raw/
    # by run_turn before this line, so a failure here loses nothing
    verdict = validate_verdict(result_info.get("structured_output"))
    assert_no_native_actions("verdict", tool_uses)
    EVIDENCE.save_json("verdict_result.json", {**verdict, "session": EVIDENCE.hashed_id(session_id)})
    EVIDENCE.record_state("claude_session_id", session_id)
    print(f"PHASE verdict PASS — {verdict['verdict']} on C1 via structured output; session persisted")


async def phase_resume():
    session_id = EVIDENCE.read_state("claude_session_id")
    text, resumed_id, tool_uses, _, _ = await run_turn(
        "resume", options("resume", resume_id=session_id),
        "Which claim_id did you audit in this session? Reply with the ID only.")
    EVIDENCE.save_text("resume_reply.txt", text)
    assert_no_native_actions("resume", tool_uses)
    EVIDENCE.save_json("resume_continuity.json", {
        "persisted": EVIDENCE.hashed_id(session_id),
        "resumed": EVIDENCE.hashed_id(resumed_id),
        "equal": resumed_id == session_id,
    })
    if resumed_id != session_id:  # fork_session=False is the documented default
        raise AssertionError(f"resumed session id differs from persisted id "
                             f"(types.py:1943) — {EVIDENCE.hashed_id(resumed_id)} != "
                             f"{EVIDENCE.hashed_id(session_id)}")
    if text.strip() != rc.CLAIM_ID:
        raise AssertionError(f"resume failed — reply: {text!r}")
    print("PHASE resume PASS — exact session (same id) recalled C1 across processes")


async def phase_auto_read():
    """Passes only if the exact native Read is OBSERVED to start and complete
    successfully (hook + stream), its result is evidenced, the model
    demonstrably received the content, and ZERO permission decisions exist."""
    phase = "auto-read"
    clean_staging(phase)
    brief = rc.brief_path()
    brief.write_text(rc.BRIEF_CONTENT)
    # incident-001 defect 2: the model must be given the ABSOLUTE path
    prompt = (f"Use the Read tool to read the file {brief} and quote its first line. "
              "If permission is denied, stop and say DENIED-OK.")
    text, _, tool_uses, tool_results, _ = await run_turn(phase, options(phase), prompt)
    EVIDENCE.save_text(f"{phase}_reply.txt", text)

    if decisions(phase):
        raise AssertionError(f"{phase}: a permission card was raised for a native read — "
                             f"native parity violated: {decisions(phase)}")
    reads = [t for t in tool_uses if t["name"] == rc.AUTO_READ_TOOL]
    if len(reads) != 1:
        raise AssertionError(f"{phase}: expected exactly 1 native Read, stream shows {tool_uses}")
    got_path = Path(str(reads[0]["input"].get("file_path", ""))).resolve()
    if got_path != brief.resolve():
        raise AssertionError(f"{phase}: Read targeted {got_path}, expected {brief}")
    results = [r for r in tool_results if r["tool_use_id"] == reads[0]["id"]]
    if len(results) != 1 or results[0]["is_error"]:
        raise AssertionError(f"{phase}: no successful tool result for the Read: {results}")
    hooked = completions(phase, rc.AUTO_READ_TOOL)
    if len(hooked) != 1:
        raise AssertionError(f"{phase}: expected exactly 1 tool_completed audit record "
                             f"(PostToolUse hook), found {len(hooked)}")
    if (hooked[0].get("annotations") or {}).get("resolved_path") != str(brief.resolve()):
        raise AssertionError(f"{phase}: hook record path mismatch: {hooked[0]}")
    if rc.BRIEF_MARKER not in text:
        raise AssertionError(f"{phase}: model reply does not quote the brief marker — "
                             "read completion not demonstrated end-to-end")
    EVIDENCE.save_json(f"{phase}_observation.json", {
        "tool_use": {"id_sha256": sha256_text(reads[0]["id"]),
                     "name": reads[0]["name"], "input": reads[0]["input"]},
        "tool_result_error": results[0]["is_error"],
        "result_sha256": results[0]["content_sha256"],
        "hook_confirmed": True, "hook_fingerprint": hooked[0].get("fingerprint"),
        "path": str(got_path), "permission_decisions": 0,
    })
    print(f"PHASE {phase} PASS — native Read observed start-to-completion "
          "(hook + stream + quoted content), zero cards, audit-logged")


async def phase_approval(expect_allow: bool):
    phase = "approval-allow" if expect_allow else "approval-deny"
    target = rc.write_target(phase)
    clean_staging(phase)
    # incident-001 defect 2: exact ABSOLUTE disposable target in the prompt
    prompt = (f"Use the Write tool to create the file {target} containing "
              f"exactly: {rc.WRITE_CONTENT}. If permission is denied, stop and say DENIED-OK.")
    text, _, tool_uses, _, _ = await run_turn(phase, options(phase), prompt)
    assert_decision_proven(phase, "allow" if expect_allow else "deny")
    done = completions(phase, "Write")
    if expect_allow:
        if len(done) != 1:
            raise AssertionError(f"{phase}: approved Write not confirmed by PostToolUse "
                                 f"hook (found {len(done)} completions)")
        if not (target.exists() and target.read_text() == rc.WRITE_CONTENT):
            raise AssertionError(f"{phase}: filesystem does not show the approved exact content")
    else:
        if done:
            raise AssertionError(f"{phase}: DENIED Write reported completed: {done}")
        if target.exists():
            raise AssertionError(f"{phase}: denied file exists — deny not enforced")
    EVIDENCE.save_json(f"{phase}_result.json", {
        "file_exists": target.exists(), "reply": text,
        "write_completions": len(done),
    })
    EVIDENCE.save_json(f"{phase}_staging_snapshot.json", staging_snapshot())
    print(f"PHASE {phase} PASS — native Write card decision proven "
          f"({'executed' if expect_allow else 'blocked'}), filesystem consistent")


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    if phase not in rc.CLAUDE_PHASES:
        sys.exit(f"usage: claude_leg.py {{{'|'.join(rc.CLAUDE_PHASES)}}} — unknown phase fails closed")
    enforce_minimal_environment(phase)  # one env for preflight AND SDK child
    assert_subscription_auth(phase)     # aborts before any SDK spawn
    write_safety_attestation(phase)
    EVIDENCE.write_manifest(phase, {"leg": "claude", "case": rc.CASE})
    ensure_staging_exists()             # SDK cwd must exist for EVERY phase
    dispatch = {
        "verdict": phase_verdict,
        "resume": phase_resume,
        "auto-read": phase_auto_read,
        "approval-allow": lambda: phase_approval(expect_allow=True),
        "approval-deny": lambda: phase_approval(expect_allow=False),
    }
    try:
        asyncio.run(dispatch[phase]())
    except BaseException as exc:  # noqa: BLE001 — incident-001: failures must be CONTROLLED
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        EVIDENCE.save_raw(f"{phase}_failure_traceback.txt", traceback.format_exc())
        print(f"PHASE {phase} FAIL (controlled): {type(exc).__name__}: {exc}")
        sys.exit(1)
    finally:
        print(LOG.anchor_receipt())


if __name__ == "__main__":
    main()
