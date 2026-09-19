"""Dialektikḗ spike v2.4 — synthetic evidence-layout check (non-model).

Live's GO item 5 (R8.1): before any live model call, PROVE that a fully
successful run can pass verify_run.py. v2.3 never proved this, and indeed a
perfect v2.3 run would have deterministically failed its own verifier
(billing-filename collision, R8 P0-2). This script:

  1. fabricates the COMPLETE evidence layout for every contract phase
     (run_contract.py — the same single definition the legs and verifier use),
     generating the decision logs through the REAL PermissionRelay code path
     with a scripted presenter, so the records are structurally identical to
     a live run's;
  2. requires verify_run.run() to PASS on the clean layout (and on a variant
     containing one legitimately relayed native Codex approval — the bijection
     must accept genuine forwards, not just the zero case);
  3. requires verify_run.run() to FAIL on each mutation, for the RIGHT reason
     (asserted by failure-message substring).

Exit 0 only if every scenario behaves as expected. No model, no network.

Run: ./venv/bin/python spike/v2/synthetic_check.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "spike" / "v2"))

import run_contract as rc  # noqa: E402
import verify_run  # noqa: E402
from core.broker import ChainedLog, canonical, sha256_text  # noqa: E402
from core.relay import NormalizedRequest, PermissionRelay, path_annotations  # noqa: E402

SYNTH_SESSION = "sess-synthetic-0001"
SYNTH_THREAD = "thr-synthetic-0001"


def presenter_returning(answer: str):
    return lambda req, card: answer


def claude_request(phase: str, staging: Path, raw_tool_use_id: str) -> NormalizedRequest:
    """Mirror of claude_leg.normalized() for the expected Write request —
    ids HASHED at the boundary (R10 f.2), manifest-match annotated (R12 a.7)."""
    payload = rc.expected_write_payload(phase, staging)
    return NormalizedRequest(
        provider="claude", case=rc.CASE, phase=phase, model=rc.CLAUDE_MODEL_LABEL,
        role=rc.PHASE_ROLE[phase], kind="can_use_tool", payload=payload,
        correlation_id=sha256_text(raw_tool_use_id),
        annotations={**path_annotations(payload["input"], staging), "tool": "Write",
                     "manifest_match": True, "manifest_expected": canonical(payload)},
    )


def hook_request(phase: str, tool: str, file_path: Path, staging: Path,
                 raw_tool_use_id: str) -> NormalizedRequest:
    tool_input = {"file_path": str(file_path)}
    return NormalizedRequest(
        provider="claude", case=rc.CASE, phase=phase, model=rc.CLAUDE_MODEL_LABEL,
        role=rc.PHASE_ROLE[phase], kind="hook:PostToolUse",
        payload={"tool": tool, "input": tool_input},
        correlation_id=sha256_text(raw_tool_use_id),
        annotations={**path_annotations(tool_input, staging), "tool": tool,
                     "response_sha256": sha256_text("synthetic response")},
    )


def codex_request(phase: str, method: str, params: dict, raw_corr_seed: str
                  ) -> NormalizedRequest:
    return NormalizedRequest(
        provider="codex", case=rc.CASE, phase=phase, model=rc.CODEX_MODEL_LABEL,
        role="auditor", kind=method, payload=params,
        correlation_id=sha256_text(raw_corr_seed),
        annotations={"thread_id_sha256": sha256_text(SYNTH_THREAD)},
    )


def write_json(dirpath: Path, name: str, obj):
    (dirpath / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def build(root: Path, flip_deny: bool = False, with_codex_relay: bool = False,
          no_toolcall: bool = False) -> tuple[Path, Path]:
    """Fabricate the full contract evidence layout under root."""
    evidence_root = root / "evidence"
    staging = root / "staging"
    staging.mkdir(parents=True)
    claude_dir = evidence_root / rc.CLAUDE_EVIDENCE
    codex_dir = evidence_root / rc.CODEX_EVIDENCE
    for d in (claude_dir, codex_dir):
        (d / "raw").mkdir(parents=True)

    # -- Claude decision log, through the REAL relay code path --
    clog = ChainedLog(claude_dir / "decisions.jsonl")
    relay_allow = PermissionRelay(clog, presenter_returning("allow"), claude_dir / "raw")
    relay_deny = PermissionRelay(clog, presenter_returning("deny"), claude_dir / "raw")
    relay_allow.audit(hook_request("auto-read", rc.AUTO_READ_TOOL,
                                   rc.brief_path(staging), staging, "toolu_synth_read"),
                      kind="tool_completed")
    relay_allow.relay(claude_request("approval-allow", staging, "toolu_synth_allow"))
    relay_allow.audit(hook_request("approval-allow", "Write",
                                   rc.write_target("approval-allow", staging), staging,
                                   "toolu_synth_allow"),
                      kind="tool_completed")
    (relay_allow if flip_deny else relay_deny).relay(
        claude_request("approval-deny", staging, "toolu_synth_deny"))

    # -- Claude evidence files (contract inventory) --
    for phase in rc.CLAUDE_PHASES:
        write_json(claude_dir, f"{phase}_billing_evidence.json", {
            "claim": rc.BILLING_CLAIM, "auth_method": "claude.ai",
            "api_provider": "firstParty", "subscription_type": "pro",
            "auth_status_sha256": sha256_text("synthetic auth status"), "exit_code": 0,
        })
        write_json(claude_dir, f"{phase}_env_attestation.json", {
            "policy": "allowlist", "kept": ["HOME", "PATH"], "dropped_count": 40,
            "dropped_names_sha256": sha256_text("[]"),
        })
        write_json(claude_dir, f"{phase}_safety_attestation.json", {
            "phase": phase, "billing_route": "synthetic", "model": rc.CLAUDE_MODEL,
            "profile_label": rc.PROFILE_LABEL, "profile_note": rc.PROFILE_NOTE,
            "native_tools": list(rc.PHASE_TOOLS[phase]),
            "workspace": str(staging), "environment_policy": "allowlist",
        })
        write_json(claude_dir, f"{phase}_shadow_warnings.json", [])
        write_json(claude_dir, f"{phase}_run_manifest.json",
                   {"phase": phase, "leg": "claude", "case": rc.CASE, "synthetic": True})
    write_json(claude_dir, "verdict_result.json", {
        "claim_id": rc.CLAIM_ID, "verdict": "CHALLENGE",
        "argument": "synthetic argument", "session": "sha256:" + sha256_text(SYNTH_SESSION),
    })
    (claude_dir / "resume_reply.txt").write_text(rc.CLAIM_ID)
    write_json(claude_dir, "resume_continuity.json", {
        "persisted": "sha256:" + sha256_text(SYNTH_SESSION),
        "resumed": "sha256:" + sha256_text(SYNTH_SESSION), "equal": True,
    })
    write_json(claude_dir, "auto-read_observation.json", {
        # R10 f.2: mirror production — hashed id only, never the raw id
        "tool_use": {"id_sha256": sha256_text("toolu_synth_read"),
                     "name": rc.AUTO_READ_TOOL,
                     "input": {"file_path": str(rc.brief_path(staging))}},
        "tool_result_error": False, "result_sha256": sha256_text(rc.BRIEF_CONTENT),
        "hook_confirmed": True, "hook_fingerprint": "synthetic",
        "path": str(rc.brief_path(staging).resolve()), "permission_decisions": 0,
    })
    (claude_dir / "auto-read_reply.txt").write_text(
        f"The first line is: {rc.BRIEF_CONTENT}")
    write_json(claude_dir, "approval-allow_result.json",
               {"file_exists": True, "reply": "wrote it", "write_completions": 1})
    write_json(claude_dir, "approval-allow_staging_snapshot.json",
               {rc.APPROVED_NAME: sha256_text(rc.WRITE_CONTENT)})
    write_json(claude_dir, "approval-deny_result.json",
               {"file_exists": False, "reply": "DENIED-OK", "write_completions": 0})
    write_json(claude_dir, "approval-deny_staging_snapshot.json", {})
    # R9 f.4: the two deterministic pre-clean snapshots are REQUIRED evidence
    for phase, want in rc.required_preclean_snapshots().items():
        write_json(claude_dir, f"{phase}_staging_snapshot_before_clean.json", want)
    write_json(claude_dir / "raw", "state.json", {"claude_session_id": SYNTH_SESSION})

    # -- Codex decision log --
    verdict_args = {"claim_id": rc.CLAIM_ID, "verdict": "AGREE",
                    "argument": "synthetic argument"}
    xlog = ChainedLog(codex_dir / "decisions.jsonl")
    xrelay = PermissionRelay(xlog, presenter_returning("allow"), codex_dir / "raw")
    if not no_toolcall:
        xrelay.audit(codex_request("verdict", "item/tool/call",
                                   {"threadId": SYNTH_THREAD, "turnId": "turn-1",
                                    "callId": "call-1", "tool": "submit_verdict",
                                    "arguments": json.dumps(verdict_args)},
                                   "corr-toolcall-1"),
                     kind="server_request")
    if with_codex_relay:
        # one legitimately forwarded native approval: request + matching decision,
        # PLUS an exact wire retransmission answered by replay (no second card)
        params = {"threadId": SYNTH_THREAD, "turnId": "turn-1",
                  "command": "cat /etc/hosts"}
        xrelay.audit(codex_request("verdict", "execCommandApproval", params,
                                   "corr-approval-1"), kind="server_request")
        xrelay.relay(codex_request("verdict", "execCommandApproval", params,
                                   "corr-approval-1"))
        xrelay.audit(codex_request("verdict", "execCommandApproval", params,
                                   "corr-approval-1"), kind="server_request")
        d, reason = xrelay.relay(codex_request("verdict", "execCommandApproval",
                                               params, "corr-approval-1"))
        assert d == "allow" and "replayed" in reason, "relay replay path broken"

    # -- Codex evidence files --
    for phase in rc.CODEX_PHASES:
        write_json(codex_dir, f"{phase}_billing_evidence.json",
                   {"claim": rc.BILLING_CLAIM, "account_type": "chatgpt", "plan_type": "plus"})
        write_json(codex_dir, f"{phase}_safety_attestation.json", {
            "phase": phase, "billing_route": "chatgpt subscription (planType=plus)",
            "model": "gpt-5.1-codex", "model_provider": "openai",
            "model_provider_allowlist": sorted(rc.ALLOWED_MODEL_PROVIDERS),
            "profile_label": rc.PROFILE_LABEL, "profile_note": rc.PROFILE_NOTE,
            "problems": [],
        })
        write_json(codex_dir, f"{phase}_client_health.json",
                   {"fatal": [], "unknown_requests": [], "declined_non_approvals": []})
        write_json(codex_dir, f"{phase}_item_summary.json",
                   {"summary": {"agentMessage": 1, "dynamicToolCall": 1}})
        # R9 f.4: the events reference must point at a real raw file with the
        # exact content hash — fabricate the raw stream the ref describes
        raw_events = json.dumps([{"method": "synthetic", "phase": phase}], indent=2)
        (codex_dir / "raw" / f"{phase}_events.json").write_text(raw_events)
        write_json(codex_dir, f"{phase}_events_ref.json",
                   {"events_sha256": sha256_text(raw_events), "count": 1})
        write_json(codex_dir, f"{phase}_run_manifest.json",
                   {"phase": phase, "leg": "codex", "case": rc.CASE, "synthetic": True})
    for phase, eff_name in (("verdict", "thread_start_effective.json"),
                            ("resume", "thread_resume_effective.json")):
        write_json(codex_dir, eff_name, {
            # incident-001: the server echoes the SandboxPolicy OBJECT, not
            # the requested wire string — the fixture mirrors the real wire
            **rc.EFFECTIVE_ECHO_STRINGS,
            "sandbox": {"type": "readOnly", "networkAccess": False},
            "model": "gpt-5.6-sol",
            "modelProvider": "openai", "cwd": str(rc.CODEX_CWD),
            "raw_sha256": sha256_text("synthetic"), "thread": "sha256:" + sha256_text(SYNTH_THREAD),
        })
    write_json(codex_dir, "verdict_result.json",
               {**verdict_args, "thread": "sha256:" + sha256_text(SYNTH_THREAD)})
    args_hash = sha256_text(canonical(verdict_args))
    write_json(codex_dir, "verdict_path.json", {
        "path": "dynamicToolCall",
        # ids modelled as equal (Codex R9 claims the join; the schema does not
        # promise it, so the leg records ids_equal as an observation only)
        "call_id_sha256": sha256_text("call-1"), "item_id_sha256": sha256_text("call-1"),
        "ids_equal": True,
        "call_args_sha256": args_hash, "item_args_sha256": args_hash,
        "args_sha256": args_hash,
    })
    (codex_dir / "resume_reply.txt").write_text(rc.CLAIM_ID)
    write_json(codex_dir / "raw", "state.json", {"codex_thread_id": SYNTH_THREAD})

    return evidence_root, staging


# ---- mutation matrix ----

def mutate_chain(evidence_root: Path, staging: Path):
    path = evidence_root / rc.CLAUDE_EVIDENCE / "decisions.jsonl"
    lines = path.read_text().splitlines()
    lines[0] = lines[0].replace('"decision"', '"tampered"', 1) if '"decision"' in lines[0] \
        else lines[0][:-2] + 'X"'
    path.write_text("\n".join(lines) + "\n")


def mutate_duplicate(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CLAUDE_EVIDENCE
    shutil.copy(d / "verdict_result.json", d / "verdict_result.1.json")


def mutate_missing(evidence_root: Path, staging: Path):
    (evidence_root / rc.CLAUDE_EVIDENCE / "auto-read_observation.json").unlink()


def mutate_billing(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CLAUDE_EVIDENCE
    obj = json.loads((d / "verdict_billing_evidence.json").read_text())
    obj["api_provider"] = "bedrock"
    write_json(d, "verdict_billing_evidence.json", obj)


def mutate_provider(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CODEX_EVIDENCE
    obj = json.loads((d / "thread_start_effective.json").read_text())
    obj["modelProvider"] = "custom-proxy"
    write_json(d, "thread_start_effective.json", obj)


def mutate_unknown_request(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CODEX_EVIDENCE
    write_json(d, "verdict_client_health.json",
               {"fatal": [], "unknown_requests": ["attestation/generate"],
                "declined_non_approvals": []})


def mutate_unmatched_relay(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CODEX_EVIDENCE
    xrelay = PermissionRelay(ChainedLog(d / "decisions.jsonl"),
                             presenter_returning("allow"), d / "raw")
    xrelay.relay(codex_request("verdict", "execCommandApproval",
                               {"command": "phantom"}, "corr-phantom"))


def mutate_profile_label(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CLAUDE_EVIDENCE
    obj = json.loads((d / "verdict_safety_attestation.json").read_text())
    obj["profile_label"] = "native-default"
    write_json(d, "verdict_safety_attestation.json", obj)


def mutate_marker(evidence_root: Path, staging: Path):
    (evidence_root / rc.CLAUDE_EVIDENCE / "auto-read_reply.txt").write_text(
        "I was unable to read the file.")


def mutate_duplicate_decision(evidence_root: Path, staging: Path):
    """Forge a second decision for an already-decided correlation key —
    the relay itself can no longer produce this (idempotent), so append
    directly; the chain stays valid, the ledger must catch it (R9 P0)."""
    req = claude_request("approval-allow", staging, "toolu_synth_allow").enrich()
    ChainedLog(evidence_root / rc.CLAUDE_EVIDENCE / "decisions.jsonl").append({
        "kind": "permission_decision", **req.tracked_record(),
        "payload_raw_ref": None, "decision": "allow", "reason": "forged duplicate"})


def mutate_orphan_claim(evidence_root: Path, staging: Path):
    """A claim with no recorded decision = a card died mid-answer — must fail."""
    req = claude_request("approval-allow", staging, "corr-orphan").enrich()
    ChainedLog(evidence_root / rc.CLAUDE_EVIDENCE / "decisions.jsonl").append({
        "kind": "relay_claim", **req.tracked_record(), "payload_raw_ref": None})


def mutate_args_join(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CODEX_EVIDENCE
    obj = json.loads((d / "verdict_path.json").read_text())
    obj["item_args_sha256"] = sha256_text("different arguments")
    write_json(d, "verdict_path.json", obj)


def mutate_missing_raw_events(evidence_root: Path, staging: Path):
    (evidence_root / rc.CODEX_EVIDENCE / "raw" / "verdict_events.json").unlink()


def mutate_missing_log(evidence_root: Path, staging: Path):
    (evidence_root / rc.CLAUDE_EVIDENCE / "decisions.jsonl").unlink()


def mutate_preclean(evidence_root: Path, staging: Path):
    write_json(evidence_root / rc.CLAUDE_EVIDENCE,
               "approval-deny_staging_snapshot_before_clean.json", {})


def mutate_raw_corr(evidence_root: Path, staging: Path):
    """A raw (unhashed) runtime id used as a correlation key — the format
    gate must reject it (R10 f.2)."""
    d = evidence_root / rc.CLAUDE_EVIDENCE
    req = NormalizedRequest(
        provider="claude", case=rc.CASE, phase="approval-allow",
        model=rc.CLAUDE_MODEL_LABEL, role="executor", kind="can_use_tool",
        payload={"tool": "Write", "input": {"x": 1}},
        correlation_id="toolu_raw_leak_0001", annotations={"tool": "Write"})
    PermissionRelay(ChainedLog(d / "decisions.jsonl"),
                    presenter_returning("allow"), d / "raw").relay(req)


def mutate_obs_raw_id(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CLAUDE_EVIDENCE
    obs = json.loads((d / "auto-read_observation.json").read_text())
    obs["tool_use"] = {"id": "toolu_synth_read", "name": rc.AUTO_READ_TOOL,
                       "input": obs["tool_use"]["input"]}
    write_json(d, "auto-read_observation.json", obs)


def mutate_chain_unbound_verdict(evidence_root: Path, staging: Path):
    """Edit verdict_result.json AND verdict_path.json consistently while the
    hash-chained wire record keeps the original arguments — only the chain
    binding can catch this (R10 f.3)."""
    d = evidence_root / rc.CODEX_EVIDENCE
    verdict = json.loads((d / "verdict_result.json").read_text())
    verdict["verdict"] = "CHALLENGE"
    write_json(d, "verdict_result.json", verdict)
    args = {k: verdict[k] for k in ("claim_id", "verdict", "argument")}
    forged = sha256_text(canonical(args))
    vpath = json.loads((d / "verdict_path.json").read_text())
    vpath.update({"args_sha256": forged, "call_args_sha256": forged,
                  "item_args_sha256": forged})
    write_json(d, "verdict_path.json", vpath)


def mutate_replay_answer(evidence_root: Path, staging: Path):
    """A replay record whose answer differs from the recorded decision —
    the ledger must reject it (R10 f.4)."""
    req = claude_request("approval-allow", staging, "toolu_synth_allow").enrich()
    ChainedLog(evidence_root / rc.CLAUDE_EVIDENCE / "decisions.jsonl").append({
        "kind": "replay_returned", **req.tracked_record(),
        "replayed_decision": "deny"})  # original was allow


def mutate_sandbox_writable(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CODEX_EVIDENCE
    obj = json.loads((d / "thread_start_effective.json").read_text())
    obj["sandbox"] = {"type": "workspaceWrite", "networkAccess": False}
    write_json(d, "thread_start_effective.json", obj)


def mutate_sandbox_network(evidence_root: Path, staging: Path):
    d = evidence_root / rc.CODEX_EVIDENCE
    obj = json.loads((d / "thread_resume_effective.json").read_text())
    obj["sandbox"] = {"type": "readOnly", "networkAccess": True}
    write_json(d, "thread_resume_effective.json", obj)


def mutate_card_unmatched(evidence_root: Path, staging: Path):
    """A decided card whose annotations lack manifest_match=True — the
    allow-only-on-MATCH policy must be evidenced, not assumed (R12 a.7)."""
    d = evidence_root / rc.CLAUDE_EVIDENCE
    log = ChainedLog(d / "decisions.jsonl")
    # rebuild is impossible without breaking the chain; instead fabricate a
    # FRESH log whose approval-allow decision lacks the annotation
    (d / "decisions.jsonl").unlink()
    relay_allow = PermissionRelay(log, presenter_returning("allow"), d / "raw")
    relay_deny = PermissionRelay(log, presenter_returning("deny"), d / "raw")
    relay_allow.audit(hook_request("auto-read", rc.AUTO_READ_TOOL,
                                   rc.brief_path(staging), staging, "toolu_synth_read"),
                      kind="tool_completed")
    bare = claude_request("approval-allow", staging, "toolu_synth_allow")
    bare.annotations = {**path_annotations(bare.payload["input"], staging), "tool": "Write"}
    relay_allow.relay(bare)
    relay_allow.audit(hook_request("approval-allow", "Write",
                                   rc.write_target("approval-allow", staging), staging,
                                   "toolu_synth_allow"),
                      kind="tool_completed")
    relay_deny.relay(claude_request("approval-deny", staging, "toolu_synth_deny"))


SCENARIOS = [
    # (name, build kwargs, mutation, expect_pass, required failure substring)
    ("clean layout", {}, None, True, None),
    ("legit relayed approval + replay", {"with_codex_relay": True}, None, True, None),
    ("chain tamper", {}, mutate_chain, False, "chain"),
    ("duplicate artefact", {}, mutate_duplicate, False, "duplicate"),
    ("missing evidence file", {}, mutate_missing, False, "missing"),
    ("api-billing evidence", {}, mutate_billing, False, "billing"),
    ("provider not pinned", {}, mutate_provider, False, "allowlist"),
    ("unknown server request", {}, mutate_unknown_request, False, "unknown"),
    ("unmatched relay decision", {}, mutate_unmatched_relay, False, "wire"),
    ("wrong deny decision", {"flip_deny": True}, None, False, "decision"),
    ("profile label wrong", {}, mutate_profile_label, False, "profile"),
    ("read marker missing", {}, mutate_marker, False, "marker"),
    # R9 additions
    ("forged duplicate decision", {}, mutate_duplicate_decision, False, "DUPLICATE"),
    ("claim without decision", {}, mutate_orphan_claim, False, "bijective"),
    ("call/item arguments mismatch", {}, mutate_args_join, False, "joined"),
    ("missing raw event stream", {}, mutate_missing_raw_events, False, "raw"),
    ("missing decision log", {}, mutate_missing_log, False, "missing"),
    ("pre-clean snapshot wrong", {}, mutate_preclean, False, "pre-clean"),
    ("no dynamic tool-call trace", {"no_toolcall": True}, None, False, "item/tool/call"),
    # R10 additions
    ("raw correlation id leaked", {}, mutate_raw_corr, False, "format"),
    ("raw tool-use id in observation", {}, mutate_obs_raw_id, False, "raw id"),
    ("verdict edited around the chain", {}, mutate_chain_unbound_verdict, False, "chained"),
    ("replay answer differs from record", {}, mutate_replay_answer, False, "replay"),
    # incident-001 / R12 additions
    ("writable effective sandbox", {}, mutate_sandbox_writable, False, "sandbox"),
    ("network-enabled effective sandbox", {}, mutate_sandbox_network, False, "sandbox"),
    ("decided card not manifest-matched", {}, mutate_card_unmatched, False, "manifest_match"),
]


def main():
    workdir = Path(tempfile.mkdtemp(prefix="dialektike-synth-"))
    print(f"synthetic workdir: {workdir}\n")
    problems = []
    for i, (name, kwargs, mutation, expect_pass, substr) in enumerate(SCENARIOS):
        root = workdir / f"case-{i:02d}"
        evidence_root, staging = build(root, **kwargs)
        if mutation:
            mutation(evidence_root, staging)
        print(f"--- scenario: {name} ---")
        failures = verify_run.run(evidence_root=evidence_root, staging=staging)
        passed = not failures
        if passed != expect_pass:
            problems.append(f"{name}: expected {'PASS' if expect_pass else 'FAIL'}, "
                            f"got {'PASS' if passed else 'FAIL'} "
                            f"({failures[:3] if failures else 'no failures'})")
        elif not expect_pass and substr and not any(substr in f for f in failures):
            problems.append(f"{name}: failed, but no failure mentions {substr!r}: {failures[:5]}")
        print(f"--- {name}: {'PASS' if passed else f'{len(failures)} failure(s)'} "
              f"(expected {'PASS' if expect_pass else 'FAIL'}) ---\n")
    shutil.rmtree(workdir, ignore_errors=True)
    if problems:
        print("SYNTHETIC CHECK FAILED:")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)
    print(f"SYNTHETIC CHECK PASSED — {len(SCENARIOS)} scenarios behaved as expected "
          f"(verifier CAN pass, and fails for the right reasons)")


if __name__ == "__main__":
    main()
