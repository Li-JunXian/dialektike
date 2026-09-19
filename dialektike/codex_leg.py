"""Dialektikḗ M1 — Codex leg: one turn over `codex app-server` (0.145.0 wire).

Codex receives the user's prompt and Claude's response as fenced data and
responds. Native approval requests — new-style item/* approvals AND legacy
execCommandApproval/applyPatchApproval — are relayed to Live through the
shared PermissionRelay and the answer is mapped back onto the wire here (the
only wire-specific part). Non-approval interactive requests and unknown
server requests are declined fail-closed on the wire and audit-logged.
Ambient (natively auto-permitted) items are audit-logged, never re-prompted
(governance 0002). Thread config is native defaults (governance 0003): only
cwd is sent; the effective modelProvider is gated against the first-party
allowlist (axiom 1).

Verified wire facts honored here: JSON-RPC over stdio without the "jsonrpc"
header; turn/completed.items is empty — item/completed is the item source;
absolute paths belong in prompts, the model does not know its cwd.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from core.broker import ChainedLog, canonical, sha256_text
from core.relay import (Decision, NormalizedRequest, PermissionRelay,
                        sanitize_terminal, terminal_presenter)

from dialektike import __version__

CASE = "m1-dialogue"
ROLE = "second-voice"

# Wire decision vocabulary per approval method (schema-pinned).
RELAY_DECISIONS = {
    "item/commandExecution/requestApproval": ("accept", "decline"),
    "item/fileChange/requestApproval": ("accept", "decline"),
    "execCommandApproval": ("approved", "denied"),   # legacy ReviewDecision enum
    "applyPatchApproval": ("approved", "denied"),    # legacy ReviewDecision enum
}

AMBIENT_ITEM_TYPES = {"commandExecution", "fileChange", "webSearch", "mcpToolCall",
                      "collabAgentToolCall", "imageView", "imageGeneration",
                      "dynamicToolCall"}

# Item types whose schema defines NO status property (audit R2 f.3): for
# these, the item/completed notification itself evidences completion.
STATUSLESS_ITEM_TYPES = {"webSearch", "imageView"}


def rate_limit_reached(params: dict) -> str | None:
    """Non-null RateLimits.rateLimitReachedType is the wire's authoritative
    'limit reached' signal (schema-pinned); snapshots without it are
    bookkeeping, not warnings."""
    reached = (params.get("rateLimits") or {}).get("rateLimitReachedType")
    return str(reached) if reached else None

# Axiom 1: the effective modelProvider must be a first-party subscription
# provider — nonempty is not evidence.
ALLOWED_MODEL_PROVIDERS = {"openai"}

@dataclass(frozen=True, slots=True)
class TurnTimeoutPolicy:
    """Bound a Codex turn without mistaking useful work for a hang.

    ``idle_seconds`` is refreshed only by schema-pinned activity belonging to
    the exact parent turn. ``hard_seconds`` remains a separate safety ceiling.
    Both clocks exclude time spent waiting for Live at a permission card.
    """

    idle_seconds: float = 600.0
    hard_seconds: float = 3600.0
    interrupt_drain_seconds: float = 5.0
    poll_seconds: float = 0.2

    def __post_init__(self) -> None:
        if min(
            self.idle_seconds,
            self.hard_seconds,
            self.interrupt_drain_seconds,
            self.poll_seconds,
        ) <= 0:
            raise ValueError("turn timeout policy values must be positive")
        if self.hard_seconds < self.idle_seconds:
            raise ValueError("hard turn timeout must not be shorter than idle timeout")


DEFAULT_TURN_TIMEOUT_POLICY = TurnTimeoutPolicy()
# Backwards-compatible name used by the M1 invariant suite and transcript
# wording. It now means parent-turn inactivity, not total wall-clock runtime.
TURN_TIMEOUT = DEFAULT_TURN_TIMEOUT_POLICY.idle_seconds

# Only explicit, schema-pinned notifications carrying the exact parent
# (threadId, turnId) may refresh its idle timeout. Global bookkeeping (for
# example account/rateLimits/updated) and child turns cannot keep it alive.
TURN_ACTIVITY_METHODS = frozenset(
    {
        "thread/tokenUsage/updated",
        "hook/started",
        "hook/completed",
        "turn/diff/updated",
        "turn/plan/updated",
        "item/started",
        "item/completed",
        "item/agentMessage/delta",
        "item/plan/delta",
        "item/commandExecution/outputDelta",
        "item/commandExecution/terminalInteraction",
        "item/fileChange/outputDelta",
        "item/fileChange/patchUpdated",
        "item/mcpToolCall/progress",
        "item/reasoning/summaryTextDelta",
        "item/reasoning/summaryPartAdded",
        "item/reasoning/textDelta",
        "item/autoApprovalReview/started",
        "item/autoApprovalReview/completed",
        "thread/compacted",
        "model/rerouted",
        "model/verification",
        "turn/moderationMetadata",
        "model/safetyBuffering/updated",
        # A retryable provider error is still genuine parent progress. The
        # exact ids are mandatory; child errors remain isolated by key.
        "error",
        # Server requests are activity only when the current wire supplies
        # both direct correlation ids. Legacy/global requests are ignored.
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "item/tool/requestUserInput",
        "mcpServer/elicitation/request",
        "item/tool/call",
    }
)

# `AppServerClient.close()` runs inside the packaged Python sidecar's own
# graceful shutdown. Keep every process/thread wait on one documented budget
# that is safely below the Rust supervisor's 15-second fallback: at most four
# seconds for TERM, one for KILL+reap, and two shared seconds for both already-
# running pipe readers (seven seconds total, excluding the bounded-size raw
# capture writes themselves).
APP_SERVER_TERMINATE_TIMEOUT = 4.0
APP_SERVER_KILL_TIMEOUT = 1.0
APP_SERVER_READER_DRAIN_TIMEOUT = 2.0


class AppServerError(RuntimeError):
    """The codex leg cannot certify its outcome — the run fails, controlled."""


class AppServerTurnTimeout(AppServerError):
    """The exact parent turn crossed an idle or hard safety boundary."""

    def __init__(self, kind: str) -> None:
        if kind not in {"idle", "hard"}:
            raise ValueError("turn timeout kind must be 'idle' or 'hard'")
        self.kind = kind
        if kind == "idle":
            reason = "parent turn had no activity for 600 seconds"
        else:
            reason = "parent turn reached the 3600-second active safety limit"
        super().__init__(reason)


class AppServerTurnInterrupted(AppServerError):
    """Live requested stop and the exact parent did not terminate in time."""


def _correlation_id(server_request_id, params: dict) -> str:
    return sha256_text(canonical({"server_request_id": server_request_id,
                                  "params_sha256": sha256_text(canonical(params))}))


def _hashed_id_annotations(params: dict) -> dict:
    """Runtime ids appear in tracked records only as hashes (relay contract)."""
    out = {}
    for key, label in (("threadId", "thread_id_sha256"), ("turnId", "turn_id_sha256"),
                       ("itemId", "item_id_sha256"), ("callId", "call_id_sha256")):
        val = params.get(key)
        if val:
            out[label] = sha256_text(str(val))
    return out


class AppServerClient:
    """JSON-RPC 2.0 over `codex app-server` stdio ("jsonrpc" header omitted)."""

    def __init__(
        self,
        log: ChainedLog,
        raw_dir: Path,
        *,
        executable: str | os.PathLike[str] = "codex",
    ):
        self.model_label = "codex"
        self.raw_dir = raw_dir
        self.executable = str(executable)
        self.proc = subprocess.Popen(
            [self.executable, "app-server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._id = 0
        self._send_lock = threading.Lock()
        self._closed = False
        self.events: list[dict] = []
        self.item_events: list[dict] = []      # item/completed params
        self.declined: list[str] = []          # methods answered fail-closed
        self.fatal: list[str] = []             # handler/protocol faults
        # Hashed itemId/callId -> the decision Live actually made.  A boolean
        # "was relayed" flag is not enough: a denied native request must not
        # later be described as a relayed approval in the item audit.
        self.relayed_item_decisions: dict[str, Decision] = {}
        self.rate_limit_events: list[dict] = []  # account/rateLimits/updated params
        self.rate_limit_stop: str | None = None  # set when the wire reports a reached limit
        self.relay_active = threading.Event()  # a card is in front of Live
        self._relay_pause_lock = threading.Lock()
        self._relay_pause_started_at: float | None = None
        self._relay_pause_accumulated = 0.0
        self.relay = PermissionRelay(log=log, presenter=self._present, raw_dir=raw_dir)
        # One app-server stream can carry the requested turn plus native
        # collaboration/subagent turns. Completion is therefore correlated by
        # the exact parent (threadId, turn.id), never by "the next
        # turn/completed notification". Keeping the completed payloads also
        # makes completion-before-wait races lossless.
        self._turn_completion_condition = threading.Condition()
        self._turn_completions: dict[tuple[str, str], dict] = {}
        self._turn_completion_error: str | None = None
        self._turn_activity_generation: dict[tuple[str, str], int] = {}
        self._turn_last_activity: dict[tuple[str, str], float] = {}
        self._stderr_chunks: list[str] = []
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._stderr = threading.Thread(target=self._drain_stderr, daemon=True)
        self._reader.start()
        self._stderr.start()

    def _present(self, req, card):
        """Shared terminal presenter, wrapped so an open card cannot expire
        the turn timeout."""
        self._begin_relay_pause()
        try:
            return terminal_presenter(req, card)
        finally:
            self._end_relay_pause()

    def _begin_relay_pause(self) -> None:
        with self._relay_pause_lock:
            if self._relay_pause_started_at is None:
                self._relay_pause_started_at = time.monotonic()
            self.relay_active.set()

    def _end_relay_pause(self) -> None:
        with self._relay_pause_lock:
            started = self._relay_pause_started_at
            if started is not None:
                self._relay_pause_accumulated += max(
                    0.0, time.monotonic() - started
                )
                self._relay_pause_started_at = None
            self.relay_active.clear()

    def relay_pause_total(self) -> float:
        """Return the exact cumulative duration of permission-card pauses."""

        with self._relay_pause_lock:
            total = self._relay_pause_accumulated
            if self._relay_pause_started_at is not None:
                total += max(0.0, time.monotonic() - self._relay_pause_started_at)
            return total

    def _normalized(self, method: str, params: dict, corr: str) -> NormalizedRequest:
        return NormalizedRequest(
            provider="codex", case=CASE, phase="codex",
            model=self.model_label, role=ROLE, kind=method,
            payload=dict(params), correlation_id=corr,
            annotations=_hashed_id_annotations(params),
        )

    def _drain_stderr(self):
        self._stderr_chunks.extend(line for line in self.proc.stderr)

    def _read_loop(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                (self.raw_dir / "codex_malformed_stdout.txt").write_text(line)
                self.fatal.append(f"malformed stdout line ({len(line)} chars, "
                                  "preserved to raw/)")
                continue
            self.events.append(msg)
            try:
                self._handle(msg)
            except Exception as exc:  # a handler fault means state is untrustworthy
                self.fatal.append(f"handler exception on {msg.get('method')!r}: {exc}")

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
        raise AppServerError(f"no response for request {req_id} within {timeout}s")

    # -- server→client handling, by exact schema method --

    def _handle(self, msg: dict):
        method = msg.get("method", "")
        params = msg.get("params", {}) or {}
        # Record exact parent activity before a permission presenter can block
        # this reader thread. The waiter's idle clock therefore reflects the
        # native request even while Live considers its card.
        self._record_turn_activity(method, params)
        if "id" in msg and method:  # server-initiated request
            corr = _correlation_id(msg["id"], params)
            self.relay.audit(self._normalized(method, params, corr),
                             kind="server_request")
            if method in RELAY_DECISIONS:
                allow_wire, deny_wire = RELAY_DECISIONS[method]
                decision, _ = self.relay.relay(self._normalized(method, params, corr))
                self._remember_relayed(params, decision)
                self._send({"id": msg["id"], "result":
                            {"decision": allow_wire if decision == "allow" else deny_wire}})
            elif method == "item/permissions/requestApproval":
                decision, _ = self.relay.relay(self._normalized(method, params, corr))
                self._remember_relayed(params, decision)
                granted = (params.get("permissions") or {}) if decision == "allow" else {}
                self._send({"id": msg["id"],
                            "result": {"permissions": granted, "scope": "turn"}})
            elif method == "mcpServer/elicitation/request":
                # non-approval interactive flow — fail-closed decline
                self._send({"id": msg["id"], "result": {"action": "decline",
                                                        "content": None}})
                self.declined.append(method)
                self.relay.audit(self._normalized(method, params, corr),
                                 kind="non_approval_declined")
            else:  # incl. item/tool/requestUserInput, token refresh, attestation
                self._send({"id": msg["id"],
                            "error": {"code": -32601,
                                      "message": "Dialektikḗ fail-closed responder"}})
                self.declined.append(method)
                self.relay.audit(self._normalized(method, params, corr),
                                 kind="unknown_request_declined")
            return
        if method == "item/completed":  # canonical item source (turn/completed.items is empty)
            self.item_events.append(params)
        elif method == "turn/completed":
            turn = params.get("turn")
            thread_id = params.get("threadId")
            turn_id = turn.get("id") if isinstance(turn, dict) else None
            with self._turn_completion_condition:
                if not thread_id or not turn_id:
                    self._turn_completion_error = (
                        "turn/completed omitted threadId or turn.id"
                    )
                else:
                    key = (str(thread_id), str(turn_id))
                    completed = dict(turn)
                    prior = self._turn_completions.get(key)
                    if prior is not None and prior != completed:
                        self._turn_completion_error = (
                            "conflicting turn/completed payloads for one turn"
                        )
                    else:
                        self._turn_completions[key] = completed
                self._turn_completion_condition.notify_all()
        elif method == "account/rateLimits/updated":
            # plan-usage visibility (standing authorization): captured to the
            # transcript and surfaced by respond(); a non-null
            # rateLimitReachedType triggers the stop-and-report path (R2 f.2)
            self.rate_limit_events.append(dict(params))
            reached = rate_limit_reached(params)
            if reached and not self.rate_limit_stop:
                self.rate_limit_stop = f"codex plan limit reached ({reached})"

    @staticmethod
    def _activity_key(method: str, params: dict) -> tuple[str, str] | None:
        if method == "turn/started":
            turn = params.get("turn")
            thread_id = params.get("threadId")
            turn_id = turn.get("id") if isinstance(turn, dict) else None
        elif method == "error":
            if params.get("willRetry") is not True:
                return None
            thread_id = params.get("threadId")
            turn_id = params.get("turnId")
        elif method in TURN_ACTIVITY_METHODS:
            thread_id = params.get("threadId")
            turn_id = params.get("turnId")
        else:
            return None
        if not thread_id or not turn_id:
            return None
        return str(thread_id), str(turn_id)

    def _record_turn_activity(self, method: str, params: dict) -> None:
        key = self._activity_key(method, params)
        if key is None:
            return
        # Store an active-time monotonic coordinate. Subtracting cumulative
        # permission-card time makes later deadline comparisons exact even if
        # the waiter is not scheduled until a card has already closed and
        # newer parent events have also arrived.
        received_at = time.monotonic() - self.relay_pause_total()
        with self._turn_completion_condition:
            self._turn_activity_generation[key] = (
                self._turn_activity_generation.get(key, 0) + 1
            )
            self._turn_last_activity[key] = received_at
            self._turn_completion_condition.notify_all()

    def turn_activity_snapshot(
        self,
        thread_id: str,
        turn_id: str,
    ) -> tuple[int, float | None]:
        """Atomically snapshot activity for one exact parent turn."""

        key = (str(thread_id), str(turn_id))
        with self._turn_completion_condition:
            return (
                self._turn_activity_generation.get(key, 0),
                self._turn_last_activity.get(key),
            )

    def wait_for_turn_update(
        self,
        thread_id: str,
        turn_id: str,
        *,
        after_generation: int,
        timeout: float,
    ) -> tuple[dict | None, int, float | None]:
        """Wait for this parent's completion or next parent activity.

        Child notifications may wake the condition internally, but the
        exact-key predicate remains false and cannot refresh or satisfy the
        parent wait.
        """

        key = (str(thread_id), str(turn_id))
        with self._turn_completion_condition:
            self._turn_completion_condition.wait_for(
                lambda: (
                    key in self._turn_completions
                    or self._turn_completion_error is not None
                    or self._turn_activity_generation.get(key, 0)
                    != after_generation
                ),
                timeout=max(0.0, timeout),
            )
            if self._turn_completion_error is not None:
                raise AppServerError(self._turn_completion_error)
            completion = self._turn_completions.get(key)
            return (
                dict(completion) if completion is not None else None,
                self._turn_activity_generation.get(key, 0),
                self._turn_last_activity.get(key),
            )

    def wait_for_turn_completion(
        self,
        thread_id: str,
        turn_id: str,
        *,
        timeout: float,
    ) -> dict | None:
        """Return only the completion for the requested parent turn.

        Foreign child completions remain retained in ``_turn_completions``
        for raw/audit fidelity, but cannot satisfy this wait. The registry is
        checked before blocking, so a completion received before turn/start's
        response (or before this method is called) is not lost.
        """

        key = (str(thread_id), str(turn_id))
        with self._turn_completion_condition:
            ready = self._turn_completion_condition.wait_for(
                lambda: (
                    key in self._turn_completions
                    or self._turn_completion_error is not None
                ),
                timeout=timeout,
            )
            if self._turn_completion_error is not None:
                raise AppServerError(self._turn_completion_error)
            if not ready:
                return None
            return dict(self._turn_completions[key])

    def _remember_relayed(self, params: dict, decision: Decision):
        """Join each native item to Live's actual recorded relay decision."""
        for key in ("itemId", "callId"):
            val = params.get(key)
            if val:
                self.relayed_item_decisions[sha256_text(str(val))] = decision

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.proc.stdin.close()
        except Exception:
            pass

        forced = False
        terminate_error: BaseException | None = None
        try:
            self.proc.terminate()
        except Exception as exc:
            # A process that has already exited may reject TERM even though a
            # following wait reaps it normally. Only promote this diagnostic
            # if the wait also cannot certify clean exit.
            terminate_error = exc
        try:
            self.proc.wait(timeout=APP_SERVER_TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            forced = True
        except Exception as exc:
            # The process state is uncertain. Escalate exactly as for a TERM
            # timeout, then retain the diagnostic in owner-only evidence.
            forced = True
            self.fatal.append(
                f"app-server wait after terminate failed: "
                f"{type(exc).__name__}: {exc}"
            )
        if forced:
            if terminate_error is not None:
                self.fatal.append(
                    f"app-server terminate failed: "
                    f"{type(terminate_error).__name__}: {terminate_error}"
                )
            try:
                self.proc.kill()
                self.proc.wait(timeout=APP_SERVER_KILL_TIMEOUT)
            except subprocess.TimeoutExpired as exc:
                self.fatal.append(
                    "app-server did not reap within the bounded kill timeout: "
                    f"{exc}"
                )
            except Exception as exc:
                self.fatal.append(
                    f"app-server kill/reap failed: {type(exc).__name__}: {exc}"
                )

        # stdout and stderr have been draining concurrently since __init__.
        # Give the pair one shared deadline; two sequential full timeouts would
        # silently double the shutdown bound.
        reader_deadline = time.monotonic() + APP_SERVER_READER_DRAIN_TIMEOUT
        for reader in (self._reader, self._stderr):
            remaining = max(0.0, reader_deadline - time.monotonic())
            reader.join(timeout=remaining)
        if self._reader.is_alive() or self._stderr.is_alive():
            self.fatal.append("reader threads did not join — capture may be incomplete")
        (self.raw_dir / "codex_events.json").write_text(
            json.dumps(self.events, indent=1, ensure_ascii=False, default=str))
        if self._stderr_chunks:
            (self.raw_dir / "codex_stderr.log").write_text("".join(self._stderr_chunks))


def _wait_for_turn_terminal(
    client: AppServerClient,
    thread_id: str,
    turn_id: str,
    *,
    interrupt_requested: threading.Event | None = None,
    policy: TurnTimeoutPolicy = DEFAULT_TURN_TIMEOUT_POLICY,
    clock=time.monotonic,
) -> dict:
    """Wait for one exact parent turn with activity-aware safety bounds.

    A timeout first requests the provider's native interruption and then
    drains the matching completion for a bounded interval. A normal
    completion racing that boundary wins. The caller remains responsible for
    interpreting non-completed terminal statuses.
    """

    # Compare in active-time coordinates: wall monotonic time minus cumulative
    # permission-card time. This remains monotonic while Live considers a
    # card and avoids reconstructing which pauses preceded each activity.
    started_at = clock() - client.relay_pause_total()
    generation, last_activity = client.turn_activity_snapshot(thread_id, turn_id)
    idle_anchor = max(
        started_at,
        last_activity if last_activity is not None else started_at,
    )
    idle_deadline = idle_anchor + policy.idle_seconds
    hard_deadline = started_at + policy.hard_seconds
    interrupted_on_wire = False

    def request_interrupt_once() -> None:
        nonlocal interrupted_on_wire
        if interrupted_on_wire:
            return
        try:
            client.request(
                "turn/interrupt",
                {"threadId": thread_id, "turnId": str(turn_id)},
            )
        except Exception as exc:
            client.fatal.append(
                "native turn/interrupt request failed: "
                f"{type(exc).__name__}: {exc}"
            )
        interrupted_on_wire = True

    while True:
        now = clock() - client.relay_pause_total()
        remaining = min(idle_deadline - now, hard_deadline - now)
        wait_seconds = max(0.0, min(policy.poll_seconds, remaining))
        completion, observed_generation, observed_activity = (
            client.wait_for_turn_update(
                thread_id,
                str(turn_id),
                after_generation=generation,
                timeout=wait_seconds,
            )
        )
        if completion is not None:
            return completion
        if observed_generation != generation:
            generation = observed_generation
            if observed_activity is not None:
                idle_deadline = (
                    max(started_at, observed_activity) + policy.idle_seconds
                )
            continue

        if interrupt_requested is not None and interrupt_requested.is_set():
            request_interrupt_once()
            completion = client.wait_for_turn_completion(
                thread_id,
                str(turn_id),
                timeout=policy.interrupt_drain_seconds,
            )
            if completion is None:
                client.fatal.append(
                    "Live requested stop; native interrupt requested; no "
                    "terminal status arrived during bounded drain"
                )
                raise AppServerTurnInterrupted(
                    "codex parent turn did not acknowledge Live's stop within "
                    "the bounded interrupt drain"
                )
            return completion

        if client.proc.poll() is not None:
            completion = client.wait_for_turn_completion(
                thread_id,
                str(turn_id),
                timeout=policy.interrupt_drain_seconds,
            )
            if completion is None:
                raise AppServerError("codex app-server exited during the turn")
            return completion

        now = clock() - client.relay_pause_total()
        if now < idle_deadline and now < hard_deadline:
            continue

        # Re-enter the exact-key condition before claiming timeout. Activity
        # or completion that arrived at the boundary therefore wins over a
        # stale clock snapshot.
        completion, observed_generation, observed_activity = (
            client.wait_for_turn_update(
                thread_id,
                str(turn_id),
                after_generation=generation,
                timeout=0.0,
            )
        )
        if completion is not None:
            return completion
        if observed_generation != generation:
            generation = observed_generation
            if observed_activity is not None:
                idle_deadline = (
                    max(started_at, observed_activity) + policy.idle_seconds
                )
            continue

        now = clock() - client.relay_pause_total()
        if now < idle_deadline and now < hard_deadline:
            continue
        timeout_kind = "hard" if now >= hard_deadline else "idle"
        request_interrupt_once()
        completion = client.wait_for_turn_completion(
            thread_id,
            str(turn_id),
            timeout=policy.interrupt_drain_seconds,
        )
        if completion is not None and completion.get("status") == "completed":
            return completion
        client.fatal.append(
            f"parent turn {timeout_kind} timeout; native interrupt requested; "
            + (
                f"drained terminal status {completion.get('status')!r}"
                if completion is not None
                else "no terminal status arrived during bounded drain"
            )
        )
        raise AppServerTurnTimeout(timeout_kind)


# -- protocol steps --

def _handshake(client: AppServerClient):
    rid = client.request("initialize", {
        "clientInfo": {"name": "dialektike", "title": "Dialektikḗ",
                       "version": __version__},
    })
    resp = client.response_for(rid)
    if "error" in resp:
        raise AppServerError(f"initialize failed: {resp['error']}")
    client.notify("initialized")


def _assert_chatgpt_account(client: AppServerClient) -> dict:
    """Axiom 1, fail closed: abort unless account.type == 'chatgpt'."""
    rid = client.request("account/read", {"refreshToken": False})
    resp = client.response_for(rid)
    if "error" in resp:
        raise AppServerError("account/read failed — cannot certify billing "
                             f"(fail closed): {resp['error']}")
    account = (resp.get("result") or {}).get("account") or {}
    if account.get("type") != "chatgpt":
        raise AppServerError(f"account type {account.get('type')!r} != 'chatgpt' — "
                             "subscription billing not proven (fail closed)")
    return account


def _served_models(client: AppServerClient) -> tuple[set[str], str | None]:
    """The models THIS codex binary can serve, and its declared default.
    Live's config may pin a model written by a newer app (e.g. the ChatGPT
    desktop app) that this binary cannot run — model/list is the binary's
    own ground truth, costs no quota, and avoids burning a failed turn."""
    data: list[dict] = []
    cursor = None
    while True:  # follow pagination if the server offers it (audit R1)
        params: dict = {"includeHidden": True}  # hidden models are still servable (R2)
        if cursor:
            params["cursor"] = cursor
        rid = client.request("model/list", params)
        resp = client.response_for(rid)
        if "error" in resp:
            raise AppServerError(f"model/list failed: {resp['error']}")
        result = resp.get("result") or {}
        data.extend(result.get("data") or [])
        cursor = result.get("nextCursor") or result.get("cursor")
        if not cursor:
            break
    ids = {m.get("model") or m.get("id") for m in data} - {None}
    default = next((m.get("model") or m.get("id") for m in data
                    if m.get("isDefault")), None)
    return ids, default


def _start_thread(client: AppServerClient, workspace: Path,
                  model: str | None = None) -> tuple[str, dict]:
    """Native-default thread (governance 0003): only cwd is requested (plus a
    servable model when the native default is broken — see respond()). The
    effective modelProvider is gated against the first-party allowlist."""
    params: dict = {"cwd": str(workspace)}
    if model:
        params["model"] = model
    rid = client.request("thread/start", params)
    resp = client.response_for(rid)
    if "error" in resp:
        raise AppServerError(f"thread/start failed: {resp['error']}")
    result = resp.get("result") or {}
    thread_id = (result.get("thread") or {}).get("id")
    if not thread_id:
        raise AppServerError(f"no result.thread.id in: {resp}")
    provider = result.get("modelProvider")
    if provider not in ALLOWED_MODEL_PROVIDERS:
        raise AppServerError(
            f"modelProvider {provider!r} not in first-party allowlist "
            f"{sorted(ALLOWED_MODEL_PROVIDERS)} — subscription billing not proven "
            "(fail closed)")
    if result.get("model"):
        client.model_label = f"codex ({result['model']})"  # cards name the model
    return thread_id, result


def _run_turn(client: AppServerClient, thread_id: str, prompt: str) -> str:
    rid = client.request("turn/start", {
        "threadId": thread_id,
        "input": [{"type": "text", "text": prompt}],
    })
    resp = client.response_for(rid)
    if "error" in resp:
        raise AppServerError(f"turn/start failed: {resp['error']}")
    turn_id = ((resp.get("result") or {}).get("turn") or {}).get("id")
    if not turn_id:
        raise AppServerError(f"no result.turn.id in: {resp}")
    completed = _wait_for_turn_terminal(
        client,
        thread_id,
        str(turn_id),
        policy=DEFAULT_TURN_TIMEOUT_POLICY,
    )
    completed_id = completed.get("id")
    if completed_id != turn_id:
        raise AppServerError(f"completed turn {completed_id!r} != started {turn_id!r}")
    status = completed.get("status")
    if status != "completed":
        raise AppServerError(f"turn status {status!r} != 'completed' — fail closed")
    return turn_id


def _bound_items(client: AppServerClient, thread_id: str, turn_id: str) -> list[dict]:
    return [ev["item"] for ev in client.item_events
            if ev.get("threadId") == thread_id and ev.get("turnId") == turn_id
            and isinstance(ev.get("item"), dict)]


def _audit_items(client: AppServerClient, thread_id: str, turn_id: str | None):
    """Audit truth for native items (governance 0002; M1 audit finding 7):
    each observed command/file/etc item is audited INDIVIDUALLY with its
    actual status and decision provenance — an item that followed a relayed
    card is NOT 'auto-permitted', and a declined/failed item is recorded as
    a failure. Called on the finally path, so items are audited even when
    the turn itself fails. turn_id None = audit everything on the thread."""
    for ev in client.item_events:
        if ev.get("threadId") != thread_id:
            continue
        if turn_id is not None and ev.get("turnId") != turn_id:
            continue
        item = ev.get("item")
        if not isinstance(item, dict) or item.get("type") not in AMBIENT_ITEM_TYPES:
            continue
        status = item.get("status")
        item_id = str(item.get("id") or "")
        relay_decision = (
            client.relayed_item_decisions.get(sha256_text(item_id))
            if item_id
            else None
        )
        relayed = relay_decision in {"allow", "deny"}
        # Schema-faithful completion (R2 f.3): statusless item types
        # (webSearch, imageView) carry no status property — for them the
        # item/completed notification itself IS the completion evidence.
        completed = (status == "completed"
                     or (status is None and item.get("type") in STATUSLESS_ITEM_TYPES))
        if completed:
            kind = "tool_completed" if relayed else "native_auto_permitted"
        else:
            kind = "tool_failed"
        annotations = {
            "thread_id_sha256": sha256_text(str(ev.get("threadId"))),
            "turn_id_sha256": sha256_text(str(ev.get("turnId"))),
            "status": status if status is not None else "(statusless completion notification)",
            "decision_provenance": (
                "relayed_approval"
                if relay_decision == "allow"
                else "relayed_denial"
                if relay_decision == "deny"
                else "native_auto"
            ),
        }
        if item_id:
            annotations["item_id_sha256"] = sha256_text(item_id)
        client.relay.audit(NormalizedRequest(
            provider="codex", case=CASE, phase="codex", model=client.model_label,
            role=ROLE, kind=f"item/{item.get('type')}", payload=dict(item),
            correlation_id=sha256_text(canonical(ev)),
            annotations=annotations,
        ), kind=kind)


def respond(
    dialectic_input: str,
    log: ChainedLog,
    raw_dir: Path,
    workspace: Path,
    *,
    executable: str | os.PathLike[str],
) -> dict:
    """One app-server turn in a fresh native-default thread; returns a
    transcript entry. Any native approval raised mid-turn reaches Live
    through the relay before the wire is answered. ``executable`` is required
    so the turn uses the exact binary whose version was gated."""
    workspace.mkdir(parents=True, exist_ok=True)
    client = AppServerClient(log, raw_dir, executable=executable)
    model_note = None
    thread_id = None
    turn_id = None
    effective: dict = {}
    account: dict = {}
    text = ""
    # Ordering that makes plan warnings and audits reliable (audit R3 f.2):
    #   capture primary failure → close and drain → audit → inspect warning
    #   → raise/return. A reached-limit event may only be drained during
    #   close(), so no failure is arbitrated before then.
    primary_exc: BaseException | None = None
    try:
        _handshake(client)
        account = _assert_chatgpt_account(client)
        served, served_default = _served_models(client)
        thread_id, effective = _start_thread(client, workspace)
        if served and effective.get("model") not in served:
            # The configured native default is a model this binary cannot
            # serve (config written by a newer app); the native CLI itself
            # would fail this turn. Repair with the binary's OWN declared
            # default — discovered, not hardcoded — and disclose it.
            if not served_default:
                raise AppServerError(
                    f"configured model {effective.get('model')!r} is not servable "
                    "by this codex binary and model/list declares no default")
            model_note = (f"configured model {effective.get('model')!r} is not "
                          f"servable by this codex binary — using its declared "
                          f"default {served_default!r}")
            print(f"note: {sanitize_terminal(model_note)}")
            thread_id, effective = _start_thread(client, workspace,
                                                 model=served_default)
            if effective.get("model") != served_default:  # audit R2: verify the echo
                raise AppServerError(
                    f"fallback thread echoed model {effective.get('model')!r} "
                    f"!= requested {served_default!r} (fail closed)")
        turn_id = _run_turn(client, thread_id, dialectic_input)
        parts = [item.get("text", "")
                 for item in _bound_items(client, thread_id, turn_id)
                 if item.get("type") == "agentMessage"]
        text = "\n\n".join(p for p in parts if p).strip()
    except BaseException as exc:
        # Retain the failure; do NOT decide how to report it until the
        # reader has drained every buffered notification.
        primary_exc = exc
    finally:
        try:
            client.close()  # join readers → item stream + rate limits final
        except BaseException as exc:
            if primary_exc is None:
                primary_exc = exc
            else:
                client.fatal.append(f"close failed after primary exception: "
                                    f"{type(exc).__name__}: {exc}")
        try:
            if thread_id is not None:
                _audit_items(client, thread_id, turn_id)
        except Exception as exc:
            client.fatal.append(f"item audit failed: {exc}")

    # Reader state, rate-limit notifications, and item events are now final.
    if isinstance(primary_exc, (KeyboardInterrupt, SystemExit)):
        raise primary_exc
    failure: BaseException | None = primary_exc
    if failure is None and client.fatal:
        failure = AppServerError(f"codex client fatal events: {client.fatal}")
    if failure is None and not text:
        failure = AppServerError("codex turn produced no agentMessage text")
    if failure is not None:
        # Secondary faults during shutdown (a failed close() or item audit)
        # accumulate in client.fatal; when a PRIMARY failure already exists
        # they must be surfaced alongside it, not silently dropped (audit R3
        # diagnostic polish). The primary still leads and stays the __cause__.
        detail = str(failure)
        secondary = failure is primary_exc and bool(client.fatal)
        if secondary:
            detail += f" [secondary faults during shutdown: {client.fatal}]"
        # a reached plan limit must not hide behind a generic failure (R2
        # f.2): the specific warning rides along into the transcript
        if client.rate_limit_stop:
            raise AppServerError(f"PLAN USAGE WARNING — {client.rate_limit_stop}; "
                                 f"turn also failed: {detail}") from failure
        if secondary:
            raise AppServerError(detail) from failure
        raise failure

    if client.rate_limit_events:
        print(f"notice: codex reported {len(client.rate_limit_events)} rate-limit "
              "snapshot(s) — recorded in the transcript")
    return {"provider": "codex", "text": text,
            "model": effective.get("model"),
            "model_provider": effective.get("modelProvider"),
            "model_note": model_note,
            "plan_type": account.get("planType"),
            "thread_id_sha256": sha256_text(thread_id),
            "declined_requests": client.declined,
            "rate_limits": client.rate_limit_events,
            "rate_limit_stop": client.rate_limit_stop}
