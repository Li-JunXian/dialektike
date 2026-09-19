"""Dialektikḗ spike v2.4 — post-run verifier (non-model, deterministic).

Checks the WHOLE contract of EXECUTION_MANIFEST.md v6, which is defined once
in run_contract.py (GO clarification 1 — phases and evidence are derived,
never assumed). Exits nonzero on any failure.

R8 corrections:
  - evidence roots are parameters (env DIALEKTIKE_EVIDENCE_ROOT /
    DIALEKTIKE_STAGING_ROOT or run() arguments) so synthetic_check.py can
    prove this verifier CAN pass before any live model call (P0-2 class);
  - billing evidence is phase-qualified — the v2.3 layout deterministically
    failed here;
  - the duplicate scan covers ALL tracked evidence (GO clarification 4: raw/
    is exempt), plus a strict inventory: unexpected tracked files fail;
  - exactly-once is a correlation-id BIJECTION between relayable server
    requests and relayed decisions, not a bare count comparison;
  - unknown / non-approval server requests fail verification (R8 f.7);
  - the auto-read phase requires positive completion proof (hook record +
    observation + quoted marker), zero permission decisions (GO clar. 2);
  - the controlled-profile LABEL is asserted (GO clarification 1).

Run: ./venv/bin/python spike/v2/verify_run.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "spike" / "v2"))

import run_contract as rc  # noqa: E402
from core.broker import ChainedLog, canonical, sha256_text  # noqa: E402
from core.relay import NormalizedRequest  # noqa: E402

DUP_PATTERN = re.compile(r".*\.\d+\.[A-Za-z0-9]+$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ACTION_KINDS = ("permission_decision", "tool_completed", "tool_failed")
# every record of these kinds must carry a SHA-256 correlation id (R10 f.2 —
# raw runtime identifiers must be structurally unable to reach tracked records)
CORRELATED_KINDS = ("relay_claim", "permission_decision", "replay_returned",
                    "server_request", "tool_completed", "tool_failed",
                    "native_auto_permitted", "non_approval_declined",
                    "unknown_request_declined")


class Checker:
    def __init__(self):
        self.failures: list[str] = []

    def fail(self, msg: str):
        self.failures.append(msg)
        print(f"FAIL  {msg}")

    def ok(self, msg: str):
        print(f"OK    {msg}")

    def check(self, cond: bool, msg: str):
        (self.ok if cond else self.fail)(msg)

    # -- evidence access --

    def load(self, dirpath: Path, name: str):
        path = dirpath / name
        if not path.exists():
            self.fail(f"missing {path.name} in {dirpath.name}")
            return None
        if name.endswith(".json"):
            return json.loads(path.read_text())
        return path.read_text()

    def read_state(self, dirpath: Path, key: str):
        state = dirpath / "raw" / "state.json"
        if not state.exists():
            self.fail(f"missing raw/state.json in {dirpath.name}")
            return None
        return json.loads(state.read_text()).get(key)

    def verified(self, dirpath: Path) -> list[dict]:
        log = ChainedLog(dirpath / "decisions.jsonl")
        try:
            recs = log.verified_records()
            self.ok(f"chain verified — {dirpath.name}/decisions.jsonl ({len(recs)} records)")
            return recs
        except Exception as exc:
            self.fail(f"chain verification ({dirpath.name}): {exc}")
            return []

    def tracked_inventory(self, dirpath: Path, required: list[str], optional: set[str]):
        """Strict inventory + duplicate scan over TRACKED files only
        (GO clarification 4: raw/ is exempt — many raw events are legitimate).
        R9 f.4: the decision log itself is REQUIRED, not merely allowed."""
        if not dirpath.exists():
            self.fail(f"evidence dir missing: {dirpath}")
            return
        tracked = sorted(p.name for p in dirpath.iterdir() if p.is_file())
        dups = [n for n in tracked if DUP_PATTERN.match(n)]
        self.check(not dups, f"{dirpath.name}: no duplicate-suffixed tracked evidence"
                   if not dups else f"{dirpath.name}: rerun/duplicate artefacts {dups}")
        allowed = set(required) | optional | {"decisions.jsonl"}
        extras = [n for n in tracked if n not in allowed and not DUP_PATTERN.match(n)]
        self.check(not extras, f"{dirpath.name}: no unexpected tracked files"
                   if not extras else f"{dirpath.name}: unexpected tracked files {extras}")
        missing = [n for n in required + ["decisions.jsonl"] if not (dirpath / n).exists()]
        self.check(not missing, f"{dirpath.name}: all {len(required)} contract files "
                   "+ decision log present"
                   if not missing else f"{dirpath.name}: missing contract files {missing}")

    def raw_ref_check(self, dirpath: Path, name: str, ref_key: str, raw_name: str):
        """R9 f.4: a tracked *_ref hash must point at an EXISTING raw file with
        that exact content hash — otherwise the reference evidences nothing."""
        ref = self.load(dirpath, name)
        if ref is None:
            return
        raw_path = dirpath / "raw" / raw_name
        if not raw_path.exists():
            self.fail(f"{name}: referenced raw file {raw_name} missing")
            return
        self.check(sha256_text(raw_path.read_text()) == ref.get(ref_key),
                   f"{name}: raw reference hash matches {raw_name}")

    def relay_ledger(self, recs: list[dict], leg: str):
        """R9 P0: exactly-once as a LEDGER property, not a count.
        - correlation_conflict records are fatal;
        - decision correlation ids are UNIQUE;
        - claims ↔ decisions form a fingerprint-matching bijection;
        - every replay refers to an existing decision with the same fingerprint."""
        conflicts = [r for r in recs if r.get("kind") == "correlation_conflict"]
        self.check(not conflicts, f"{leg}: no correlation conflicts" if not conflicts
                   else f"{leg}: correlation conflicts recorded: {len(conflicts)}")
        bad_corr = [r.get("kind") for r in recs if r.get("kind") in CORRELATED_KINDS
                    and not HEX64.match(str(r.get("correlation_id", "")))]
        self.check(not bad_corr, f"{leg}: correlation id format sha256-hex on every record"
                   if not bad_corr else
                   f"{leg}: correlation id format violation (raw runtime id leaked?) "
                   f"on kinds {bad_corr}")
        decisions = [r for r in recs if r.get("kind") == "permission_decision"]
        claims = [r for r in recs if r.get("kind") == "relay_claim"]
        replays = [r for r in recs if r.get("kind") == "replay_returned"]
        dec_by_corr = {}
        dup = False
        for r in decisions:
            dup = dup or r.get("correlation_id") in dec_by_corr
            dec_by_corr[r.get("correlation_id")] = r
        self.check(not dup, f"{leg}: decision correlation ids unique"
                   if not dup else f"{leg}: DUPLICATE decision correlation ids")
        claim_by_corr = {r.get("correlation_id"): r for r in claims}
        bij = (len(claims) == len(claim_by_corr)
               and set(claim_by_corr) == set(dec_by_corr)
               and all(claim_by_corr[c].get("fingerprint") == dec_by_corr[c].get("fingerprint")
                       for c in dec_by_corr))
        self.check(bij, f"{leg}: claims ↔ decisions bijective, fingerprint-matched "
                   f"({len(decisions)} pair(s))" if bij else
                   f"{leg}: claim/decision ledger NOT bijective "
                   f"(claims={len(claims)}, decisions={len(decisions)})")
        bad_replays = [r for r in replays
                       if r.get("correlation_id") not in dec_by_corr
                       or dec_by_corr[r.get("correlation_id")].get("fingerprint")
                       != r.get("fingerprint")
                       # R10 f.4: the replayed answer must BE the recorded answer
                       or dec_by_corr[r.get("correlation_id")].get("decision")
                       != r.get("replayed_decision")]
        self.check(not bad_replays, f"{leg}: replays ({len(replays)}) all reference "
                   "recorded decisions, answers identical" if not bad_replays else
                   f"{leg}: replay without matching recorded decision/answer: {len(bad_replays)}")
        return dec_by_corr


def phase_actions(recs: list[dict], phase: str) -> list[dict]:
    return [r for r in recs if r.get("phase") == phase and r.get("kind") in ACTION_KINDS]


def expected_claude_fingerprint(phase: str, staging: Path) -> str:
    return NormalizedRequest(
        provider="claude", case=rc.CASE, phase=phase, model=rc.CLAUDE_MODEL_LABEL,
        role=rc.PHASE_ROLE[phase], kind="can_use_tool",
        payload=rc.expected_write_payload(phase, staging), correlation_id="",
    ).enrich().fingerprint


def check_claude(c: Checker, evidence_root: Path, staging: Path):
    print("== Claude leg ==")
    d = evidence_root / rc.CLAUDE_EVIDENCE
    required = [f for p in rc.CLAUDE_PHASES for f in rc.claude_files(p)]
    optional = {"auto-read_staging_snapshot_before_clean.json"}  # depends on pre-run state
    c.tracked_inventory(d, required, optional)
    recs = c.verified(d)
    c.relay_ledger(recs, "claude")

    # R9 f.4: two pre-clean snapshots are deterministic given the phase order
    for phase, want in rc.required_preclean_snapshots().items():
        snap = c.load(d, f"{phase}_staging_snapshot_before_clean.json")
        if snap is not None:
            c.check(snap == want, f"{phase}: pre-clean snapshot exactly the prior "
                    "phase's output" if snap == want else
                    f"{phase}: pre-clean snapshot {snap} != required {want}")

    decisions = [r for r in recs if r.get("kind") == "permission_decision"]
    c.check(len(decisions) == len(rc.EXPECTED_DECISIONS),
            f"exactly {len(rc.EXPECTED_DECISIONS)} permission decisions (found {len(decisions)})")
    for phase, want in rc.EXPECTED_DECISIONS:
        match = [r for r in decisions if r.get("phase") == phase]
        if len(match) != 1:
            c.fail(f"{phase}: expected 1 decision, found {len(match)}")
            continue
        rec = match[0]
        if rec.get("fingerprint") != expected_claude_fingerprint(phase, staging):
            c.fail(f"{phase}: fingerprint mismatch — the model issued a different request "
                   "than the manifest describes")
        elif rec.get("decision") != want:
            c.fail(f"{phase}: decision {rec.get('decision')!r} != {want!r}")
        elif (rec.get("annotations") or {}).get("manifest_match") is not True:
            c.fail(f"{phase}: decided card lacked manifest_match=True annotation (R12 a.7)")
        else:
            c.ok(f"{phase}: exact-fingerprint {want} proven, card manifest-matched")
    for phase in ("verdict", "resume", "auto-read"):
        n = len([r for r in decisions if r.get("phase") == phase])
        c.check(n == 0, f"{phase}: zero permission decisions" if n == 0
                else f"{phase}: {n} permission decisions (expected 0)")
    for phase in ("verdict", "resume"):
        n = len(phase_actions(recs, phase))
        c.check(n == 0, f"{phase}: zero native actions" if n == 0
                else f"{phase}: {n} native action records (expected 0)")

    # auto-read: positive completion proof (GO clarification 2)
    hooked = [r for r in phase_actions(recs, "auto-read") if r.get("kind") == "tool_completed"
              and (r.get("annotations") or {}).get("tool") == rc.AUTO_READ_TOOL]
    brief = str(rc.brief_path(staging).resolve())
    c.check(len(hooked) == 1 and (hooked[0].get("annotations") or {}).get("resolved_path") == brief,
            "auto-read: exactly one hook-confirmed Read completion of the brief")
    obs = c.load(d, "auto-read_observation.json")
    if obs is not None:
        tu = obs.get("tool_use") or {}
        good = (obs.get("hook_confirmed") is True
                and tu.get("name") == rc.AUTO_READ_TOOL
                and Path(str(obs.get("path", ""))).resolve() == rc.brief_path(staging).resolve()
                and obs.get("tool_result_error") is False
                and obs.get("permission_decisions") == 0)
        c.check(good, "auto-read: observation evidences start-to-completion, zero cards")
        # R10 f.2: tracked observation must carry the hashed id ONLY
        c.check("id" not in tu and bool(HEX64.match(str(tu.get("id_sha256", "")))),
                "auto-read: observation carries hashed tool-use id, no raw id")
    reply = c.load(d, "auto-read_reply.txt")
    if reply is not None:
        c.check(rc.BRIEF_MARKER in reply, "auto-read: model reply quotes the brief marker")

    # approval side effects
    done_by_phase = {p: [r for r in phase_actions(recs, p) if r.get("kind") == "tool_completed"
                         and (r.get("annotations") or {}).get("tool") == "Write"]
                     for p, _ in rc.EXPECTED_DECISIONS}
    c.check(len(done_by_phase["approval-allow"]) == 1,
            "approval-allow: approved Write hook-confirmed executed")
    c.check(len(done_by_phase["approval-deny"]) == 0,
            "approval-deny: denied Write never executed")
    snap = c.load(d, "approval-allow_staging_snapshot.json")
    if snap is not None:
        c.check(snap.get(rc.APPROVED_NAME) == sha256_text(rc.WRITE_CONTENT),
                "approval-allow snapshot: approved.txt exact content hash")
    snap2 = c.load(d, "approval-deny_staging_snapshot.json")
    if snap2 is not None:
        c.check(rc.DENIED_NAME not in snap2,
                "approval-deny snapshot: denied.txt absent")
    c.check(not (staging / rc.DENIED_NAME).exists(),
            "staging: denied.txt does not exist after the run")

    # per-phase attestations (labels are binding — GO clarification 1)
    for phase in rc.CLAUDE_PHASES:
        billing = c.load(d, f"{phase}_billing_evidence.json")
        if billing is not None:
            c.check(billing.get("claim") == rc.BILLING_CLAIM and billing.get("exit_code") == 0
                    and billing.get("auth_method") == "claude.ai"
                    and billing.get("api_provider") == "firstParty",
                    f"{phase}: billing positive-evidence (claude.ai firstParty, claim exact)")
        env = c.load(d, f"{phase}_env_attestation.json")
        if env is not None:
            c.check(env.get("policy") == "allowlist", f"{phase}: env policy allowlist")
        att = c.load(d, f"{phase}_safety_attestation.json")
        if att is not None:
            c.check(att.get("profile_label") == rc.PROFILE_LABEL
                    and att.get("native_tools") == list(rc.PHASE_TOOLS[phase]),
                    f"{phase}: controlled spike profile labeled, tool set exact")
        shadow = c.load(d, f"{phase}_shadow_warnings.json")
        if shadow is not None:
            c.check(shadow == [], f"{phase}: no shadow warnings")

    # verdict + session continuity
    verdict = c.load(d, "verdict_result.json")
    sid = c.read_state(d, "claude_session_id")
    if verdict is not None:
        if verdict.get("claim_id") != rc.CLAIM_ID or verdict.get("verdict") not in rc.VERDICT_ENUM:
            c.fail(f"claude verdict malformed: {verdict}")
        elif sid and verdict.get("session") != "sha256:" + sha256_text(sid):
            c.fail("claude verdict session hash does not match persisted session id")
        else:
            c.ok(f"claude verdict valid ({verdict.get('verdict')} on C1), session bound")
    reply = c.load(d, "resume_reply.txt")
    if reply is not None:
        c.check(reply.strip() == rc.CLAIM_ID, "claude resume reply exact")
    cont = c.load(d, "resume_continuity.json")
    if cont is not None:
        c.check(cont.get("equal") is True and bool(sid)
                and cont.get("persisted") == "sha256:" + sha256_text(sid),
                "claude resume continuity: same session id")


def check_codex(c: Checker, evidence_root: Path):
    print("== Codex leg ==")
    d = evidence_root / rc.CODEX_EVIDENCE
    required = [f for p in rc.CODEX_PHASES for f in rc.codex_files(p)]
    c.tracked_inventory(d, required, set())
    recs = c.verified(d)
    dec_by_corr = c.relay_ledger(recs, "codex")

    # R9 f.4: the dynamic tool call MUST have left a wire trace — an empty or
    # missing log can no longer pass on trivial bijection
    tool_calls = [r for r in recs if r.get("kind") == "server_request"
                  and r.get("request_kind") == "item/tool/call"]
    by_phase = {p: [r for r in tool_calls if r.get("phase") == p] for p in rc.CODEX_PHASES}
    c.check(len(by_phase["verdict"]) == 1 and len(by_phase["resume"]) == 0,
            "codex: exactly one item/tool/call server request, in the verdict phase")

    for phase in rc.CODEX_PHASES:
        billing = c.load(d, f"{phase}_billing_evidence.json")
        if billing is not None:
            c.check(billing.get("account_type") == "chatgpt"
                    and billing.get("claim") == rc.BILLING_CLAIM,
                    f"{phase}: billing evidence chatgpt subscription, claim exact")
        eff_name = "thread_start_effective.json" if phase == "verdict" \
            else "thread_resume_effective.json"
        eff = c.load(d, eff_name)
        if eff is not None:
            # incident-001 / R12 a.6: strings validated as echoed strings, the
            # sandbox validated as the schema-shaped EFFECTIVE object
            bad = {k: eff.get(k) for k, v in rc.EFFECTIVE_ECHO_STRINGS.items()
                   if eff.get(k) != v}
            c.check(not bad, f"{phase}: effective approval config fail-closed" if not bad
                    else f"{phase}: effective config mismatch {bad}")
            c.check(rc.sandbox_effective_ok(eff.get("sandbox")),
                    f"{phase}: effective sandbox readOnly without network"
                    if rc.sandbox_effective_ok(eff.get("sandbox")) else
                    f"{phase}: effective sandbox NOT strict: {eff.get('sandbox')!r}")
            c.check(eff.get("modelProvider") in rc.ALLOWED_MODEL_PROVIDERS,
                    f"{phase}: modelProvider {eff.get('modelProvider')!r} in pinned "
                    f"first-party allowlist (R8 P0-3)")
        att = c.load(d, f"{phase}_safety_attestation.json")
        if att is not None:
            c.check(att.get("problems") == [] and att.get("profile_label") == rc.PROFILE_LABEL,
                    f"{phase}: SafetyAttestation clean and profile labeled")
        health = c.load(d, f"{phase}_client_health.json")
        if health is not None:
            c.check(health.get("fatal") == [] and health.get("unknown_requests") == []
                    and health.get("declined_non_approvals") == [],
                    f"{phase}: client healthy, no unknown/non-approval requests (R8 f.7)")
        c.raw_ref_check(d, f"{phase}_events_ref.json", "events_sha256",
                        f"{phase}_events.json")

    vpath = c.load(d, "verdict_path.json")
    verdict = c.load(d, "verdict_result.json")
    tid = c.read_state(d, "codex_thread_id")
    if vpath is not None:
        c.check(vpath.get("path") == "dynamicToolCall", "codex verdict via dynamicToolCall only")
        c.check(bool(vpath.get("call_args_sha256"))
                and vpath.get("call_args_sha256") == vpath.get("item_args_sha256")
                and "ids_equal" in vpath,
                "codex verdict: call and completed item joined on arguments "
                "(schema-required both sides; ids recorded as observation — R9 f.3)")
        if verdict is not None:
            args = {k: verdict[k] for k in ("claim_id", "verdict", "argument") if k in verdict}
            c.check(vpath.get("args_sha256") == sha256_text(canonical(args)),
                    "codex verdict content hash-bound to the submitted tool arguments (R8 f.5)")
            # R10 f.3: bind the verdict to the HASH-CHAINED wire record, not
            # merely to editable evidence files — read the chained item/tool/call
            # record's raw payload, verify its hash, and compare its arguments
            if len(by_phase["verdict"]) == 1:
                rec = by_phase["verdict"][0]
                raw_path = d / "raw" / str(rec.get("payload_raw_ref") or "")
                if not raw_path.is_file():
                    c.fail("verdict not chained: raw payload of the item/tool/call "
                           "record is missing")
                else:
                    raw_text = raw_path.read_text()
                    payload = json.loads(raw_text)
                    wire_args = payload.get("arguments")
                    if isinstance(wire_args, str):
                        wire_args = json.loads(wire_args)
                    c.check(sha256_text(raw_text) == rec.get("payload_sha256")
                            and canonical(wire_args) == canonical(args),
                            "codex verdict bound to the chained wire record "
                            "(raw payload hash + arguments exact)")
    if verdict is not None:
        good = (verdict.get("claim_id") == rc.CLAIM_ID
                and verdict.get("verdict") in rc.VERDICT_ENUM
                and bool(tid) and verdict.get("thread") == "sha256:" + sha256_text(tid))
        c.check(good, f"codex verdict valid ({verdict.get('verdict')} on C1), thread bound")
    reply = c.load(d, "resume_reply.txt")
    if reply is not None:
        c.check(reply.strip() == rc.CLAIM_ID, "codex resume reply exact")

    # exactly-once against the WIRE (R9 P0): every relayable server request is
    # either the single decided ask or an accounted replay of it — no phantom
    # decisions, no unanswered asks, uniqueness guaranteed by relay_ledger above
    asked: dict[str, int] = {}
    for r in recs:
        if r.get("kind") == "server_request" and r.get("request_kind") in rc.RELAYABLE_METHODS:
            asked[r.get("correlation_id")] = asked.get(r.get("correlation_id"), 0) + 1
    replays: dict[str, int] = {}
    for r in recs:
        if r.get("kind") == "replay_returned":
            replays[r.get("correlation_id")] = replays.get(r.get("correlation_id"), 0) + 1
    offsurface = [r.get("request_kind") for r in recs if r.get("kind") == "permission_decision"
                  and r.get("request_kind") not in rc.RELAYABLE_METHODS]
    wire_ok = (set(asked) == set(dec_by_corr) and not offsurface
               and all(n == 1 + replays.get(corr, 0) for corr, n in asked.items()))
    c.check(wire_ok,
            f"native approval exactly-once vs wire: {len(asked)} relayable key(s), "
            f"each decided once, {sum(replays.values())} replay(s) accounted"
            if wire_ok else
            f"relay/wire mismatch: asked={asked} decided={sorted(dec_by_corr)} "
            f"replays={replays} off-surface={offsurface}")
    unknowns = [r.get("request_kind") for r in recs
                if r.get("kind") in ("unknown_request_declined", "non_approval_declined")]
    c.check(not unknowns, "no unknown/non-approval server requests in the log"
            if not unknowns else f"unknown/non-approval requests occurred: {unknowns}")


def run(evidence_root: Path | None = None, staging: Path | None = None) -> list[str]:
    evidence_root = evidence_root or Path(os.environ.get("DIALEKTIKE_EVIDENCE_ROOT",
                                                         rc.EVIDENCE_ROOT))
    staging = staging or Path(os.environ.get("DIALEKTIKE_STAGING_ROOT", rc.STAGING))
    c = Checker()
    claude_dir = evidence_root / rc.CLAUDE_EVIDENCE
    codex_dir = evidence_root / rc.CODEX_EVIDENCE
    if not claude_dir.exists() or not codex_dir.exists():
        c.fail("evidence directories missing — the run did not happen or was moved")
    else:
        check_claude(c, evidence_root, staging)
        check_codex(c, evidence_root)
    return c.failures


def main():
    failures = run()
    print()
    if failures:
        print(f"VERIFICATION FAILED — {len(failures)} problem(s)")
        sys.exit(1)
    print(f"VERIFICATION PASSED — full manifest contract satisfied "
          f"({len(rc.CLAUDE_PHASES)} Claude + {len(rc.CODEX_PHASES)} Codex phases)")


if __name__ == "__main__":
    main()
