"""Broker + evidence invariants (reproducible, non-model). R9 f.6: these were
scratchpad-only in v2.3/v2.4 validation; committed so any auditor can rerun.

Run: ./venv/bin/python tests/broker_invariants.py   (exit 0 = all hold)
"""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.broker import (ActionRequest, Broker, ChainedLog, ChainVerificationError,  # noqa: E402
                         Manifest, CONSUMED_REASON)
from core.evidence import EvidenceDir, safe_name  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="dialektike-broker-inv-"))
staging = tmp / "staging"; staging.mkdir()
raw = tmp / "raw"
checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(("OK  " if cond else "FAIL"), name)


def req(phase="p1", tool="mcp__dialektike__read_file", tin=None):
    return ActionRequest(case="t", phase=phase, model="claude (haiku)", role="auditor",
                         tool=tool, tool_input=tin or {"path": "x.txt"})


# 1. fail-closed basics
log = ChainedLog(tmp / "d1.jsonl")
b = Broker(mode="bogus", log=log, staging_root=staging, raw_dir=raw)
d, r = b.decide(req())
check("unknown mode denies", d == "deny" and "unknown broker mode" in r)
b = Broker(mode="ask", log=log, staging_root=staging, raw_dir=raw,
           presenter=lambda q, c: "maybe")
d, r = b.decide(req())
check("invalid presenter output denies", d == "deny" and "invalid decision" in r)
b = Broker(mode="ask", log=log, staging_root=staging, raw_dir=raw,
           presenter=lambda q, c: (_ for _ in ()).throw(RuntimeError("ui died")))
d, r = b.decide(req())
check("presenter exception denies", d == "deny" and "fail closed" in r)
bad = ActionRequest(case="t", phase="p1", model="m", role="auditor",
                    tool="t", tool_input={"path": object()})  # unserializable
d, r = Broker(mode="ask", log=log, staging_root=staging, raw_dir=raw).decide(bad)
check("malformed input denies + logged", d == "deny")
d, r = Broker(mode="ask", log=log, staging_root=staging, raw_dir=raw,
              presenter=lambda q, c: "allow").decide(req(tin={"path": "../escape.txt"}))
check("path escape denies before presenter", d == "deny" and "escapes staging" in r)

# 2. privacy split
allow_b = Broker(mode="ask", log=log, staging_root=staging, raw_dir=raw,
                 presenter=lambda q, c: "allow")
d, _ = allow_b.decide(req(phase="p2"))
recs = log.records()
check("tracked record carries no tool_input",
      all("tool_input" not in r for r in recs))
check("raw payload stashed", any(raw.glob("input-*.json")))

# 3. manifest single-use + persistence + chain-verified load
fp = req(phase="p3").enrich(staging).fingerprint
mpath = tmp / "m.json"
mpath.write_text(json.dumps({"approved_actions": [{"fingerprint": fp}]}))
log2 = ChainedLog(tmp / "d2.jsonl")
man = Manifest.load(mpath, log2)
mb = Broker(mode="manifest", log=log2, staging_root=staging, manifest=man, raw_dir=raw)
d1, r1 = mb.decide(req(phase="p3"))
d2, r2 = mb.decide(req(phase="p3"))
check("manifest single-use", d1 == "allow" and r1 == CONSUMED_REASON and d2 == "deny")
man2 = Manifest.load(mpath, log2)  # simulated restart
d3, _ = Broker(mode="manifest", log=log2, staging_root=staging,
               manifest=man2, raw_dir=raw).decide(req(phase="p3"))
check("consumption persists across restart", d3 == "deny" and man2.entries == [])

# corrupt the log -> load must fail closed, not re-arm
lines = (tmp / "d2.jsonl").read_text().splitlines()
recj = json.loads(lines[0]); recj["reason"] = "tampered"
lines[0] = json.dumps(recj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
(tmp / "d2.jsonl").write_text("\n".join(lines) + "\n")
try:
    Manifest.load(mpath, log2)
    check("corrupted chain: Manifest.load fails closed", False)
except ChainVerificationError:
    check("corrupted chain: Manifest.load fails closed", True)
try:
    log2.verified_records()
    check("verified_records raises on corruption", False)
except ChainVerificationError:
    check("verified_records raises on corruption", True)
check("anchor refuses corrupted chain",
      "CHAIN VERIFICATION FAILED" in log2.anchor_receipt())
check("anchor OK on valid chain includes head",
      "records verified, head " in log.anchor_receipt())

# append_unique (R9 P0 primitive): atomic claim under one flock
log3 = ChainedLog(tmp / "d3.jsonl")
a1, r1 = log3.append_unique({"kind": "relay_claim", "correlation_id": "k1", "x": 1},
                            "relay_claim", "k1")
a2, r2 = log3.append_unique({"kind": "relay_claim", "correlation_id": "k1", "x": 2},
                            "relay_claim", "k1")
check("append_unique claims once, returns existing after",
      a1 is True and a2 is False and r2.get("x") == 1)
try:
    lines3 = (tmp / "d3.jsonl").read_text().splitlines()
    j = json.loads(lines3[0]); j["x"] = 9
    (tmp / "d3.jsonl").write_text(
        json.dumps(j, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    log3.append_unique({"kind": "relay_claim", "correlation_id": "k2"}, "relay_claim", "k2")
    check("append_unique refuses corrupted chain", False)
except ChainVerificationError:
    check("append_unique refuses corrupted chain", True)

# 4. evidence filename sanitization (R7: untrusted ids)
ev = EvidenceDir(tmp / "ev", "leg")
h = ev.save_raw("../../../evil.json", {"x": 1})
outside = (tmp / "ev" / "evil.json", tmp.parent / "evil.json", Path("/tmp/evil.json"))
check("hostile raw name confined", not any(p.exists() for p in outside)
      and any((tmp / "ev" / "leg" / "raw").glob("*evil*")))
check("safe_name strips separators/dots",
      "/" not in safe_name("a/../b") and not safe_name("...x").startswith("."))
p = ev.save_json("../../trick.json", {"y": 2})
check("hostile tracked name confined",
      p.parent == (tmp / "ev" / "leg") and not (tmp / "trick.json").exists())

fails = [n for n, okk in checks if not okk]
print()
print(f"{len(checks) - len(fails)}/{len(checks)} invariants hold")
sys.exit(1 if fails else 0)
