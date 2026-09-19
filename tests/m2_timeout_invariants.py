"""Deterministic Codex timeout and public-failure invariants.

These checks exercise the app-server wait policy without launching a model or
sleeping for the production ten-minute/one-hour budgets.  The scripted client
uses an injected monotonic clock and deliberately mixes parent, child, and
global traffic so only the exact parent turn can extend its inactivity window.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.broker import ChainedLog
from dialektike import codex_leg
from dialektike.adapters import codex as codex_adapter_module
from dialektike.adapters.base import AdapterError, TurnInterrupted, TurnTimedOut
from dialektike.codex_leg import AppServerClient, TurnTimeoutPolicy
from dialektike.domain import (
    AdapterCapabilities,
    AgentSystem,
    ModelCapability,
    ModelProfile,
    ModelSelection,
    Participant,
    Role,
    RunStatus,
    StructuredContentBlock,
    TurnPaths,
    TurnRequest,
    TurnResult,
    TurnStage,
    TurnStatus,
    Vendor,
)
from dialektike.runs import RunStore
from dialektike.sidecar import JsonlSidecar, PROTOCOL_NAME, SAFE_RUN_FAILURE


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass(frozen=True)
class _TimedEvent:
    at: float
    kind: str
    completion: dict | None = None
    pause_total: float | None = None


class _RunningProcess:
    def poll(self):
        return None


class _ScriptedWaitClient:
    """Minimal exact-parent surface consumed by ``_wait_for_turn``."""

    def __init__(
        self,
        clock: _Clock,
        events: list[_TimedEvent] | None = None,
        *,
        drain_result: dict | None = None,
    ) -> None:
        self.clock = clock
        self.events = list(events or [])
        self.drain_result = drain_result
        self.generation = 0
        self.last_activity_at: float | None = None
        self.relay_active = threading.Event()
        self.proc = _RunningProcess()
        self.requests: list[tuple[str, dict]] = []
        self.update_waits: list[tuple[str, str, int, float]] = []
        self.drain_waits: list[tuple[str, str, float]] = []
        self.fatal: list[str] = []
        self.pause_total = 0.0

    def relay_pause_total(self) -> float:
        return self.pause_total

    def turn_activity_snapshot(
        self,
        thread_id: str,
        turn_id: str,
    ) -> tuple[int, float | None]:
        self._assert_parent(thread_id, turn_id)
        return self.generation, self.last_activity_at

    def wait_for_turn_update(
        self,
        thread_id: str,
        turn_id: str,
        *,
        after_generation: int,
        timeout: float,
    ) -> tuple[dict | None, int, float | None]:
        self._assert_parent(thread_id, turn_id)
        if after_generation != self.generation:
            raise AssertionError(
                f"wait used stale generation {after_generation}; "
                f"current is {self.generation}"
            )
        self.update_waits.append(
            (thread_id, turn_id, after_generation, timeout)
        )
        deadline = self.clock.now + timeout
        if self.events and self.events[0].at <= deadline:
            event = self.events.pop(0)
            if event.at < self.clock.now:
                raise AssertionError("scripted events must be monotonic")
            self.clock.now = event.at
            if event.kind == "parent":
                self.generation += 1
                # Production stores activity in active-time coordinates:
                # wall monotonic time less cumulative permission-card time.
                self.last_activity_at = event.at - self.pause_total
            elif event.kind == "pause":
                if (
                    event.pause_total is None
                    or event.pause_total < self.pause_total
                ):
                    raise AssertionError(
                        "permission-pause totals must be cumulative"
                    )
                self.pause_total = event.pause_total
            elif event.kind not in {"foreign", "completion"}:
                raise AssertionError(f"unknown event kind {event.kind!r}")
            return event.completion, self.generation, self.last_activity_at
        self.clock.now = deadline
        return None, self.generation, self.last_activity_at

    def request(self, method: str, params: dict) -> int:
        self.requests.append((method, dict(params)))
        return len(self.requests)

    def wait_for_turn_completion(
        self,
        thread_id: str,
        turn_id: str,
        *,
        timeout: float,
    ) -> dict | None:
        self._assert_parent(thread_id, turn_id)
        self.drain_waits.append((thread_id, turn_id, timeout))
        return self.drain_result

    @staticmethod
    def _assert_parent(thread_id: str, turn_id: str) -> None:
        if (thread_id, turn_id) != ("parent-thread", "parent-turn"):
            raise AssertionError(
                f"wait escaped parent correlation: {(thread_id, turn_id)!r}"
            )


def _policy(
    *,
    idle: float = 5.0,
    hard: float = 20.0,
    drain: float = 1.25,
    poll: float = 2.0,
) -> TurnTimeoutPolicy:
    return TurnTimeoutPolicy(
        idle_seconds=idle,
        hard_seconds=hard,
        interrupt_drain_seconds=drain,
        poll_seconds=poll,
    )


def _participant(
    participant_id: str,
    adapter_id: str,
    vendor: Vendor,
    system: AgentSystem,
) -> Participant:
    return Participant(
        participant_id=participant_id,
        vendor=vendor,
        agent_system=system,
        adapter_id=adapter_id,
        auth_route=f"{adapter_id}-subscription",
        model_profile=ModelProfile(
            requested=ModelSelection(
                model_id=f"{adapter_id}-model",
                effort="high",
            )
        ),
    )


PARTICIPANTS = (
    _participant("executor", "codex", Vendor.OPENAI, AgentSystem.CODEX),
    _participant(
        "auditor",
        "claude-code",
        Vendor.ANTHROPIC,
        AgentSystem.CLAUDE_CODE,
    ),
)


def _turn_request(root: Path) -> TurnRequest:
    return TurnRequest(
        run_id="timeout-regression",
        round_number=1,
        turn_number=1,
        role=Role.EXECUTOR,
        participant=PARTICIPANTS[0],
        original_prompt="Wait safely.",
        input_text="Wait safely.",
        paths=TurnPaths(
            run_path=str(root),
            raw_dir=str(root / "raw"),
            workspace_dir=str(root / "workspace"),
            decisions_path=str(root / "decisions.jsonl"),
        ),
        stage=TurnStage.PROPOSAL,
    )


def _command(command_id: str, command: str, payload: dict | None = None) -> str:
    return json.dumps(
        {
            "protocol": PROTOCOL_NAME,
            "id": command_id,
            "command": command,
            "payload": payload or {},
        }
    )


def _run_payload() -> dict:
    return {
        "prompt": "Wait safely.",
        "rounds": 1,
        "participants": [
            {
                "role": "executor",
                "runtime_id": "codex",
                "requested": {
                    "model": "codex-model",
                    "effort": "high",
                    "service_tier": "native-default",
                },
            },
            {
                "role": "auditor",
                "runtime_id": "claude-code",
                "requested": {
                    "model": "claude-code-model",
                    "effort": "high",
                    "service_tier": "native-default",
                },
            },
        ],
    }


class _OutcomeAdapter:
    def __init__(
        self,
        participant: Participant,
        *,
        failure: str | None = None,
    ) -> None:
        self.adapter_id = participant.adapter_id
        self.participant = participant
        self.failure = failure

    async def discover_capabilities(self) -> AdapterCapabilities:
        requested = self.participant.model_profile.requested
        return AdapterCapabilities(
            adapter_id=self.adapter_id,
            vendor=self.participant.vendor,
            agent_system=self.participant.agent_system,
            models=(
                ModelCapability(
                    model_id=requested.model_id or "model",
                    display_name=f"{self.adapter_id} model",
                    efforts=(requested.effort or "high",),
                ),
            ),
            runtime_version=f"{self.adapter_id}-runtime",
            account_route=self.participant.auth_route,
        )

    async def run_turn(self, request, cancellation) -> TurnResult:
        requested = request.participant.model_profile.requested
        profile = request.participant.model_profile.resolved(
            ModelSelection(
                model_id=requested.model_id,
                effort=requested.effort,
                service_tier=requested.service_tier,
            ),
            f"{self.adapter_id}:test-authority",
        )
        text = "authoritative parent commentary before timeout"
        result = TurnResult(
            text=text,
            blocks=(StructuredContentBlock.markdown(text),),
            model_profile=profile,
            account_route=request.participant.auth_route,
            runtime_version=f"{self.adapter_id}-runtime",
            evidence=(("turn_id_sha256", "real-parent-turn-hash"),),
        )
        if self.failure == "timeout":
            raise TurnTimedOut(
                "idle",
                reason="SECRET transport detail at /Users/live/private",
                partial_result=result,
            )
        if self.failure == "ordinary":
            raise AdapterError(
                "SECRET arbitrary failure at /Users/live/private",
                partial_result=result,
            )
        return result

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None


class AppServerActivityCorrelationTests(unittest.TestCase):
    class _QuietProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout = io.StringIO()
            self.stderr = io.StringIO()

        def poll(self):
            return None

        def terminate(self):
            return None

        def kill(self):
            return None

        def wait(self, timeout=None):
            return 0

    def test_only_exact_parent_notifications_advance_parent_activity(self):
        clock = _Clock()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            raw.mkdir()
            with (
                patch.object(
                    codex_leg.subprocess,
                    "Popen",
                    return_value=self._QuietProcess(),
                ),
                patch.object(codex_leg.time, "monotonic", side_effect=clock),
            ):
                client = AppServerClient(
                    ChainedLog(root / "decisions.jsonl"),
                    raw,
                    executable=root / "gated-codex",
                )
                initial = client.turn_activity_snapshot(
                    "parent-thread", "parent-turn"
                )

                clock.now = 10.0
                client._handle(
                    {
                        "method": "item/agentMessage/delta",
                        "params": {
                            "threadId": "parent-thread",
                            "turnId": "parent-turn",
                            "delta": "visible parent text",
                        },
                    }
                )
                parent = client.turn_activity_snapshot(
                    "parent-thread", "parent-turn"
                )

                clock.now = 11.0
                client._handle(
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": "child-thread",
                            "turnId": "child-turn",
                            "item": {"id": "child-item", "type": "webSearch"},
                        },
                    }
                )
                client._handle(
                    {
                        "method": "account/rateLimits/updated",
                        "params": {
                            "rateLimits": {
                                "planType": "plus",
                                "rateLimitReachedType": None,
                            }
                        },
                    }
                )
                after_foreign = client.turn_activity_snapshot(
                    "parent-thread", "parent-turn"
                )

                clock.now = 12.0
                client._handle(
                    {
                        "method": "thread/tokenUsage/updated",
                        "params": {
                            "threadId": "parent-thread",
                            "turnId": "parent-turn",
                            "tokenUsage": {"total": 1},
                        },
                    }
                )
                after_second_parent = client.turn_activity_snapshot(
                    "parent-thread", "parent-turn"
                )
                client.close()

        self.assertEqual(initial, (0, None))
        self.assertEqual(parent, (1, 10.0))
        self.assertEqual(after_foreign, parent)
        self.assertEqual(after_second_parent, (2, 12.0))

    def test_completion_before_wait_is_retained_by_atomic_update_waiter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            raw.mkdir()
            with patch.object(
                codex_leg.subprocess,
                "Popen",
                return_value=self._QuietProcess(),
            ):
                client = AppServerClient(
                    ChainedLog(root / "decisions.jsonl"),
                    raw,
                    executable=root / "gated-codex",
                )
            client._handle(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "parent-thread",
                        "turn": {
                            "id": "parent-turn",
                            "status": "completed",
                        },
                    },
                }
            )
            try:
                generation, _ = client.turn_activity_snapshot(
                    "parent-thread", "parent-turn"
                )
                completion, returned_generation, _ = (
                    client.wait_for_turn_update(
                        "parent-thread",
                        "parent-turn",
                        after_generation=generation,
                        timeout=0,
                    )
                )
            finally:
                client.close()

        self.assertEqual(
            completion,
            {"id": "parent-turn", "status": "completed"},
        )
        self.assertEqual(returned_generation, generation)

    def test_only_retryable_exact_parent_error_advances_activity(self):
        clock = _Clock()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            raw.mkdir()
            with (
                patch.object(
                    codex_leg.subprocess,
                    "Popen",
                    return_value=self._QuietProcess(),
                ),
                patch.object(codex_leg.time, "monotonic", side_effect=clock),
            ):
                client = AppServerClient(
                    ChainedLog(root / "decisions.jsonl"),
                    raw,
                    executable=root / "gated-codex",
                )

                clock.now = 10.0
                client._handle(
                    {
                        "method": "error",
                        "params": {
                            "threadId": "parent-thread",
                            "turnId": "parent-turn",
                            "willRetry": True,
                            "error": {"message": "retrying parent"},
                        },
                    }
                )
                after_parent_retry = client.turn_activity_snapshot(
                    "parent-thread", "parent-turn"
                )

                clock.now = 11.0
                client._handle(
                    {
                        "method": "error",
                        "params": {
                            "threadId": "child-thread",
                            "turnId": "child-turn",
                            "willRetry": True,
                            "error": {"message": "retrying child"},
                        },
                    }
                )
                after_child_retry = client.turn_activity_snapshot(
                    "parent-thread", "parent-turn"
                )

                clock.now = 12.0
                client._handle(
                    {
                        "method": "error",
                        "params": {
                            "threadId": "parent-thread",
                            "turnId": "parent-turn",
                            "willRetry": False,
                            "error": {"message": "terminal parent error"},
                        },
                    }
                )
                after_terminal_parent = client.turn_activity_snapshot(
                    "parent-thread", "parent-turn"
                )
                child = client.turn_activity_snapshot(
                    "child-thread", "child-turn"
                )
                client.close()

        self.assertEqual(after_parent_retry, (1, 10.0))
        self.assertEqual(after_child_retry, after_parent_retry)
        self.assertEqual(after_terminal_parent, after_parent_retry)
        self.assertEqual(child, (1, 11.0))


class CodexTimeoutPolicyTests(unittest.TestCase):
    def test_parent_activity_extends_idle_deadline(self):
        clock = _Clock()
        client = _ScriptedWaitClient(
            clock,
            [
                _TimedEvent(4.0, "parent"),
                _TimedEvent(8.0, "parent"),
                _TimedEvent(
                    11.5,
                    "completion",
                    {"id": "parent-turn", "status": "completed"},
                ),
            ],
        )

        codex_adapter_module._wait_for_turn(
            client,
            thread_id="parent-thread",
            turn_id="parent-turn",
            interrupt_requested=threading.Event(),
            policy=_policy(),
            clock=clock,
        )

        self.assertEqual(clock.now, 11.5)
        self.assertEqual(client.requests, [])
        self.assertEqual(client.drain_waits, [])

    def test_parent_activity_at_exact_idle_boundary_wins_and_extends(self):
        clock = _Clock()
        client = _ScriptedWaitClient(
            clock,
            [
                # The exact-key waiter receives this event at the same instant
                # as the original idle deadline. It must be observed before
                # the clock snapshot is allowed to claim a timeout.
                _TimedEvent(5.0, "parent"),
                _TimedEvent(
                    9.0,
                    "completion",
                    {"id": "parent-turn", "status": "completed"},
                ),
            ],
        )

        codex_adapter_module._wait_for_turn(
            client,
            thread_id="parent-thread",
            turn_id="parent-turn",
            interrupt_requested=threading.Event(),
            policy=_policy(),
            clock=clock,
        )

        self.assertEqual(clock.now, 9.0)
        self.assertEqual(client.generation, 1)
        self.assertEqual(client.last_activity_at, 5.0)
        self.assertEqual(client.requests, [])
        self.assertEqual(client.drain_waits, [])

    def test_cumulative_permission_pauses_shift_idle_and_hard_deadlines(self):
        clock = _Clock()
        client = _ScriptedWaitClient(
            clock,
            [
                # Two completed permission waits contribute three and then
                # two more seconds. Completion at 9.5 is later than both the
                # original 5-second idle and 8-second hard limits, so success
                # proves both clocks moved by the cumulative five seconds.
                _TimedEvent(4.0, "pause", pause_total=3.0),
                _TimedEvent(7.0, "pause", pause_total=5.0),
                _TimedEvent(
                    9.5,
                    "completion",
                    {"id": "parent-turn", "status": "completed"},
                ),
            ],
        )
        policy = _policy(hard=8.0)

        codex_adapter_module._wait_for_turn(
            client,
            thread_id="parent-thread",
            turn_id="parent-turn",
            interrupt_requested=threading.Event(),
            policy=policy,
            clock=clock,
        )

        self.assertEqual(clock.now, 9.5)
        self.assertEqual(client.pause_total, 5.0)
        self.assertGreater(clock.now, policy.idle_seconds)
        self.assertGreater(clock.now, policy.hard_seconds)
        self.assertEqual(client.requests, [])
        self.assertEqual(client.drain_waits, [])

    def test_parent_activity_after_prior_pause_uses_active_time_coordinate(self):
        clock = _Clock()
        client = _ScriptedWaitClient(
            clock,
            [
                _TimedEvent(4.0, "pause", pause_total=3.0),
                # Wall time 7 minus the prior 3-second permission pause is
                # active time 4. Its five-second idle window therefore ends
                # at active time 9, or wall time 12—not wall time 15.
                _TimedEvent(7.0, "parent"),
            ],
        )
        policy = _policy(hard=20.0)

        with self.assertRaises(TurnTimedOut) as failure:
            codex_adapter_module._wait_for_turn(
                client,
                thread_id="parent-thread",
                turn_id="parent-turn",
                interrupt_requested=threading.Event(),
                policy=policy,
                clock=clock,
            )

        self.assertEqual(failure.exception.kind, "idle")
        self.assertEqual(client.last_activity_at, 4.0)
        self.assertEqual(clock.now, 12.0)

    def test_preexisting_live_stop_interrupts_once_and_drains_once(self):
        clock = _Clock()
        client = _ScriptedWaitClient(clock)
        policy = _policy()
        interrupt_requested = threading.Event()
        interrupt_requested.set()

        with self.assertRaises(TurnInterrupted) as failure:
            codex_adapter_module._wait_for_turn(
                client,
                thread_id="parent-thread",
                turn_id="parent-turn",
                interrupt_requested=interrupt_requested,
                policy=policy,
                clock=clock,
            )

        self.assertNotIsInstance(failure.exception, TurnTimedOut)
        self.assertEqual(
            client.requests,
            [
                (
                    "turn/interrupt",
                    {
                        "threadId": "parent-thread",
                        "turnId": "parent-turn",
                    },
                )
            ],
        )
        self.assertEqual(
            client.drain_waits,
            [("parent-thread", "parent-turn", policy.interrupt_drain_seconds)],
        )
        self.assertIn("Live's stop", str(failure.exception))

    def test_child_and_global_noise_do_not_extend_parent_idle_deadline(self):
        clock = _Clock()
        client = _ScriptedWaitClient(
            clock,
            [
                _TimedEvent(4.0, "foreign"),
                _TimedEvent(4.5, "foreign"),
            ],
        )
        policy = _policy()

        with self.assertRaises(TurnTimedOut) as failure:
            codex_adapter_module._wait_for_turn(
                client,
                thread_id="parent-thread",
                turn_id="parent-turn",
                interrupt_requested=threading.Event(),
                policy=policy,
                clock=clock,
            )

        self.assertEqual(failure.exception.kind, "idle")
        self.assertEqual(clock.now, policy.idle_seconds)
        self.assertEqual(
            client.requests,
            [
                (
                    "turn/interrupt",
                    {
                        "threadId": "parent-thread",
                        "turnId": "parent-turn",
                    },
                )
            ],
        )
        self.assertEqual(
            client.drain_waits,
            [("parent-thread", "parent-turn", policy.interrupt_drain_seconds)],
        )

    def test_hard_cap_wins_despite_continuous_parent_activity(self):
        clock = _Clock()
        client = _ScriptedWaitClient(
            clock,
            [
                _TimedEvent(4.0, "parent"),
                _TimedEvent(8.0, "parent"),
                _TimedEvent(11.5, "parent"),
            ],
        )
        policy = _policy(hard=12.0)

        with self.assertRaises(TurnTimedOut) as failure:
            codex_adapter_module._wait_for_turn(
                client,
                thread_id="parent-thread",
                turn_id="parent-turn",
                interrupt_requested=threading.Event(),
                policy=policy,
                clock=clock,
            )

        self.assertEqual(failure.exception.kind, "hard")
        self.assertEqual(clock.now, policy.hard_seconds)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(len(client.drain_waits), 1)

    def test_completion_during_timeout_drain_wins_the_race(self):
        clock = _Clock()
        completed = {"id": "parent-turn", "status": "completed"}
        client = _ScriptedWaitClient(clock, drain_result=completed)
        policy = _policy()

        codex_adapter_module._wait_for_turn(
            client,
            thread_id="parent-thread",
            turn_id="parent-turn",
            interrupt_requested=threading.Event(),
            policy=policy,
            clock=clock,
        )

        self.assertEqual(len(client.requests), 1)
        self.assertEqual(
            client.drain_waits,
            [("parent-thread", "parent-turn", policy.interrupt_drain_seconds)],
        )

    def test_turn_start_returns_the_parent_id_before_waiting(self):
        class StartClient:
            def __init__(self) -> None:
                self.sent: list[tuple[str, dict]] = []

            def request(self, method, params):
                self.sent.append((method, dict(params)))
                return 41

            def response_for(self, request_id):
                if request_id != 41:
                    raise AssertionError("unexpected request id")
                return {"result": {"turn": {"id": "parent-turn"}}}

        with tempfile.TemporaryDirectory() as td:
            client = StartClient()
            turn_id = codex_adapter_module._start_turn(
                client,
                thread_id="parent-thread",
                request=_turn_request(Path(td)),
                effort="high",
                service_tier=None,
            )

        self.assertEqual(turn_id, "parent-turn")
        self.assertEqual(client.sent[0][0], "turn/start")
        self.assertEqual(client.sent[0][1]["threadId"], "parent-thread")


class TimeoutPublicMessageTests(unittest.TestCase):
    def test_public_timeout_messages_are_fixed_and_private_reason_free(self):
        first = TurnTimedOut(
            "idle",
            reason="SECRET token at /Users/live/private/a",
        )
        second = TurnTimedOut(
            "idle",
            reason="a different transport diagnostic",
        )
        hard = TurnTimedOut(
            "hard",
            reason="SECRET hard-cap transport diagnostic",
        )

        self.assertEqual(first.public_message, second.public_message)
        self.assertIn("10 minutes", first.public_message)
        self.assertIn("60-minute", hard.public_message)
        self.assertIn("partial response", first.public_message)
        self.assertNotIn("SECRET", first.public_message)
        self.assertNotIn("/Users/", first.public_message)
        self.assertFalse(hasattr(AdapterError("private"), "public_message"))


class TimeoutSidecarSurfaceTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, failure: str):
        output: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            runs_root = Path(td) / "runs"
            sidecar = JsonlSidecar(
                store=RunStore(runs_root),
                adapters={
                    "codex": _OutcomeAdapter(
                        PARTICIPANTS[0],
                        failure=failure,
                    ),
                    "claude-code": _OutcomeAdapter(PARTICIPANTS[1]),
                },
                write_line=output.append,
            )
            await sidecar.handle_line(
                _command("discover", "capabilities.discover")
            )
            await sidecar.handle_line(
                _command("run", "run.start", _run_payload())
            )
            await sidecar.wait_idle()
            messages = [json.loads(line) for line in output]
            started = next(
                item
                for item in messages
                if item["event"] == "command.result"
                and item.get("request_id") == "run"
            )
            transcript = json.loads(
                (
                    runs_root
                    / started["payload"]["run_id"]
                    / "transcript.json"
                ).read_text()
            )
        return messages, transcript

    async def test_timeout_surfaces_fixed_reason_and_saves_parent_partial(self):
        messages, transcript = await self._run("timeout")
        failure = next(
            item for item in messages if item["event"] == "run.failed"
        )
        expected = TurnTimedOut("idle").public_message

        self.assertEqual(failure["payload"]["message"], expected)
        serialized = json.dumps(messages)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("/Users/live/private", serialized)
        partial = next(
            item
            for item in messages
            if item["event"] == "conversation.message"
        )
        self.assertTrue(partial["payload"]["message"]["partial"])
        self.assertEqual(
            partial["payload"]["message"]["text"],
            "authoritative parent commentary before timeout",
        )
        self.assertEqual(transcript["status"], RunStatus.FAILED.value)
        self.assertEqual(transcript["turns"][0]["status"], TurnStatus.FAILED.value)
        self.assertEqual(
            dict(transcript["turns"][0]["evidence"])["turn_id_sha256"],
            "real-parent-turn-hash",
        )
        self.assertIn("SECRET transport detail", transcript["failure"])

    async def test_arbitrary_adapter_failure_stays_masked(self):
        messages, transcript = await self._run("ordinary")
        failure = next(
            item for item in messages if item["event"] == "run.failed"
        )

        self.assertEqual(failure["payload"]["message"], SAFE_RUN_FAILURE)
        serialized = json.dumps(messages)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("/Users/live/private", serialized)
        self.assertIn("SECRET arbitrary failure", transcript["failure"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
