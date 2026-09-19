"""M2 stop-path invariants for partial provider evidence."""

from __future__ import annotations

import asyncio
import io
import json
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, TextBlock

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.broker import ChainedLog
from dialektike import codex_leg
from dialektike.adapters.base import (
    AdapterError,
    PlanUsageWarning,
    TurnInterrupted,
)
from dialektike.adapters import claude as claude_adapter_module
from dialektike.adapters import codex as codex_adapter_module
from dialektike.adapters.capabilities import (
    CapabilityError,
    RuntimeGateError,
)
from dialektike.domain import (
    AdapterCapabilities,
    AgentSystem,
    ModelCapability,
    ModelProfile,
    ModelSelection,
    Participant,
    Role,
    RunConfig,
    RunStatus,
    TurnPaths,
    TurnRequest,
    TurnResult,
    TurnStage,
    TurnStatus,
    Vendor,
)
from dialektike.orchestrator import CancellationToken, DialecticOrchestrator
from dialektike.runs import RunStore
from dialektike.sidecar import (
    SAFE_COMMAND_FAILURE,
    SAFE_RUN_FAILURE,
    JsonlSidecar,
    PROTOCOL_NAME,
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
    _participant(
        "executor",
        "codex",
        Vendor.OPENAI,
        AgentSystem.CODEX,
    ),
    _participant(
        "auditor",
        "claude-code",
        Vendor.ANTHROPIC,
        AgentSystem.CLAUDE_CODE,
    ),
)


class _ScriptedAdapter:
    def __init__(
        self,
        adapter_id: str,
        *,
        outcome: (
            type[AdapterError]
            | type[PlanUsageWarning]
            | type[TurnInterrupted]
            | None
        ) = None,
    ) -> None:
        self.adapter_id = adapter_id
        self.outcome = outcome
        self.requests = []
        self.closed = False

    async def discover_capabilities(self) -> AdapterCapabilities:
        participant = next(
            item for item in PARTICIPANTS if item.adapter_id == self.adapter_id
        )
        requested = participant.model_profile.requested
        return AdapterCapabilities(
            adapter_id=self.adapter_id,
            vendor=participant.vendor,
            agent_system=participant.agent_system,
            models=(
                ModelCapability(
                    model_id=requested.model_id or "model",
                    display_name=f"{self.adapter_id} test model",
                    efforts=(requested.effort or "high",),
                    is_default=True,
                ),
            ),
            runtime_version=f"{self.adapter_id}-test-runtime",
            account_route=participant.auth_route,
        )

    async def run_turn(self, request, cancellation) -> TurnResult:
        self.requests.append(request)
        requested = request.participant.model_profile.requested
        profile = request.participant.model_profile.resolved(
            ModelSelection(
                model_id=requested.model_id,
                effort=requested.effort,
                service_tier=requested.service_tier,
            ),
            f"{self.adapter_id}:test-authority",
        )
        result = TurnResult(
            text=f"authoritative partial from {self.adapter_id}",
            model_profile=profile,
            account_route=request.participant.auth_route,
            runtime_version=f"{self.adapter_id}-test-runtime",
            evidence=(("partial", "true"),),
        )
        if self.outcome is PlanUsageWarning:
            raise PlanUsageWarning(
                "subscription boundary reached",
                partial_result=result,
            )
        if self.outcome is TurnInterrupted:
            raise TurnInterrupted(
                "native runtime confirmed interruption",
                partial_result=result,
            )
        if self.outcome is AdapterError:
            raise AdapterError(
                "ordinary provider failure after partial output",
                partial_result=result,
            )
        return result

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


def _config(*, rounds: int = 3) -> RunConfig:
    return RunConfig.fixed_roles(
        prompt="Cross-examine this safely.",
        participants=PARTICIPANTS,
        executor_id="executor",
        auditor_id="auditor",
        rounds=rounds,
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


def _gui_payload() -> dict:
    return {
        "prompt": "Cross-examine this safely.",
        "rounds": 3,
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


def _turn_request(
    participant: Participant,
    root: Path,
    *,
    role: Role,
    stage: TurnStage,
) -> TurnRequest:
    return TurnRequest(
        run_id="runtime-correction",
        round_number=1,
        turn_number=1,
        role=role,
        participant=participant,
        original_prompt="Review this.",
        input_text="Review this.",
        paths=TurnPaths(
            run_path=str(root),
            raw_dir=str(root / "raw"),
            workspace_dir=str(root / "workspace"),
            decisions_path=str(root / "decisions.jsonl"),
        ),
        stage=stage,
    )


class OrchestratorPartialStopTests(unittest.IsolatedAsyncioTestCase):
    async def _run_special(self, outcome_type):
        executor = _ScriptedAdapter("codex", outcome=outcome_type)
        auditor = _ScriptedAdapter("claude-code")
        with tempfile.TemporaryDirectory() as td:
            outcome = await DialecticOrchestrator(
                store=RunStore(Path(td) / "runs"),
                adapters={"codex": executor, "claude-code": auditor},
            ).run(_config(), run_id="partial-stop")
            snapshot = json.loads(
                (Path(outcome.run_path) / "transcript.json").read_text()
            )
            events = [
                json.loads(line)
                for line in (
                    Path(outcome.run_path) / "events.jsonl"
                ).read_text().splitlines()
            ]
        return outcome, snapshot, events, executor, auditor

    async def test_plan_warning_preserves_partial_and_stops_every_later_turn(self):
        outcome, snapshot, events, executor, auditor = await self._run_special(
            PlanUsageWarning
        )

        self.assertEqual(outcome.status, RunStatus.CANCELLED)
        self.assertEqual(len(outcome.turns), 1)
        self.assertEqual(outcome.turns[0].status, TurnStatus.CANCELLED)
        self.assertEqual(
            outcome.turns[0].text,
            "authoritative partial from codex",
        )
        self.assertEqual(outcome.turns[0].evidence, (("partial", "true"),))
        self.assertEqual(
            outcome.turns[0].model_profile.effective_authority,
            "codex:test-authority",
        )
        self.assertTrue(
            (outcome.stop_reason or "").startswith("PLAN USAGE WARNING")
        )
        self.assertEqual(len(executor.requests), 1)
        self.assertEqual(auditor.requests, [])
        self.assertEqual(snapshot["turns"][0]["text"], outcome.turns[0].text)
        self.assertEqual(snapshot["status"], "cancelled")
        kinds = [item["kind"] for item in events]
        self.assertLess(kinds.index("plan_warning"), kinds.index("turn_cancelled"))
        self.assertLess(kinds.index("turn_cancelled"), kinds.index("run_cancelled"))

    async def test_native_interruption_preserves_partial_and_reason(self):
        outcome, snapshot, events, executor, auditor = await self._run_special(
            TurnInterrupted
        )

        self.assertEqual(outcome.status, RunStatus.CANCELLED)
        self.assertEqual(
            outcome.stop_reason,
            "native runtime confirmed interruption",
        )
        self.assertEqual(outcome.turns[0].status, TurnStatus.CANCELLED)
        self.assertEqual(
            outcome.turns[0].text,
            "authoritative partial from codex",
        )
        self.assertEqual(outcome.turns[0].evidence, (("partial", "true"),))
        self.assertEqual(auditor.requests, [])
        self.assertEqual(
            snapshot["stop_reason"],
            "native runtime confirmed interruption",
        )
        kinds = [item["kind"] for item in events]
        self.assertNotIn("turn_completed", kinds)
        self.assertLess(kinds.index("turn_cancelled"), kinds.index("run_cancelled"))

    async def test_ordinary_provider_failure_preserves_authoritative_partial(self):
        outcome, snapshot, events, executor, auditor = await self._run_special(
            AdapterError
        )

        self.assertEqual(outcome.status, RunStatus.FAILED)
        self.assertEqual(outcome.turns[0].status, TurnStatus.FAILED)
        self.assertEqual(
            outcome.turns[0].text,
            "authoritative partial from codex",
        )
        self.assertEqual(outcome.turns[0].evidence, (("partial", "true"),))
        self.assertEqual(
            snapshot["turns"][0]["model_profile"]["effective_authority"],
            "codex:test-authority",
        )
        self.assertEqual(
            snapshot["turns"][0]["evidence"], [["partial", "true"]]
        )
        failed = next(item for item in events if item["kind"] == "turn_failed")
        self.assertEqual(
            failed["payload"]["turn"]["text"],
            "authoritative partial from codex",
        )
        self.assertEqual(
            failed["payload"]["turn"]["evidence"], [["partial", "true"]]
        )
        self.assertEqual(auditor.requests, [])


class SidecarPartialStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_warning_reaches_gui_with_partial_text_before_terminal_stop(self):
        output: list[str] = []
        executor = _ScriptedAdapter("codex", outcome=PlanUsageWarning)
        auditor = _ScriptedAdapter("claude-code")
        with tempfile.TemporaryDirectory() as td:
            sidecar = JsonlSidecar(
                store=RunStore(Path(td) / "runs"),
                adapters={"codex": executor, "claude-code": auditor},
                write_line=output.append,
            )
            await sidecar.handle_line(
                _command("discover", "capabilities.discover")
            )
            await sidecar.handle_line(
                _command("run", "run.start", _gui_payload())
            )
            await sidecar.wait_idle()

        messages = [json.loads(line) for line in output]
        events = [item["event"] for item in messages]
        self.assertIn("plan.warning", events)
        self.assertIn("conversation.message", events)
        self.assertIn("run.stopped", events)
        self.assertLess(
            events.index("conversation.message"),
            events.index("run.stopped"),
        )
        conversation = next(
            item for item in messages if item["event"] == "conversation.message"
        )
        self.assertEqual(
            conversation["payload"]["message"]["text"],
            "authoritative partial from codex",
        )
        self.assertTrue(conversation["payload"]["message"]["partial"])
        terminal = next(
            item for item in messages if item["event"] == "run.stopped"
        )
        self.assertEqual(terminal["payload"]["reason"], "plan-warning")
        self.assertIn(
            "subscription-usage boundary",
            terminal["payload"]["message"],
        )
        self.assertNotIn(
            "interrupt failed",
            json.dumps(messages),
        )
        self.assertNotIn("run_path", terminal["payload"])
        self.assertEqual(auditor.requests, [])


class AppServerShutdownBoundTests(unittest.TestCase):
    def test_terminate_timeout_kills_reaps_and_shares_one_reader_deadline(self):
        release = threading.Event()

        class BlockingLines:
            def __init__(self) -> None:
                self.started = threading.Event()

            def __iter__(self):
                self.started.set()
                release.wait(timeout=2)
                return
                yield ""  # pragma: no cover - makes this a blocking generator

        class Sink:
            def close(self):
                return None

        class SlowProcess:
            def __init__(self) -> None:
                self.stdin = Sink()
                self.stdout = BlockingLines()
                self.stderr = BlockingLines()
                self.terminated = False
                self.killed = False
                self.reaped = False
                self.wait_timeouts: list[float] = []

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.killed = True

            def wait(self, timeout=None):
                self.wait_timeouts.append(timeout)
                if not self.killed:
                    time.sleep(timeout)
                    raise subprocess.TimeoutExpired("codex app-server", timeout)
                self.reaped = True
                return -9

        process = SlowProcess()
        with tempfile.TemporaryDirectory() as td, patch.object(
            codex_leg.subprocess,
            "Popen",
            return_value=process,
        ), patch.object(
            codex_leg,
            "APP_SERVER_TERMINATE_TIMEOUT",
            0.03,
        ), patch.object(
            codex_leg,
            "APP_SERVER_KILL_TIMEOUT",
            0.02,
        ), patch.object(
            codex_leg,
            "APP_SERVER_READER_DRAIN_TIMEOUT",
            0.2,
        ):
            root = Path(td)
            raw = root / "raw"
            raw.mkdir()
            client = codex_leg.AppServerClient(
                ChainedLog(root / "decisions.jsonl"),
                raw,
                executable=root / "gated-codex",
            )
            self.assertTrue(process.stdout.started.wait(timeout=1))
            self.assertTrue(process.stderr.started.wait(timeout=1))

            started = time.monotonic()
            client.close()
            elapsed = time.monotonic() - started

            self.assertTrue(process.terminated)
            self.assertTrue(process.killed)
            self.assertTrue(process.reaped)
            self.assertEqual(process.wait_timeouts, [0.03, 0.02])
            # TERM plus one shared reader deadline is about 230 ms. Giving
            # both readers their own 200 ms wait would exceed this bound.
            self.assertGreaterEqual(elapsed, 0.2)
            self.assertLess(elapsed, 0.35)
            self.assertTrue((raw / "codex_events.json").is_file())
            self.assertIn("reader threads did not join", " ".join(client.fatal))

            release.set()
            client._reader.join(timeout=1)
            client._stderr.join(timeout=1)
            self.assertFalse(client._reader.is_alive())
            self.assertFalse(client._stderr.is_alive())


class CodexTurnCorrelationTests(unittest.TestCase):
    class _QuietProcess:
        """No-wire process used to initialise the real app-server client."""

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

    @staticmethod
    def _completion(thread_id: str, turn_id: str) -> dict:
        return {
            "method": "turn/completed",
            "params": {
                "threadId": thread_id,
                "turn": {"id": turn_id, "status": "completed"},
            },
        }

    def _client(self, root: Path, request: TurnRequest):
        raw_dir = root / "raw"
        raw_dir.mkdir()
        process = self._QuietProcess()
        with patch.object(
            codex_leg.subprocess,
            "Popen",
            return_value=process,
        ):
            client = codex_adapter_module._M2AppServerClient(
                ChainedLog(root / "decisions.jsonl"),
                raw_dir,
                turn_request=request,
                presenter=lambda request, card: "deny",
                activity_bridge=None,
                relay_provider_id="codex",
                executable=str(root / "gated-codex"),
            )
        client.request = lambda method, params: 17
        return client

    def test_child_completion_before_parent_does_not_satisfy_parent_waiter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _turn_request(
                PARTICIPANTS[0],
                root,
                role=Role.EXECUTOR,
                stage=TurnStage.PROPOSAL,
            )
            client = self._client(root, request)
            child = self._completion("child-thread", "child-turn")
            parent = self._completion("parent-thread", "parent-turn")
            parent_timer = threading.Timer(0.02, client._handle, args=(parent,))

            def response_for(request_id):
                self.assertEqual(request_id, 17)
                client._handle(child)
                parent_timer.start()
                return {"result": {"turn": {"id": "parent-turn"}}}

            client.response_for = response_for
            try:
                completed_turn = codex_adapter_module._start_and_wait_turn(
                    client,
                    thread_id="parent-thread",
                    request=request,
                    effort="high",
                    service_tier=None,
                    interrupt_requested=threading.Event(),
                )
                retained_child = client.wait_for_turn_completion(
                    "child-thread",
                    "child-turn",
                    timeout=0,
                )
            finally:
                parent_timer.join(timeout=1)
                client.close()

        self.assertEqual(completed_turn, "parent-turn")
        self.assertEqual(
            retained_child,
            {"id": "child-turn", "status": "completed"},
        )

    def test_m1_waiter_uses_the_same_parent_correlation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _turn_request(
                PARTICIPANTS[0],
                root,
                role=Role.EXECUTOR,
                stage=TurnStage.PROPOSAL,
            )
            client = self._client(root, request)
            child = self._completion("child-thread", "child-turn")
            parent = self._completion("parent-thread", "parent-turn")
            parent_timer = threading.Timer(0.02, client._handle, args=(parent,))

            def response_for(request_id):
                self.assertEqual(request_id, 17)
                client._handle(child)
                parent_timer.start()
                return {"result": {"turn": {"id": "parent-turn"}}}

            client.response_for = response_for
            try:
                completed_turn = codex_leg._run_turn(
                    client,
                    "parent-thread",
                    "test parent correlation",
                )
            finally:
                parent_timer.join(timeout=1)
                client.close()

        self.assertEqual(completed_turn, "parent-turn")

    def test_parent_completion_before_waiter_registration_is_retained(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _turn_request(
                PARTICIPANTS[0],
                root,
                role=Role.EXECUTOR,
                stage=TurnStage.PROPOSAL,
            )
            client = self._client(root, request)
            parent = self._completion("parent-thread", "parent-turn")

            def response_for(request_id):
                self.assertEqual(request_id, 17)
                # The notification is handled before turn/start's response is
                # returned, so the exact waiter key is not known yet.
                client._handle(parent)
                return {"result": {"turn": {"id": "parent-turn"}}}

            client.response_for = response_for
            try:
                completed_turn = codex_adapter_module._start_and_wait_turn(
                    client,
                    thread_id="parent-thread",
                    request=request,
                    effort="high",
                    service_tier=None,
                    interrupt_requested=threading.Event(),
                )
            finally:
                client.close()

        self.assertEqual(completed_turn, "parent-turn")


class LiveAdapterRuntimeCorrectionTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _claude_server_info() -> dict:
        return {
            "models": [
                {
                    "value": "claude-code-model",
                    "displayName": "Claude test model",
                    "resolvedModel": "claude-code-model",
                    "supportedEffortLevels": ["high"],
                }
            ]
        }

    async def test_claude_failure_retains_authoritative_partial_text(self):
        class FakeClaudeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get_server_info(self):
                return LiveAdapterRuntimeCorrectionTests._claude_server_info()

            async def query(self, text):
                self.query_text = text

            async def receive_response(self):
                yield AssistantMessage(
                    content=[TextBlock("Claude authoritative partial")],
                    model="claude-code-model",
                )
                raise RuntimeError("provider stream failed after output")

            async def interrupt(self):
                return None

            async def disconnect(self):
                return None

        fake = FakeClaudeClient()
        with tempfile.TemporaryDirectory() as td, patch.object(
            claude_adapter_module,
            "gated_claude_runtime",
            return_value=(
                Path("/tmp/fake-claude"),
                {
                    "subscription_type": "pro",
                    "api_provider": "firstParty",
                },
                "test-version",
            ),
        ), patch.object(
            claude_adapter_module,
            "ClaudeSDKClient",
            side_effect=lambda **kwargs: fake,
        ):
            request = _turn_request(
                PARTICIPANTS[1],
                Path(td),
                role=Role.AUDITOR,
                stage=TurnStage.AUDIT,
            )
            with self.assertRaises(AdapterError) as raised:
                await claude_adapter_module.ClaudeCodeRuntimeAdapter(
                    lambda request, card: "deny"
                ).run_turn(request, CancellationToken())

        partial = raised.exception.partial_result
        self.assertIsNotNone(partial)
        self.assertEqual(partial.text, "Claude authoritative partial")
        self.assertEqual(
            [(block.type, block.text) for block in partial.blocks],
            [("markdown", "Claude authoritative partial")],
        )
        self.assertEqual(
            partial.model_profile.effective.model_id,
            "claude-code-model",
        )

    async def test_claude_clean_eof_without_result_is_failed_with_partial(self):
        class CleanEofClaudeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get_server_info(self):
                return LiveAdapterRuntimeCorrectionTests._claude_server_info()

            async def query(self, text):
                self.query_text = text

            async def receive_response(self):
                yield AssistantMessage(
                    content=[TextBlock("Claude partial before clean EOF")],
                    model="claude-code-model",
                )

            async def interrupt(self):
                return None

            async def disconnect(self):
                return None

        fake = CleanEofClaudeClient()
        with tempfile.TemporaryDirectory() as td, patch.object(
            claude_adapter_module,
            "gated_claude_runtime",
            return_value=(
                Path("/tmp/fake-claude"),
                {
                    "subscription_type": "pro",
                    "api_provider": "firstParty",
                },
                "test-version",
            ),
        ), patch.object(
            claude_adapter_module,
            "ClaudeSDKClient",
            side_effect=lambda **kwargs: fake,
        ):
            request = _turn_request(
                PARTICIPANTS[1],
                Path(td),
                role=Role.AUDITOR,
                stage=TurnStage.AUDIT,
            )
            with self.assertRaisesRegex(
                AdapterError,
                "without a terminal ResultMessage",
            ) as raised:
                await claude_adapter_module.ClaudeCodeRuntimeAdapter(
                    lambda request, card: "deny"
                ).run_turn(request, CancellationToken())

        partial = raised.exception.partial_result
        self.assertIsNotNone(partial)
        self.assertEqual(partial.text, "Claude partial before clean EOF")
        self.assertEqual(
            [(block.type, block.text) for block in partial.blocks],
            [("markdown", "Claude partial before clean EOF")],
        )

    async def test_claude_stop_during_catalog_gate_never_submits_query(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        class Presenter:
            def __init__(self):
                self.failed = []

            def __call__(self, request, card):
                return "deny"

            def fail_pending(self, reason):
                self.failed.append(reason)

        class FakeClaudeClient:
            def __init__(self):
                self.query_count = 0
                self.interrupt_count = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get_server_info(self):
                entered.set()
                await release.wait()
                return LiveAdapterRuntimeCorrectionTests._claude_server_info()

            async def query(self, text):
                self.query_count += 1

            async def receive_response(self):
                if False:
                    yield None

            async def interrupt(self):
                self.interrupt_count += 1

            async def disconnect(self):
                return None

        fake = FakeClaudeClient()
        presenter = Presenter()
        token = CancellationToken()
        with tempfile.TemporaryDirectory() as td, patch.object(
            claude_adapter_module,
            "gated_claude_runtime",
            return_value=(
                Path("/tmp/fake-claude"),
                {
                    "subscription_type": "pro",
                    "api_provider": "firstParty",
                },
                "test-version",
            ),
        ), patch.object(
            claude_adapter_module,
            "ClaudeSDKClient",
            side_effect=lambda **kwargs: fake,
        ):
            request = _turn_request(
                PARTICIPANTS[1],
                Path(td),
                role=Role.AUDITOR,
                stage=TurnStage.AUDIT,
            )
            task = asyncio.create_task(
                claude_adapter_module.ClaudeCodeRuntimeAdapter(
                    presenter
                ).run_turn(request, token)
            )
            await asyncio.wait_for(entered.wait(), timeout=2)
            token.cancel("parallel plan warning")
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(TurnInterrupted):
                await asyncio.wait_for(task, timeout=2)

        self.assertEqual(fake.query_count, 0)
        self.assertEqual(fake.interrupt_count, 1)
        self.assertEqual(
            presenter.failed,
            ["run stopped while permission card was open"],
        )

    async def test_codex_failure_retains_partial_and_ephemeral_evidence(self):
        instances = []

        class FakeCodexClient:
            def __init__(self, *args, **kwargs):
                self.rate_limit_events = []
                self.rate_limit_stop = None
                self.fatal = []
                instances.append(self)

            def close(self):
                self.fatal.append("provider reader failed after output")

        row = {
            "id": "codex-model",
            "model": "codex-model",
            "displayName": "Codex test model",
            "isDefault": True,
            "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
        }
        thread = {
            "thread": {"id": "opaque-thread", "ephemeral": True},
            "modelProvider": "openai",
            "model": "codex-model",
            "serviceTier": None,
        }
        with tempfile.TemporaryDirectory() as td, patch.object(
            codex_adapter_module.gates,
            "assert_codex_version",
            return_value={"executable": "/tmp/fake-codex"},
        ), patch.object(
            codex_adapter_module,
            "_M2AppServerClient",
            FakeCodexClient,
        ), patch.object(
            codex_adapter_module,
            "_handshake",
        ), patch.object(
            codex_adapter_module,
            "_certify_subscription_route",
            return_value=({"planType": "plus"}, "plus", False, None),
        ), patch.object(
            codex_adapter_module,
            "_catalog_rows",
            return_value=[row],
        ), patch.object(
            codex_adapter_module,
            "_start_selected_thread",
            return_value=("opaque-thread", thread),
        ), patch.object(
            codex_adapter_module,
            "_start_turn",
            return_value="opaque-turn",
        ), patch.object(
            codex_adapter_module,
            "_wait_for_turn",
        ), patch.object(
            codex_adapter_module,
            "_bound_items",
            return_value=[
                {"type": "agentMessage", "text": "Codex authoritative partial"},
                {"id": "compact-1", "type": "contextCompaction"},
            ],
        ), patch.object(
            codex_adapter_module,
            "_audit_items",
        ):
            request = _turn_request(
                PARTICIPANTS[0],
                Path(td),
                role=Role.EXECUTOR,
                stage=TurnStage.PROPOSAL,
            )
            with self.assertRaises(AdapterError) as raised:
                codex_adapter_module.CodexRuntimeAdapter(
                    lambda request, card: "deny"
                )._run_turn_sync(request)

        partial = raised.exception.partial_result
        self.assertIsNotNone(partial)
        self.assertEqual(partial.text, "Codex authoritative partial")
        self.assertEqual(
            [(block.type, block.text) for block in partial.blocks],
            [("markdown", "Codex authoritative partial")],
        )
        self.assertIn(("thread_ephemeral", "true"), partial.evidence)
        self.assertIn(
            ("native_compaction_event_count", "1"),
            partial.evidence,
        )
        self.assertIn(
            ("native_compaction_topic_checkpoint_mutated", "false"),
            partial.evidence,
        )
        self.assertEqual(len(instances), 1)

    async def test_codex_positive_credit_balance_allows_native_subscription_turn(
        self,
    ):
        """Optional post-limit credits must not block an in-limit Plus turn."""

        starts = []
        priority_policy = []

        class FakeCodexClient:
            def __init__(self, *args, **kwargs):
                self.rate_limit_events = []
                self.rate_limit_stop = None
                self.fatal = []

            def close(self):
                return None

        row = {
            "id": "codex-model",
            "model": "codex-model",
            "displayName": "Codex test model",
            "isDefault": True,
            "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
            "serviceTiers": [
                {
                    "id": "priority",
                    "name": "Fast",
                    "description": "Higher consumption rate",
                }
            ],
        }
        thread = {
            "thread": {"id": "opaque-thread", "ephemeral": True},
            "modelProvider": "openai",
            "model": "codex-model",
            "serviceTier": None,
        }
        real_normalize = codex_adapter_module.codex_capabilities_from_model_list

        def normalize(rows, **kwargs):
            priority_policy.append(kwargs["priority_within_subscription"])
            return real_normalize(
                rows,
                runtime_version=kwargs["runtime_version"],
                account_route=kwargs["account_route"],
                priority_within_subscription=kwargs[
                    "priority_within_subscription"
                ],
            )

        def start_thread(_client, _request, selected_model, service_tier):
            starts.append(("thread", selected_model, service_tier))
            return "opaque-thread", thread

        def start_turn(
            _client,
            *,
            thread_id,
            request,
            effort,
            service_tier,
        ):
            starts.append(("turn", thread_id, service_tier))
            return "opaque-turn"

        with tempfile.TemporaryDirectory() as td, patch.object(
            codex_adapter_module.gates,
            "assert_codex_version",
            return_value={"executable": "/tmp/fake-codex"},
        ), patch.object(
            codex_adapter_module,
            "_M2AppServerClient",
            FakeCodexClient,
        ), patch.object(
            codex_adapter_module,
            "_handshake",
        ), patch.object(
            codex_adapter_module,
            "_certify_subscription_route",
            return_value=({"planType": "plus"}, "plus", True, None),
        ), patch.object(
            codex_adapter_module,
            "_catalog_rows",
            return_value=[row],
        ), patch.object(
            codex_adapter_module,
            "codex_capabilities_from_model_list",
            side_effect=normalize,
        ), patch.object(
            codex_adapter_module,
            "_start_selected_thread",
            side_effect=start_thread,
        ), patch.object(
            codex_adapter_module,
            "_start_turn",
            side_effect=start_turn,
        ), patch.object(
            codex_adapter_module,
            "_wait_for_turn",
        ), patch.object(
            codex_adapter_module,
            "_bound_items",
            return_value=[
                {"type": "agentMessage", "text": "Subscription turn completed"}
            ],
        ), patch.object(
            codex_adapter_module,
            "_audit_items",
        ):
            request = _turn_request(
                PARTICIPANTS[0],
                Path(td),
                role=Role.EXECUTOR,
                stage=TurnStage.PROPOSAL,
            )
            result = codex_adapter_module.CodexRuntimeAdapter(
                lambda request, card: "deny"
            )._run_turn_sync(request)

        self.assertEqual(result.text, "Subscription turn completed")
        self.assertEqual(result.account_route, "chatgpt:plus")
        self.assertIn(
            ("purchased_credit_spend_available", "true"),
            result.evidence,
        )
        self.assertEqual(priority_policy, [False])
        self.assertEqual(
            starts,
            [
                ("thread", "codex-model", None),
                ("turn", "opaque-thread", None),
            ],
        )

    async def test_codex_stop_during_catalog_gate_never_starts_thread_or_turn(self):
        entered = threading.Event()
        release = threading.Event()
        starts: list[str] = []

        class Presenter:
            def __init__(self):
                self.failed = []

            def __call__(self, request, card):
                return "deny"

            def fail_pending(self, reason):
                self.failed.append(reason)

        class FakeCodexClient:
            def __init__(self, *args, **kwargs):
                self.rate_limit_events = []
                self.rate_limit_stop = None
                self.fatal = []

            def close(self):
                return None

        def catalog(_client):
            entered.set()
            release.wait(timeout=2)
            return [
                {
                    "id": "codex-model",
                    "model": "codex-model",
                    "displayName": "Codex test model",
                    "isDefault": True,
                    "supportedReasoningEfforts": [
                        {"reasoningEffort": "high"}
                    ],
                }
            ]

        def start_thread(*args, **kwargs):
            starts.append("thread")
            return "opaque-thread", {}

        def start_turn(*args, **kwargs):
            starts.append("turn")
            return "opaque-turn"

        presenter = Presenter()
        token = CancellationToken()
        with tempfile.TemporaryDirectory() as td, patch.object(
            codex_adapter_module.gates,
            "assert_codex_version",
            return_value={"executable": "/tmp/fake-codex"},
        ), patch.object(
            codex_adapter_module,
            "_M2AppServerClient",
            FakeCodexClient,
        ), patch.object(
            codex_adapter_module,
            "_handshake",
        ), patch.object(
            codex_adapter_module,
            "_certify_subscription_route",
            return_value=({"planType": "plus"}, "plus", False, None),
        ), patch.object(
            codex_adapter_module,
            "_catalog_rows",
            side_effect=catalog,
        ), patch.object(
            codex_adapter_module,
            "_start_selected_thread",
            side_effect=start_thread,
        ), patch.object(
            codex_adapter_module,
            "_start_turn",
            side_effect=start_turn,
        ), patch.object(
            codex_adapter_module,
            "_wait_for_turn",
        ), patch.object(
            codex_adapter_module,
            "_audit_items",
        ):
            request = _turn_request(
                PARTICIPANTS[0],
                Path(td),
                role=Role.EXECUTOR,
                stage=TurnStage.PROPOSAL,
            )
            task = asyncio.create_task(
                codex_adapter_module.CodexRuntimeAdapter(
                    presenter
                ).run_turn(request, token)
            )
            self.assertTrue(
                await asyncio.to_thread(entered.wait, 2),
                "Codex catalog gate did not start",
            )
            token.cancel("parallel plan warning")
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(TurnInterrupted):
                await asyncio.wait_for(task, timeout=2)

        self.assertEqual(starts, [])
        self.assertEqual(
            presenter.failed,
            ["run stopped while permission card was open"],
        )

    async def test_plan_warning_releases_another_auditors_open_card(self):
        card_open = threading.Event()
        card_released = threading.Event()

        class BlockingPresenter:
            def __init__(self):
                self.failure_reason = None

            def __call__(self, request, card):
                return "deny"

            def wait_on_card(self):
                card_open.set()
                if not card_released.wait(timeout=2):
                    raise RuntimeError("permission card remained blocked")
                raise AdapterError(self.failure_reason or "card failed closed")

            def fail_pending(self, reason):
                self.failure_reason = reason
                card_released.set()

        executor = _participant(
            "executor-google", "synthetic-google-cli", "google", "synthetic-google-cli"
        )
        codex_auditor = _participant(
            "auditor-openai", "codex", Vendor.OPENAI, AgentSystem.CODEX
        )
        warning_auditor = _participant(
            "auditor-anthropic",
            "claude-code",
            Vendor.ANTHROPIC,
            AgentSystem.CLAUDE_CODE,
        )
        presenter = BlockingPresenter()
        blocked = codex_adapter_module.CodexRuntimeAdapter(presenter)

        def blocked_turn(request, cancellation):
            presenter.wait_on_card()

        blocked._run_turn_sync = blocked_turn

        class WarningAdapter(_ScriptedAdapter):
            async def run_turn(self, request, cancellation):
                await asyncio.to_thread(card_open.wait, 2)
                raise PlanUsageWarning("subscription boundary reached")

        config = RunConfig.fixed_roles(
            prompt="Cross-examine safely.",
            participants=(executor, codex_auditor, warning_auditor),
            executor_id=executor.participant_id,
            auditor_ids=(
                codex_auditor.participant_id,
                warning_auditor.participant_id,
            ),
            rounds=1,
        )
        with tempfile.TemporaryDirectory() as td:
            outcome = await asyncio.wait_for(
                DialecticOrchestrator(
                    store=RunStore(Path(td) / "runs"),
                    adapters={
                        "synthetic-google-cli": _ScriptedAdapter("synthetic-google-cli"),
                        "codex": blocked,
                        "claude-code": WarningAdapter("claude-code"),
                    },
                ).run(config, run_id="plan-warning-open-card"),
                timeout=3,
            )

        self.assertEqual(outcome.status, RunStatus.CANCELLED)
        self.assertTrue(card_open.is_set())
        self.assertTrue(card_released.is_set())
        self.assertEqual(
            presenter.failure_reason,
            "run stopped while permission card was open",
        )


class RuntimeAdapterGateTests(unittest.IsolatedAsyncioTestCase):
    GATE_TEXT = "ABORT: deterministic subscription gate (fail closed)"

    async def test_live_adapters_promote_only_system_exit_gate_verdicts(self):
        with patch.object(
            claude_adapter_module,
            "gated_claude_runtime",
            side_effect=SystemExit(self.GATE_TEXT),
        ):
            with self.assertRaisesRegex(
                RuntimeGateError,
                "deterministic subscription gate",
            ):
                await claude_adapter_module.discover_claude_capabilities()
            with self.assertRaisesRegex(
                RuntimeGateError,
                "deterministic subscription gate",
            ):
                await claude_adapter_module.ClaudeCodeRuntimeAdapter(
                    lambda request, card: "deny"
                ).run_turn(object(), object())

        with patch.object(
            codex_adapter_module.gates,
            "assert_codex_version",
            side_effect=SystemExit(self.GATE_TEXT),
        ):
            with self.assertRaisesRegex(
                RuntimeGateError,
                "deterministic subscription gate",
            ):
                await codex_adapter_module.discover_codex_capabilities()
            with self.assertRaisesRegex(
                RuntimeGateError,
                "deterministic subscription gate",
            ):
                codex_adapter_module.CodexRuntimeAdapter(
                    lambda request, card: "deny"
                )._run_turn_sync(object())

    def test_codex_account_and_rate_failures_use_fixed_public_verdicts(self):
        class AccountFailureClient:
            def request(self, method, params):
                return method

            def response_for(self, request_id):
                return {
                    "result": {
                        "account": {
                            "type": "api",
                            "planType": "unknown",
                        }
                    }
                }

        with self.assertRaises(RuntimeGateError) as account_failure:
            codex_adapter_module._certify_subscription_route(
                AccountFailureClient()
            )
        self.assertEqual(
            str(account_failure.exception),
            codex_adapter_module.CODEX_ACCOUNT_GATE_ABORT,
        )

        class RateFailureClient:
            def request(self, method, params):
                return method

            def response_for(self, request_id):
                if request_id == "account/read":
                    return {
                        "result": {
                            "account": {
                                "type": "chatgpt",
                                "planType": "plus",
                            }
                        }
                    }
                return {
                    "result": {
                        "rateLimits": {
                            "planType": "plus",
                            "credits": "PRIVATE MALFORMED PROVIDER DATA",
                        }
                    }
                }

        with self.assertRaises(RuntimeGateError) as rate_failure:
            codex_adapter_module._certify_subscription_route(
                RateFailureClient()
            )
        self.assertEqual(
            str(rate_failure.exception),
            codex_adapter_module.CODEX_RATE_GATE_ABORT,
        )
        self.assertNotIn(
            "PRIVATE MALFORMED PROVIDER DATA",
            str(rate_failure.exception),
        )


class SidecarGateVisibilityTests(unittest.IsolatedAsyncioTestCase):
    GATE_TEXT = (
        "ABORT: auth is not first-party claude.ai subscription "
        "(fail closed)"
    )

    async def test_discovery_displays_only_the_authored_runtime_gate_verdict(self):
        gate_text = self.GATE_TEXT

        class GateAdapter(_ScriptedAdapter):
            async def discover_capabilities(self) -> AdapterCapabilities:
                raise RuntimeGateError(gate_text)

        output: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            runs_root = Path(td) / "runs"
            sidecar = JsonlSidecar(
                store=RunStore(runs_root),
                adapters={
                    "codex": _ScriptedAdapter("codex"),
                    "claude-code": GateAdapter("claude-code"),
                },
                write_line=output.append,
            )
            await sidecar.handle_line(
                _command("discover", "capabilities.discover")
            )
            diagnostic = runs_root / "sidecar-diagnostics.jsonl"
            diagnostic_text = diagnostic.read_text()
            diagnostic_mode = stat.S_IMODE(diagnostic.stat().st_mode)

        messages = [json.loads(line) for line in output]
        self.assertEqual(len(messages), 1)
        failure = messages[0]
        self.assertEqual(failure["event"], "capabilities.result")
        self.assertEqual(failure["request_id"], "discover")
        unavailable = next(
            item
            for item in failure["payload"]["providers"]
            if item["runtime_id"] == "claude-code"
        )
        self.assertEqual(
            unavailable["availability"]["reason"],
            self.GATE_TEXT,
        )
        self.assertNotEqual(
            unavailable["availability"]["reason"],
            SAFE_COMMAND_FAILURE,
        )
        self.assertIn(self.GATE_TEXT, diagnostic_text)
        self.assertEqual(diagnostic_mode, 0o600)

    async def test_broad_capability_failure_remains_owner_only(self):
        private_detail = (
            "SECRET catalog response at /Users/live/private/catalog.json"
        )

        class CatalogFailureAdapter(_ScriptedAdapter):
            async def discover_capabilities(self) -> AdapterCapabilities:
                raise CapabilityError(private_detail)

        output: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            runs_root = Path(td) / "runs"
            sidecar = JsonlSidecar(
                store=RunStore(runs_root),
                adapters={
                    "codex": _ScriptedAdapter("codex"),
                    "claude-code": CatalogFailureAdapter("claude-code"),
                },
                write_line=output.append,
            )
            await sidecar.handle_line(
                _command("discover", "capabilities.discover")
            )
            diagnostic_text = (
                runs_root / "sidecar-diagnostics.jsonl"
            ).read_text()

        serialized = json.dumps([json.loads(line) for line in output])
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("/Users/live/private", serialized)
        failure = json.loads(output[-1])
        unavailable = next(
            item
            for item in failure["payload"]["providers"]
            if item["runtime_id"] == "claude-code"
        )
        self.assertEqual(
            unavailable["availability"]["reason"],
            "Runtime discovery failed safely. Full diagnostics remain owner-only.",
        )
        self.assertIn(private_detail, diagnostic_text)

    async def test_turn_gate_survives_failed_outcome_and_reaches_the_gui(self):
        gate_text = self.GATE_TEXT

        class GateAdapter(_ScriptedAdapter):
            async def run_turn(self, request, cancellation) -> TurnResult:
                raise RuntimeGateError(gate_text)

        output: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            runs_root = Path(td) / "runs"
            sidecar = JsonlSidecar(
                store=RunStore(runs_root),
                adapters={
                    "codex": GateAdapter("codex"),
                    "claude-code": _ScriptedAdapter("claude-code"),
                },
                write_line=output.append,
            )
            await sidecar.handle_line(
                _command("discover", "capabilities.discover")
            )
            await sidecar.handle_line(
                _command("run", "run.start", _gui_payload())
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

        failure = next(
            item for item in messages if item["event"] == "run.failed"
        )
        self.assertEqual(
            failure["payload"]["message"],
            f"The run stopped before execution: {self.GATE_TEXT}",
        )
        self.assertNotEqual(
            failure["payload"]["message"],
            SAFE_RUN_FAILURE,
        )
        self.assertIn(self.GATE_TEXT, transcript["failure"])

    async def test_arbitrary_turn_failure_remains_masked_and_owner_only(self):
        private_detail = (
            "SECRET provider diagnostic at /Users/live/private"
        )

        class ExplodingAdapter(_ScriptedAdapter):
            async def run_turn(self, request, cancellation) -> TurnResult:
                raise AdapterError(private_detail)

        output: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            runs_root = Path(td) / "runs"
            sidecar = JsonlSidecar(
                store=RunStore(runs_root),
                adapters={
                    "codex": ExplodingAdapter("codex"),
                    "claude-code": _ScriptedAdapter("claude-code"),
                },
                write_line=output.append,
            )
            await sidecar.handle_line(
                _command("discover", "capabilities.discover")
            )
            await sidecar.handle_line(
                _command("run", "run.start", _gui_payload())
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

        serialized = json.dumps(messages)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("/Users/live/private", serialized)
        failure = next(
            item for item in messages if item["event"] == "run.failed"
        )
        self.assertEqual(
            failure["payload"]["message"],
            SAFE_RUN_FAILURE,
        )
        self.assertIn(private_detail, transcript["failure"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
