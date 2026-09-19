"""PermissionRelay invariants (reproducible, non-model). R9 f.6: committed so
any auditor can rerun; extended for the R9 P0 durable exactly-once semantics.

Run: ./venv/bin/python tests/relay_invariants.py   (exit 0 = all hold)
"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.broker import ChainedLog, canonical, sha256_text  # noqa: E402
from core.relay import (NormalizedRequest, PermissionRelay,  # noqa: E402
                        RelayIntegrityError, path_annotations)

FAILS = []


def check(name, cond):
    print(("OK    " if cond else "FAIL  ") + name)
    if not cond:
        FAILS.append(name)


def req(payload=None, corr="corr-1"):
    return NormalizedRequest(provider="test", case="c", phase="p", model="m",
                             role="r", kind="native/ask", payload=payload or {"x": 1},
                             correlation_id=corr, annotations={"a": "b"})


def forbidden_presenter(q, c):
    raise AssertionError("presenter invoked when it must not be")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    log = ChainedLog(root / "log.jsonl")
    raw = root / "raw"

    # 1-2: presenter answers map exactly; anything else fails closed
    r = PermissionRelay(log, lambda q, c: "allow", raw)
    check("allow passes through", r.relay(req())[0] == "allow")
    r = PermissionRelay(log, lambda q, c: "ALLOW!!", raw)
    d, reason = r.relay(req(corr="corr-2"))
    check("invalid presenter output → deny", d == "deny" and "invalid" in reason)

    # 3: presenter exception → deny, logged
    def boom(q, c):
        raise RuntimeError("ui crashed")
    d, reason = PermissionRelay(log, boom, raw).relay(req(corr="corr-3"))
    check("presenter exception → deny", d == "deny" and "fail closed" in reason)

    # 4: malformed (non-serializable) payload → deny, no card, still claimed
    d, reason = PermissionRelay(log, forbidden_presenter, raw).relay(
        req(payload={"bad": object()}, corr="corr-4"))
    check("non-canonicalizable payload → deny without a card",
          d == "deny" and "malformed" in reason)

    # 5: audit kind restriction — cannot masquerade as a decision
    try:
        PermissionRelay(log, lambda q, c: "allow", raw).audit(req(), "permission_decision")
        check("audit refuses kind permission_decision", False)
    except ValueError:
        check("audit refuses kind permission_decision", True)

    # 6: audit writes a record without ever presenting a card
    PermissionRelay(log, forbidden_presenter, raw).audit(req(corr="corr-6"), "tool_completed")
    check("audit never presents a card", True)

    # 7: durable exactly-once (R9 P0) — exact replay returns the recorded
    #    decision WITHOUT a second card
    d, reason = PermissionRelay(log, forbidden_presenter, raw).relay(req(corr="corr-1"))
    check("exact replay: recorded decision, no second card",
          d == "allow" and "replayed" in reason)
    recs = log.verified_records()
    check("replay leaves an audit trail",
          any(x["kind"] == "replay_returned" and x["correlation_id"] == "corr-1"
              for x in recs))

    # 8: same correlation, DIFFERENT fingerprint → fatal, never presented
    try:
        PermissionRelay(log, forbidden_presenter, raw).relay(
            req(payload={"x": 999}, corr="corr-1"))
        check("correlation conflict raises RelayIntegrityError", False)
    except RelayIntegrityError:
        check("correlation conflict raises RelayIntegrityError", True)
    check("conflict recorded in the chain",
          any(x["kind"] == "correlation_conflict" for x in log.verified_records()))

    # 9: claim without decision (prior attempt died mid-card) → fatal
    log2 = ChainedLog(root / "log2.jsonl")
    stale = req(corr="corr-stale").enrich()
    log2.append({"kind": "relay_claim", **stale.tracked_record(), "payload_raw_ref": None})
    try:
        PermissionRelay(log2, forbidden_presenter, raw).relay(req(corr="corr-stale"))
        check("claim without decision → RelayIntegrityError", False)
    except RelayIntegrityError:
        check("claim without decision → RelayIntegrityError", True)

    # 9b (R10 f.4): empty correlation id → refused before any card or claim
    try:
        PermissionRelay(log2, forbidden_presenter, raw).relay(req(corr=""))
        check("empty correlation id → RelayIntegrityError", False)
    except RelayIntegrityError:
        check("empty correlation id → RelayIntegrityError", True)

    # 9c (R10 f.4): multiple prior decisions for one key → conflict, not a replay
    log3 = ChainedLog(root / "log3.jsonl")
    multi = req(corr="corr-multi").enrich()
    log3.append({"kind": "relay_claim", **multi.tracked_record(), "payload_raw_ref": None})
    for _ in range(2):  # forge a corrupted ledger with two decisions
        log3.append({"kind": "permission_decision", **multi.tracked_record(),
                     "payload_raw_ref": None, "decision": "allow", "reason": "forged"})
    try:
        PermissionRelay(log3, forbidden_presenter, raw).relay(req(corr="corr-multi"))
        check("multiple prior decisions → RelayIntegrityError", False)
    except RelayIntegrityError:
        check("multiple prior decisions → RelayIntegrityError", True)

    # 10: ledger shape — every decision has a fingerprint-matching claim
    recs = log.verified_records()
    dec = [x for x in recs if x["kind"] == "permission_decision"]
    claims = {x["correlation_id"]: x for x in recs if x["kind"] == "relay_claim"}
    check("claims ↔ decisions bijective, fingerprint-matched",
          {x["correlation_id"] for x in dec} == set(claims)
          and all(claims[x["correlation_id"]]["fingerprint"] == x["fingerprint"]
                  for x in dec))
    check("no verbatim payload in tracked records",
          all("payload" not in x for x in recs))
    check("request_kind separated from record kind",
          all(x.get("request_kind") == "native/ask" for x in dec))
    check("annotations preserved verbatim",
          all(x.get("annotations") == {"a": "b"} for x in dec))

    # 11: raw stash holds the canonical payload; tracked record references it
    ok_rec = [x for x in dec if x["correlation_id"] == "corr-1"][0]
    raw_file = raw / ok_rec["payload_raw_ref"]
    check("raw stash exists with canonical payload",
          raw_file.exists() and raw_file.read_text() == canonical({"x": 1}))
    check("payload hash matches stash",
          ok_rec["payload_sha256"] == sha256_text(raw_file.read_text()))

    # 12: one relay call appends exactly claim + decision
    before = len(log.verified_records())
    PermissionRelay(log, lambda q, c: "deny", raw).relay(req(corr="corr-12"))
    check("one relay call appends exactly claim + decision",
          len(log.verified_records()) == before + 2)

    # 13: a bound-method presenter receives its lifecycle hook only after the
    #     decision append; this is how the Codex reader wrapper delegates to
    #     the trusted GUI presenter.
    class HookOwner:
        def __init__(self, chained_log):
            self.log = chained_log
            self.notified_after_append = False

        def present(self, q, c):
            return "deny"

        def decision_recorded(self, q, decision):
            self.notified_after_append = (
                self.log.verified_records()[-1]["kind"]
                == "permission_decision"
            )

    hook_owner = HookOwner(log)
    PermissionRelay(log, hook_owner.present, raw).relay(
        req(corr="corr-hook")
    )
    check(
        "presenter notified only after durable decision append",
        hook_owner.notified_after_append,
    )

    # 14: fingerprint determinism + payload sensitivity
    a = req().enrich().fingerprint
    b = req().enrich().fingerprint
    c2 = req(payload={"x": 2}).enrich().fingerprint
    check("fingerprint deterministic and payload-sensitive", a == b and a != c2)

    # 15: path annotations verdicts
    inside = path_annotations({"file_path": str(root / "raw" / "f.txt")}, root)
    outside = path_annotations({"file_path": "/etc/hosts"}, root)
    check("path annotations confine correctly",
          inside["path_confined"] is True and outside["path_confined"] is False)

print()
if FAILS:
    print(f"RELAY INVARIANTS FAILED: {len(FAILS)}")
    sys.exit(1)
print("RELAY INVARIANTS — all hold")
