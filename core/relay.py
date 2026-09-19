"""Dialektikḗ PermissionRelay — the ONE provider-neutral permission surface.

Governance 0002 (native parity): adapters forward exactly the permission
requests their native runtime raises — once, verbatim, enriched only with
deterministic data — and map the relay's answer back onto their own wire.
Governance 0003: every adapter (and later the GUI) uses THIS relay; adapters
retain only wire-specific response mapping. The spike-era per-adapter prompt
UIs (broker terminal presenter used only by the Claude leg, `_ask_live` in the
Codex leg) are superseded by this module.

Division of labour with core/broker.py: the relay owns presentation,
exactly-once logging, and audit records; the Broker's `manifest` verb
(finite pre-approved action lists) remains a policy layer for alpha and is
not used by spike v2.4 (mode is Live-at-terminal throughout).

Privacy contract (R5/R6): the verbatim payload goes ONLY to the git-ignored
raw store and onto the card at decision time. Tracked records carry hashes.
Adapters MUST hash any runtime identifier (session/thread/turn/item ids)
before placing it in `annotations` — annotations are written to the tracked
log verbatim (R8 finding 6).
"""

from __future__ import annotations

import secrets
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal

try:
    import termios
except ImportError:  # non-POSIX platform: stdin flush becomes a no-op
    termios = None

from core.broker import ChainedLog, canonical, sha256_text

Decision = Literal["allow", "deny"]

# Audit kinds adapters may log via audit(). NEVER "permission_decision" — an
# audit record must not be able to masquerade as a relayed decision.
AUDIT_KINDS = {
    "tool_completed",            # native runtime executed a tool (hook-observed)
    "tool_failed",               # native runtime reported a tool failure
    "native_auto_permitted",     # action the native runtime permitted with no ask
    "server_request",            # verbatim server→client request (Codex wire)
    "non_approval_declined",     # non-approval interactive request, declined fail-closed
    "unknown_request_declined",  # unknown method, declined fail-closed on the wire
}

# Kinds written ONLY by the relay itself (R9 P0 — durable exactly-once):
#   relay_claim        — atomic claim of a correlation key BEFORE presentation
#   replay_returned    — exact retransmission answered from the recorded decision
#   correlation_conflict — same correlation key, different fingerprint (fatal)
RELAY_INTERNAL_KINDS = {"relay_claim", "replay_returned", "correlation_conflict"}


class RelayIntegrityError(Exception):
    """The exactly-once invariant cannot be preserved for this request —
    the phase must fail; the adapter must NOT answer the wire as if decided."""


@dataclass
class NormalizedRequest:
    """One native runtime event, normalized. `payload` is the VERBATIM native
    content (tool input, wire params). `annotations` are deterministic,
    adapter-computed additions (path verdicts, HASHED runtime ids) — the
    exactly-once ruling permits deterministic enrichment only."""

    provider: str            # "claude" | "codex" | future
    case: str
    phase: str
    model: str
    role: str
    kind: str                # native request kind: e.g. "can_use_tool", wire method
    payload: dict
    correlation_id: str      # deterministic join key (tool_use_id / wire request id hash)
    annotations: dict = field(default_factory=dict)
    payload_sha256: str = ""
    fingerprint: str = ""

    def enrich(self) -> "NormalizedRequest":
        self.payload_sha256 = sha256_text(canonical(self.payload))
        self.fingerprint = sha256_text(canonical({
            "provider": self.provider, "case": self.case, "phase": self.phase,
            "model": self.model, "role": self.role, "kind": self.kind,
            "payload": self.payload,
        }))
        return self

    def tracked_record(self) -> dict:
        rec = asdict(self)
        del rec["payload"]  # hashes in, payload out (R6 privacy)
        # "kind" belongs to the log record (permission_decision / audit kind);
        # the request's own kind is tracked as request_kind.
        rec["request_kind"] = rec.pop("kind")
        return rec


def path_annotations(payload_input: dict, root: Path) -> dict:
    """Deterministic path verdict for tool inputs that name a file."""
    raw = payload_input.get("path") or payload_input.get("file_path")
    if raw is None:
        return {}
    rootr = root.resolve()
    target = Path(str(raw)).resolve() if Path(str(raw)).is_absolute() \
        else (rootr / str(raw)).resolve()
    return {"resolved_path": str(target),
            "path_confined": target == rootr or target.is_relative_to(rootr)}


def sanitize_terminal(text: str) -> str:
    """Make untrusted content safe to PRINT without letting it drive the
    terminal (M1 audit finding 2): C0/C1 control characters and DEL are
    shown as visible escapes instead of being interpreted — so model output
    cannot move the cursor, clear the screen, or forge a permission card.
    Newlines and tabs pass through; content is otherwise shown faithfully."""
    out = []
    for ch in text:
        cp = ord(ch)
        if ch in ("\n", "\t"):
            out.append(ch)
        elif cp < 0x20 or cp == 0x7F or 0x80 <= cp <= 0x9F:
            out.append(f"\\x{cp:02x}")
        else:
            out.append(ch)
    return "".join(out)


def render_card(req: NormalizedRequest) -> str:
    """Full-content card. Verbatim payload, never truncated. The assembled
    card is terminal-sanitized: control characters appear as visible escapes
    (the raw stash keeps the exact bytes; the card must not let payload
    content or annotations drive Live's terminal)."""
    body = canonical(req.payload)
    lines = [
        "┌─ PERMISSION CARD ─ Dialektikḗ (native request, relayed once) ─",
        f"│ provider:     {req.provider}   model: {req.model}   role: {req.role}",
        f"│ case/phase:   {req.case} / {req.phase}",
        f"│ request kind: {req.kind}",
        f"│ payload sha:  {req.payload_sha256}",
        f"│ fingerprint:  {req.fingerprint}",
        f"│ correlation:  {req.correlation_id}",
    ]
    for key in sorted(req.annotations):
        lines.append(f"│ {key}: {req.annotations[key]}")
    lines.append(f"└─ full native request content ({len(body)} chars) ─")
    return sanitize_terminal("\n".join(lines) + "\n" + body)


Presenter = Callable[[NormalizedRequest, str], str]


def terminal_presenter(req: NormalizedRequest, card: str) -> str:
    """Live's terminal decision surface, spoof-resistant (M1 audit finding 2):
    pending stdin is drained so pre-typed or model-baited bytes cannot answer
    a card, and ALLOW requires a fresh random token printed WITH this card —
    text printed earlier (e.g. a forged card inside model output) cannot know
    it. Anything but the exact token denies (cards answered only by Live)."""
    print("\n" + card)
    token = secrets.token_hex(2)
    if termios is not None:
        try:
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except Exception:
            pass  # stdin is not a tty (dev runs): nothing buffered to drain
    answer = input(f"dialektike> type {token} to ALLOW once; anything else denies: ").strip()
    return "allow" if answer == token else "deny"


class PermissionRelay:
    """Exactly-once presentation of native permission requests, fail closed.

    relay(): one native request → one card → one logged decision, DURABLY
    idempotent per correlation key (R9 P0):
      - before any card, the correlation key is atomically CLAIMED in the
        hash-chained log (one flock: verify + scan + append);
      - an exact retransmission (same correlation_id AND same fingerprint)
        returns the recorded decision WITHOUT a second card (`replay_returned`
        audit record);
      - the same correlation key with a DIFFERENT fingerprint, or a claim with
        no recorded decision (a prior attempt died mid-card), raises
        RelayIntegrityError — the phase fails rather than guess.
    Scope note (honest claim): dedup keys on the correlation_id the adapter
    derives from the WIRE REQUEST identity. If the native runtime genuinely
    asks again (a new wire request), that presents again — the native UI
    would too (governance 0002 parity). In-process calls are serialized by a
    lock; cross-process duplication is prevented by the durable log claim.

    audit(): log-only record for actions that must NOT create a prompt
             (governance 0002) — auto-permitted actions, wire bookkeeping.
    """

    def __init__(self, log: ChainedLog, presenter: Presenter = terminal_presenter,
                 raw_dir: Path | None = None):
        self.log = log
        self.presenter = presenter
        self.raw_dir = raw_dir
        self._lock = threading.Lock()

    def _stash_raw(self, req: NormalizedRequest) -> str | None:
        if self.raw_dir is None:
            return None
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        name = f"relay-{req.fingerprint[:24]}.json"
        n, path = 1, self.raw_dir / name
        while path.exists():
            path = self.raw_dir / f"relay-{req.fingerprint[:24]}.{n}.json"
            n += 1
        path.write_text(canonical(req.payload))
        return path.name

    def _decision_record(self, req: NormalizedRequest, raw_ref, decision, reason) -> None:
        self.log.append({
            "ts": time.time(), "kind": "permission_decision",
            **req.tracked_record(), "payload_raw_ref": raw_ref,
            "decision": decision, "reason": reason,
        })

    def _notify_presenter(
        self,
        method: str,
        req: NormalizedRequest,
        decision: Decision,
    ) -> None:
        """Optional GUI lifecycle hook; never changes a durable decision.

        Terminal presenters have no hook. The M2 bridge uses it to distinguish
        an in-memory Live response from the later hash-chain append. A
        notification transport failure after the append cannot revoke or
        rewrite the already-recorded decision.
        """

        callback = getattr(self.presenter, method, None)
        if not callable(callback):
            owner = getattr(self.presenter, "__self__", None)
            callback = getattr(owner, method, None)
        if callable(callback):
            try:
                callback(req, decision)
            except Exception:
                pass

    def relay(self, req: NormalizedRequest) -> tuple[Decision, str]:
        with self._lock:
            return self._relay_locked(req)

    def _relay_locked(self, req: NormalizedRequest) -> tuple[Decision, str]:
        if not req.correlation_id:  # R10 f.4: no key, no exactly-once — refuse
            raise RelayIntegrityError(
                "missing correlation id — the exactly-once key cannot be claimed")
        try:
            req.enrich()
        except Exception as exc:
            # Unenrichable payload: no fingerprint exists, so neither replay
            # nor conflict can be verified. Claim-and-deny ONCE; the same key
            # arriving again is an integrity fault, never a silent second
            # deny (M1 audit finding 5: no conflation).
            appended, _ = self.log.append_unique(
                {"ts": time.time(), "kind": "relay_claim",
                 **req.tracked_record(), "payload_raw_ref": None},
                "relay_claim", req.correlation_id)
            if not appended:
                self.log.append({"ts": time.time(), "kind": "correlation_conflict",
                                 **req.tracked_record(),
                                 "conflicting_fingerprint": "UNENRICHABLE_RETRANSMISSION"})
                raise RelayIntegrityError(
                    f"correlation {req.correlation_id} re-presented with an "
                    "unenrichable payload — exactly-once cannot be verified")
            reason = f"malformed request — fail closed ({exc})"
            self._decision_record(req, None, "deny", reason)
            return "deny", reason

        # Claim BEFORE touching raw storage (M1 audit finding 5): replay and
        # conflict answers must never depend on raw-store health.
        claim = {"ts": time.time(), "kind": "relay_claim",
                 **req.tracked_record(), "payload_raw_ref": None}
        appended, existing = self.log.append_unique(claim, "relay_claim", req.correlation_id)
        if not appended:
            if existing.get("fingerprint") != req.fingerprint:
                self.log.append({"ts": time.time(), "kind": "correlation_conflict",
                                 **req.tracked_record(),
                                 "conflicting_fingerprint": existing.get("fingerprint")})
                raise RelayIntegrityError(
                    f"correlation {req.correlation_id} reused with a DIFFERENT request "
                    "fingerprint — exactly-once cannot be preserved, failing the phase")
            prior = [r for r in self.log.verified_records()
                     if r.get("kind") == "permission_decision"
                     and r.get("correlation_id") == req.correlation_id]
            # R10 f.4: a replay is answerable ONLY from exactly one prior decision
            if len(prior) == 1 and prior[0].get("fingerprint") == req.fingerprint:
                self.log.append({"ts": time.time(), "kind": "replay_returned",
                                 **req.tracked_record(),
                                 "replayed_decision": prior[0]["decision"]})
                return prior[0]["decision"], "replayed recorded decision (exactly-once)"
            if len(prior) > 1:
                self.log.append({"ts": time.time(), "kind": "correlation_conflict",
                                 **req.tracked_record(),
                                 "conflicting_fingerprint": "MULTIPLE_PRIOR_DECISIONS"})
                raise RelayIntegrityError(
                    f"correlation {req.correlation_id} has {len(prior)} recorded "
                    "decisions — ledger integrity lost, failing the phase")
            self.log.append({"ts": time.time(), "kind": "correlation_conflict",
                             **req.tracked_record(),
                             "conflicting_fingerprint": existing.get("fingerprint")})
            raise RelayIntegrityError(
                f"correlation {req.correlation_id} already claimed without a recorded "
                "decision (prior attempt died mid-card) — failing the phase")

        # We own the claim. Stash the verbatim payload BEFORE any card (R6:
        # card and raw stash must carry the same content); if the raw store
        # fails, deny WITHOUT presenting — and because the deny is recorded,
        # any replay of this key returns it consistently.
        try:
            raw_ref = self._stash_raw(req)
        except Exception as exc:
            reason = f"raw evidence store unavailable — fail closed ({exc})"
            self._decision_record(req, None, "deny", reason)
            return "deny", reason

        # exactly one presentation
        decision: Decision = "deny"
        reason = "fail-closed default"
        try:
            result = self.presenter(req, render_card(req))
            if result == "allow":
                decision, reason = "allow", "Live decided at presenter"
            elif result == "deny":
                reason = "Live decided at presenter"
            else:
                reason = f"presenter returned invalid decision {result!r} — fail closed"
        except Exception as exc:
            decision, reason = "deny", f"relay exception — fail closed ({exc})"
        try:
            self._decision_record(req, raw_ref, decision, reason)
        except BaseException:
            self._notify_presenter("decision_record_failed", req, decision)
            raise
        self._notify_presenter("decision_recorded", req, decision)
        return decision, reason

    def audit(self, req: NormalizedRequest, kind: str) -> dict:
        """No card, no decision — audit trail only (governance 0002)."""
        if kind not in AUDIT_KINDS:
            raise ValueError(f"not an audit kind: {kind!r}")
        req.enrich()
        raw_ref = self._stash_raw(req)
        return self.log.append({
            "ts": time.time(), "kind": kind,
            **req.tracked_record(), "payload_raw_ref": raw_ref,
        })
