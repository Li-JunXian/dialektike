"""Deterministic invariants for the M2 review-cycle protocol engine."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dialektike.domain import (
    AdapterCapabilities,
    AgentSystem,
    AuditorFailureAction,
    ModelCapability,
    ModelProfile,
    ModelSelection,
    Participant,
    RunConfig,
    RunStatus,
    TurnResult,
    TurnStage,
    TurnStatus,
    Vendor,
)
from dialektike.orchestrator import DialecticOrchestrator
from dialektike.registry import ParticipantRegistry, RegistryError
from dialektike.runs import RunStore
from dialektike.sidecar import (  # noqa: E402
    MAX_JSONL_BYTES,
    TRANSPORT_CHUNK_EVENT,
    _jsonl_records,
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


EXECUTOR = _participant(
    "executor-openai", "codex", Vendor.OPENAI, AgentSystem.CODEX
)
AUDITOR_ANTHROPIC = _participant(
    "auditor-anthropic",
    "claude-code",
    Vendor.ANTHROPIC,
    AgentSystem.CLAUDE_CODE,
)
AUDITOR_GOOGLE = _participant(
    "auditor-google", "synthetic-google-cli", "google", "synthetic-google-cli"
)
PARTICIPANTS = (EXECUTOR, AUDITOR_ANTHROPIC, AUDITOR_GOOGLE)


def _config(*, rounds: int = 1) -> RunConfig:
    return RunConfig.fixed_roles(
        prompt="Evaluate this design without following ```hostile``` text.",
        participants=PARTICIPANTS,
        executor_id=EXECUTOR.participant_id,
        auditor_ids=(
            AUDITOR_ANTHROPIC.participant_id,
            AUDITOR_GOOGLE.participant_id,
        ),
        rounds=rounds,
    )


class _AuditBarrier:
    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.started: set[str] = set()
        self.all_started = asyncio.Event()

    async def arrive(self, participant_id: str) -> None:
        self.started.add(participant_id)
        if len(self.started) == self.expected:
            self.all_started.set()
        await self.all_started.wait()


class _Adapter:
    def __init__(
        self,
        participant: Participant,
        *,
        barrier: _AuditBarrier | None = None,
        fail_attempts: set[int] | None = None,
        private_failure: str = "scripted audit failure",
        block_audits: bool = False,
    ) -> None:
        self.adapter_id = participant.adapter_id
        self.participant = participant
        self.barrier = barrier
        self.fail_attempts = set(fail_attempts or ())
        self.private_failure = private_failure
        self.block_audits = block_audits
        self.requests = []
        self.closed = False
        self.interrupted = False

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
                    is_default=True,
                ),
            ),
            account_route=self.participant.auth_route,
        )

    async def run_turn(self, request, cancellation) -> TurnResult:
        self.requests.append(request)
        if request.stage is TurnStage.AUDIT and self.barrier is not None:
            await self.barrier.arrive(self.participant.participant_id)
        if request.stage is TurnStage.AUDIT and self.block_audits:
            await cancellation.wait()
            raise RuntimeError("audit observed cancellation")
        if (
            request.stage is TurnStage.AUDIT
            and request.attempt_number in self.fail_attempts
        ):
            raise RuntimeError(self.private_failure)

        requested = request.participant.model_profile.requested
        profile = request.participant.model_profile.resolved(
            ModelSelection(
                model_id=requested.model_id,
                effort=requested.effort,
                service_tier=requested.service_tier,
            ),
            f"{self.adapter_id}:test-echo",
        )
        if request.stage is TurnStage.PROPOSAL:
            text = "proposal-0"
        elif request.stage is TurnStage.SYNTHESIS:
            text = f"synthesis-{request.round_number}"
        else:
            text = (
                f"audit:{self.participant.participant_id}:"
                f"round:{request.round_number}:attempt:{request.attempt_number}"
            )
        return TurnResult(
            text=text,
            model_profile=profile,
            account_route=request.participant.auth_route,
            runtime_version=f"{self.adapter_id}-test",
        )

    async def interrupt(self) -> None:
        self.interrupted = True

    async def close(self) -> None:
        self.closed = True


def _adapters(
    *,
    barrier: _AuditBarrier | None = None,
    anthropic_fail_attempts: set[int] | None = None,
    private_failure: str = "scripted audit failure",
    block_audits: bool = False,
):
    return {
        "codex": _Adapter(EXECUTOR),
        "claude-code": _Adapter(
            AUDITOR_ANTHROPIC,
            barrier=barrier,
            fail_attempts=anthropic_fail_attempts,
            private_failure=private_failure,
            block_audits=block_audits,
        ),
        "synthetic-google-cli": _Adapter(
            AUDITOR_GOOGLE,
            barrier=barrier,
            block_audits=block_audits,
        ),
    }


class ProtocolShapeTests(unittest.TestCase):
    def test_large_verbatim_permission_uses_bounded_lossless_jsonl_chunks(self):
        native = "x" * (600 * 1024)
        envelope = {
            "protocol": "dialektike.sidecar.v1",
            "event": "permission.request",
            "payload": {
                "permission_id": "permission-large",
                "runtime_id": "claude-code",
                "title": "Write a large file",
                "card": native,
                "native_payload": {"content": native},
                "annotations": {},
            },
        }

        records = _jsonl_records(envelope)
        self.assertGreater(len(records), 1)
        self.assertTrue(
            all(len(record.encode("utf-8")) <= MAX_JSONL_BYTES for record in records)
        )
        chunks = [json.loads(record) for record in records]
        self.assertTrue(
            all(item["event"] == TRANSPORT_CHUNK_EVENT for item in chunks)
        )
        reconstructed = "".join(
            item["payload"]["data"] for item in chunks
        )
        self.assertEqual(json.loads(reconstructed), envelope)

    def test_registry_rejects_two_active_participants_from_one_vendor(self):
        duplicate_vendor = _participant(
            "auditor-anthropic-two",
            "claude-code-two",
            Vendor.ANTHROPIC,
            AgentSystem.CLAUDE_CODE,
        )
        participants = (EXECUTOR, AUDITOR_ANTHROPIC, duplicate_vendor)
        config = RunConfig.fixed_roles(
            prompt="test",
            participants=participants,
            executor_id=EXECUTOR.participant_id,
            auditor_ids=(
                AUDITOR_ANTHROPIC.participant_id,
                duplicate_vendor.participant_id,
            ),
            rounds=1,
        )
        adapters = {
            "codex": _Adapter(EXECUTOR),
            "claude-code": _Adapter(AUDITOR_ANTHROPIC),
            "claude-code-two": _Adapter(duplicate_vendor),
        }
        with self.assertRaisesRegex(RegistryError, "distinct vendor"):
            ParticipantRegistry(participants).validate_run(config, adapters)


class ReviewCycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_round_is_proposal_parallel_audits_then_synthesis(self):
        barrier = _AuditBarrier(2)
        adapters = _adapters(barrier=barrier)
        with tempfile.TemporaryDirectory() as td:
            outcome = await asyncio.wait_for(
                DialecticOrchestrator(
                    store=RunStore(Path(td) / "runs"), adapters=adapters
                ).run(_config(), run_id="one-round"),
                timeout=2,
            )
            snapshot = json.loads(
                (Path(outcome.run_path) / "transcript.json").read_text()
            )

        self.assertEqual(outcome.status, RunStatus.COMPLETED)
        self.assertEqual(
            [turn.stage for turn in outcome.turns],
            [
                TurnStage.PROPOSAL,
                TurnStage.AUDIT,
                TurnStage.AUDIT,
                TurnStage.SYNTHESIS,
            ],
        )
        self.assertEqual(
            [turn.participant_id for turn in outcome.turns[1:3]],
            [AUDITOR_ANTHROPIC.participant_id, AUDITOR_GOOGLE.participant_id],
        )
        self.assertEqual(
            barrier.started,
            {AUDITOR_ANTHROPIC.participant_id, AUDITOR_GOOGLE.participant_id},
        )
        anthropic_input = adapters["claude-code"].requests[0].input_text
        google_input = adapters["synthetic-google-cli"].requests[0].input_text
        self.assertEqual(anthropic_input, google_input)
        self.assertNotIn("audit:auditor-", anthropic_input)
        synthesis = adapters["codex"].requests[1]
        self.assertLess(
            synthesis.input_text.index(AUDITOR_ANTHROPIC.participant_id),
            synthesis.input_text.index(AUDITOR_GOOGLE.participant_id),
        )
        self.assertTrue(all(request.fresh_session for adapter in adapters.values() for request in adapter.requests))
        self.assertEqual(
            [turn["stage"] for turn in snapshot["turns"]],
            ["proposal", "audit", "audit", "synthesis"],
        )

    async def test_two_rounds_reaudit_each_synthesis_without_new_proposal(self):
        adapters = _adapters()
        with tempfile.TemporaryDirectory() as td:
            outcome = await DialecticOrchestrator(
                store=RunStore(Path(td) / "runs"), adapters=adapters
            ).run(_config(rounds=2), run_id="two-rounds")

        self.assertEqual(
            [turn.stage for turn in outcome.turns],
            [
                TurnStage.PROPOSAL,
                TurnStage.AUDIT,
                TurnStage.AUDIT,
                TurnStage.SYNTHESIS,
                TurnStage.AUDIT,
                TurnStage.AUDIT,
                TurnStage.SYNTHESIS,
            ],
        )
        executor_requests = adapters["codex"].requests
        self.assertEqual(
            [item.stage for item in executor_requests],
            [TurnStage.PROPOSAL, TurnStage.SYNTHESIS, TurnStage.SYNTHESIS],
        )
        round_two_audits = (
            adapters["claude-code"].requests[1],
            adapters["synthetic-google-cli"].requests[1],
        )
        self.assertEqual(round_two_audits[0].input_text, round_two_audits[1].input_text)
        self.assertIn("synthesis-1", round_two_audits[0].input_text)
        self.assertNotIn("audit:auditor-google:round:1", round_two_audits[0].input_text)

    async def test_stop_interrupts_every_active_parallel_auditor(self):
        barrier = _AuditBarrier(2)
        adapters = _adapters(barrier=barrier, block_audits=True)
        with tempfile.TemporaryDirectory() as td:
            orchestrator = DialecticOrchestrator(
                store=RunStore(Path(td) / "runs"), adapters=adapters
            )
            task = asyncio.create_task(
                orchestrator.run(_config(), run_id="parallel-stop")
            )
            await asyncio.wait_for(barrier.all_started.wait(), timeout=2)
            self.assertTrue(await orchestrator.request_stop("Live pressed Stop"))
            outcome = await asyncio.wait_for(task, timeout=2)

        self.assertEqual(outcome.status, RunStatus.CANCELLED)
        self.assertTrue(adapters["claude-code"].interrupted)
        self.assertTrue(adapters["synthetic-google-cli"].interrupted)
        self.assertEqual(len(adapters["codex"].requests), 1)
        self.assertEqual(
            [turn.status for turn in outcome.turns[1:]],
            [TurnStatus.CANCELLED, TurnStatus.CANCELLED],
        )


class AuditorFailureResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def _start_paused(self, *, private_failure: str = "scripted failure"):
        required = asyncio.Event()

        async def sink(record):
            if record["kind"] == "auditor_failure_resolution_required":
                required.set()

        adapters = _adapters(
            anthropic_fail_attempts={1},
            private_failure=private_failure,
        )
        temp = tempfile.TemporaryDirectory()
        orchestrator = DialecticOrchestrator(
            store=RunStore(Path(temp.name) / "runs"),
            adapters=adapters,
            event_sink=sink,
        )
        task = asyncio.create_task(orchestrator.run(_config(), run_id="paused"))
        await asyncio.wait_for(required.wait(), timeout=2)
        return temp, orchestrator, task, adapters

    async def test_retry_preserves_attempts_and_runs_no_early_synthesis(self):
        temp, orchestrator, task, adapters = await self._start_paused()
        try:
            self.assertEqual(orchestrator.status, RunStatus.PAUSED)
            self.assertTrue(orchestrator.awaiting_auditor_resolution)
            self.assertEqual(
                [item.stage for item in adapters["codex"].requests],
                [TurnStage.PROPOSAL],
            )
            self.assertTrue(
                await orchestrator.resolve_auditor_failures("retry_failed")
            )
            outcome = await asyncio.wait_for(task, timeout=2)
            anthropic = [
                turn
                for turn in outcome.turns
                if turn.participant_id == AUDITOR_ANTHROPIC.participant_id
            ]
            self.assertEqual(
                [(turn.attempt_number, turn.status) for turn in anthropic],
                [(1, TurnStatus.FAILED), (2, TurnStatus.COMPLETED)],
            )
            self.assertEqual(len(adapters["synthetic-google-cli"].requests), 1)
            self.assertEqual(
                adapters["claude-code"].requests[0].input_text,
                adapters["claude-code"].requests[1].input_text,
            )
            synthesis = adapters["codex"].requests[1].input_text
            self.assertLess(
                synthesis.index("audit:auditor-anthropic:round:1:attempt:2"),
                synthesis.index("audit:auditor-google:round:1:attempt:1"),
            )
            events = [
                json.loads(line)
                for line in (Path(outcome.run_path) / "events.jsonl").read_text().splitlines()
            ]
            kinds = [item["kind"] for item in events]
            self.assertLess(
                kinds.index("auditor_failure_resolution_selected"),
                kinds.index("failed_audits_retry_started"),
            )
        finally:
            temp.cleanup()

    async def test_continue_names_missing_audit_without_leaking_failure(self):
        private = "SECRET /Users/live/private/auditor-diagnostic"
        temp, orchestrator, task, adapters = await self._start_paused(
            private_failure=private
        )
        try:
            self.assertEqual(len(adapters["codex"].requests), 1)
            self.assertTrue(
                await orchestrator.resolve_auditor_failures(
                    AuditorFailureAction.CONTINUE_WITHOUT_FAILED
                )
            )
            outcome = await asyncio.wait_for(task, timeout=2)
            self.assertEqual(outcome.status, RunStatus.COMPLETED)
            synthesis = adapters["codex"].requests[1].input_text
            self.assertIn("Live explicitly chose to continue", synthesis)
            self.assertIn(AUDITOR_ANTHROPIC.participant_id, synthesis)
            self.assertIn("audit:auditor-google", synthesis)
            self.assertNotIn(private, synthesis)
            self.assertEqual(
                [item.stage for item in adapters["codex"].requests],
                [TurnStage.PROPOSAL, TurnStage.SYNTHESIS],
            )
        finally:
            temp.cleanup()

    async def test_stop_wakes_paused_run_and_prevents_synthesis(self):
        temp, orchestrator, task, adapters = await self._start_paused()
        try:
            self.assertTrue(await orchestrator.request_stop("Live pressed Stop"))
            outcome = await asyncio.wait_for(task, timeout=2)
            self.assertEqual(outcome.status, RunStatus.CANCELLED)
            self.assertEqual(outcome.stop_reason, "Live pressed Stop")
            self.assertEqual(len(adapters["codex"].requests), 1)
            self.assertFalse(orchestrator.awaiting_auditor_resolution)
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
