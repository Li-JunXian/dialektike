"""Dialektikḗ Capability Broker — chain log, fingerprints, manifest approvals.

Semantics updated for governance 0002/0003 (v2.4): live presentation of native
permission requests moved to the provider-neutral PermissionRelay in
core/relay.py — BOTH adapters submit normalized native requests there. This
module keeps the primitives the relay builds on (canonical/sha256, the
hash-chained ChainedLog) plus the `manifest` verb (finite, exact, single-use
pre-approved action lists) for alpha. The Broker's `ask` mode and
ActionRequest card remain for manifest-mode tooling and tests; spike v2.4's
legs do not call Broker.decide.

Axioms (Live's rulings; governance 0001, as re-scoped by 0002):
  - Fail closed: unknown mode, presenter error, invalid presenter output, malformed
    request, path escape → DENY (and the denial is logged).
  - Exactly once: each NATIVE runtime approval request surfaces to Live one time,
    verbatim, enriched only with deterministic data; natively auto-permitted
    actions are audit-logged, never re-prompted. No LLM decides/asks.
  - Verbs: allow once · deny · pre-approved exact finite manifest (single-use,
    consumption persisted via the decision log itself).

Privacy (R6): git-tracked decision records carry HASHES of tool inputs, never the
inputs themselves; full payloads are written to a git-ignored raw store and shown
in full on the card at decision time.

Tamper-evidence threat model (R5, honest claim): the hash chain detects ACCIDENTAL
OR UNCOORDINATED modification. It does not defeat adversarial local rewriting.
Independent anchoring: anchor_receipt() first re-verifies the chain, then prints
the head hash for Live to paste into the next cross-model audit round.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal

GENESIS = "dialektike-genesis"

Decision = Literal["allow", "deny"]


class ChainVerificationError(Exception):
    """The decision log's hash chain failed verification — nothing derived
    from it (manifest consumption, decision proofs, anchors) may be trusted."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass
class ActionRequest:
    """One model-issued tool request, verbatim, plus deterministic enrichment."""

    case: str
    phase: str
    model: str
    role: str
    tool: str
    tool_input: dict
    tool_use_id: str | None = None
    content_sha256: str = ""
    fingerprint: str = ""
    path_confined: bool | None = None
    resolved_path: str | None = None

    def enrich(self, staging_root: Path | None) -> "ActionRequest":
        self.content_sha256 = sha256_text(canonical(self.tool_input))
        self.fingerprint = sha256_text(canonical({
            "case": self.case, "phase": self.phase, "model": self.model,
            "role": self.role, "tool": self.tool, "input": self.tool_input,
        }))
        raw = self.tool_input.get("path") or self.tool_input.get("file_path")
        if raw is not None and staging_root is not None:
            root = staging_root.resolve()
            target = Path(str(raw)).resolve() if Path(str(raw)).is_absolute() \
                else (root / str(raw)).resolve()
            self.resolved_path = str(target)
            self.path_confined = target == root or target.is_relative_to(root)
        return self

    def tracked_record(self) -> dict:
        """The git-trackable projection: hashes in, payload out (R6 privacy)."""
        rec = asdict(self)
        del rec["tool_input"]
        return rec


def render_card(req: ActionRequest) -> str:
    """Full-content permission card shown to Live at decision time. Never truncated."""
    body = canonical(req.tool_input)
    lines = [
        "┌─ PERMISSION CARD ─ Dialektikḗ ───────────────────────",
        f"│ case/phase:   {req.case} / {req.phase}",
        f"│ model:        {req.model}   role: {req.role}",
        f"│ action:       {req.tool}   (tool_use_id: {req.tool_use_id})",
        f"│ input sha256: {req.content_sha256}",
        f"│ fingerprint:  {req.fingerprint}",
    ]
    if req.path_confined is not None:
        verdict = "CONFINED to staging" if req.path_confined else "⚠ OUTSIDE STAGING"
        lines.append(f"│ path:         {req.resolved_path} — {verdict}")
    lines.append("└──────────────────────────────────────────────────────")
    return f"--- full request content ({len(body)} chars) ---\n{body}\n" + "\n".join(lines)


class ChainedLog:
    """Append-only JSONL log; records hash-chain to their predecessor.

    Appends hold an exclusive flock across read-head/write and fsync before
    unlock (R6: crash-atomicity for cooperative writers)."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash_locked(self, f) -> str:
        f.seek(0)
        last = None
        for line in f:
            if line.strip():
                last = json.loads(line)
        return last["hash"] if last else GENESIS

    def _write_locked(self, f, record: dict) -> dict:
        record["prev_hash"] = self._last_hash_locked(f)
        record["hash"] = sha256_text(canonical(record))
        f.seek(0, 2)
        f.write(canonical(record) + "\n")
        f.flush()
        os.fsync(f.fileno())
        return record

    def append(self, record: dict) -> dict:
        record = dict(record)
        with self.path.open("a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                return self._write_locked(f, record)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def append_unique(self, record: dict, kind: str, correlation_id: str
                      ) -> tuple[bool, dict]:
        """Atomic claim (R9 P0): verify the chain, scan for an existing record
        with this kind+correlation_id, and append ONLY if absent — all under
        ONE exclusive flock, so no interleaving writer can claim the same key.
        Returns (appended, record) — the existing record when appended=False."""
        record = dict(record)
        with self.path.open("a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                lines = f.readlines()
                ok, n, _ = ChainedLog._verify_lines(lines)
                if not ok:
                    raise ChainVerificationError(
                        f"chain broken at record {n} in {self.path} — refusing to claim")
                for line in lines:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    if rec.get("kind") == kind and rec.get("correlation_id") == correlation_id:
                        return False, rec
                return True, self._write_locked(f, record)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open() as f:
            return [json.loads(line) for line in f if line.strip()]

    def verified_records(self) -> list[dict]:
        """Read the log under the same lock appends take, verify the whole
        chain, and only then return the records (R7: nothing may be derived
        from an unverified chain). Raises ChainVerificationError."""
        if not self.path.exists():
            return []
        with self.path.open("a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                lines = f.readlines()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        ok, n, _ = ChainedLog._verify_lines(lines)
        if not ok:
            raise ChainVerificationError(
                f"chain broken at record {n} in {self.path} — refusing to derive from it")
        return [json.loads(line) for line in lines if line.strip()]

    def anchor_receipt(self) -> str:
        """Verify chain and read the head in ONE locked pass (R7: the v2.2
        verify-then-read was two unlocked operations — racy)."""
        if not self.path.exists():
            return "ANCHOR RECEIPT — empty log (no decisions recorded)"
        with self.path.open("a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                lines = f.readlines()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        ok, n, head = ChainedLog._verify_lines(lines)
        if not ok:
            return (f"⚠ CHAIN VERIFICATION FAILED at record {n} in {self.path.name} — "
                    "DO NOT trust or anchor this log; investigate before proceeding")
        if n == 0:
            return "ANCHOR RECEIPT — empty log (no decisions recorded)"
        return (f"ANCHOR RECEIPT — {self.path.name}: {n} records verified, head {head}\n"
                f"  (paste this line to the other model in the next audit round)")

    @staticmethod
    def _verify_lines(lines) -> tuple[bool, int, str]:
        """Returns (ok, records_verified_or_first_bad_index, head_hash)."""
        prev, n = GENESIS, 0
        for line in lines:
            if not line.strip():
                continue
            rec = json.loads(line)
            claimed = rec.pop("hash", None)
            if claimed is None or rec.get("prev_hash") != prev \
                    or sha256_text(canonical(rec)) != claimed:
                return False, n, prev
            prev, n = claimed, n + 1
        return True, n, prev

    @staticmethod
    def verify(path: Path) -> tuple[bool, int]:
        with path.open() as f:
            ok, n, _ = ChainedLog._verify_lines(f)
        return ok, n


Presenter = Callable[[ActionRequest, str], Decision]


def terminal_presenter(req: ActionRequest, card: str) -> Decision:
    print(card)
    answer = input("dialektike> allow once / deny [a/d]: ").strip().lower()
    return "allow" if answer in ("a", "allow") else "deny"


CONSUMED_REASON = "consumed pre-approved single-use manifest entry"


@dataclass
class Manifest:
    """Finite, exact, SINGLE-USE pre-approved action list.

    Consumption is persistent (R6): on load, fingerprints already consumed
    according to the decision log are subtracted, so a restart cannot re-arm
    an already-used approval. The decision log is the single source of truth,
    and it is chain-VERIFIED before anything is derived from it (R7: a
    corrupted log must not re-arm a consumed approval — fail closed instead)."""

    entries: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path, log: "ChainedLog | None" = None) -> "Manifest":
        data = json.loads(path.read_text())
        entries = [e["fingerprint"] for e in data["approved_actions"]]
        if log is not None:
            for rec in log.verified_records():  # raises ChainVerificationError
                if rec.get("reason") == CONSUMED_REASON and rec.get("fingerprint") in entries:
                    entries.remove(rec["fingerprint"])
        return cls(entries)

    def consume(self, req: ActionRequest) -> bool:
        if req.fingerprint in self.entries:
            self.entries.remove(req.fingerprint)
            return True
        return False


class Broker:
    """The single gate. mode ∈ {'ask', 'manifest'}; anything else fails closed."""

    def __init__(self, mode: str, log: ChainedLog, staging_root: Path,
                 presenter: Presenter = terminal_presenter,
                 manifest: Manifest | None = None,
                 raw_dir: Path | None = None):
        self.mode = mode
        self.log = log
        self.staging_root = staging_root
        self.presenter = presenter
        self.manifest = manifest
        self.raw_dir = raw_dir

    def _stash_raw(self, req: ActionRequest) -> str | None:
        if self.raw_dir is None:
            return None
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        name = f"input-{req.fingerprint[:24]}.json"
        (self.raw_dir / name).write_text(canonical(req.tool_input))
        return name

    def decide(self, req: ActionRequest) -> tuple[Decision, str]:
        decision: Decision = "deny"
        reason = "fail-closed default"
        raw_ref = None
        try:
            req.enrich(self.staging_root)  # inside the boundary (R6: malformed input → logged denial)
            raw_ref = self._stash_raw(req)
            if req.path_confined is False:
                reason = "path escapes staging (deterministic check)"
            elif self.mode == "ask":
                result = self.presenter(req, render_card(req))
                if result == "allow":
                    decision, reason = "allow", "Live decided at presenter"
                elif result == "deny":
                    reason = "Live decided at presenter"
                else:
                    reason = f"presenter returned invalid decision {result!r} — fail closed"
            elif self.mode == "manifest":
                if self.manifest is not None and self.manifest.consume(req):
                    decision, reason = "allow", CONSUMED_REASON
                else:
                    reason = "not in (or already consumed from) manifest"
            else:
                reason = f"unknown broker mode {self.mode!r} — fail closed"
        except Exception as exc:
            decision, reason = "deny", f"broker exception — fail closed ({exc})"
        self.log.append({
            "ts": time.time(), "kind": "permission_decision",
            **req.tracked_record(), "input_raw_ref": raw_ref,
            "decision": decision, "reason": reason,
        })
        return decision, reason
