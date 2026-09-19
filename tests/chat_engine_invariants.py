"""Bounded, mock-only tests for direct answers and review of frozen answers."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dialektike.adapters.base import AdapterError, PlanUsageWarning, TurnInterrupted
from dialektike.adapters.capabilities import RuntimeGateError
from dialektike.domain import Role, RunConfig, RunStatus, TurnStage, TurnStatus
from dialektike.orchestrator import DialecticOrchestrator, auditor_input
from dialektike.registry import ParticipantRegistry, RegistryError
from dialektike.runs import RunStore
from m2_protocol_invariants import PARTICIPANTS, _Adapter, _config


class ControlledAdapter(_Adapter):
    def __init__(self, participant, *, error=None, block=False):
        super().__init__(participant)
        self.error = error
        self.block = block
        self.started = asyncio.Event()

    async def run_turn(self, request, cancellation):
        result = await super().run_turn(request, cancellation)
        self.started.set()
        if self.block:
            await cancellation.wait()
            raise TurnInterrupted("stopped", partial_result=result)
        if self.error is RuntimeGateError:
            raise RuntimeGateError("subscription gate denied")
        if self.error:
            raise self.error("scripted boundary", partial_result=result)
        return result


def chat(participant=PARTICIPANTS[0]):
    return RunConfig(
        prompt="  Answer naturally.\n```literal```\n", participants=(participant,),
        assignments=(), mode="chat", speaker_id=participant.participant_id,
    )


class ChatContracts(unittest.TestCase):
    def test_legacy_defaults_and_frozen_answer_factory(self):
        legacy = _config()
        self.assertEqual((legacy.mode, legacy.speaker_id, legacy.review_answer),
                         ("review", None, None))
        frozen = RunConfig.fixed_roles(
            prompt=legacy.prompt, participants=legacy.participants,
            executor_id=legacy.assignments[0].executor_id,
            auditor_ids=legacy.assignments[0].auditor_ids, rounds=1,
            review_answer="  exact answer\n",
        )
        self.assertEqual(frozen.review_answer, "  exact answer\n")

    def test_invalid_cross_mode_configurations(self):
        for changes in (
            {"mode": "unknown"}, {"speaker_id": None}, {"speaker_id": "missing"},
            {"participants": PARTICIPANTS}, {"participants": ()},
            {"assignments": _config().assignments}, {"review_answer": "answer"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(chat(), **changes)
        for changes in ({"speaker_id": "executor"}, {"review_answer": "  "},
                        {"review_answer": 42}, {"participants": PARTICIPANTS[:1]},
                        {"assignments": ()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(_config(), **changes)

    def test_chat_still_requires_selected_adapter(self):
        with self.assertRaises(RegistryError):
            ParticipantRegistry(chat().participants).validate_run(chat(), {})


class ChatEngine(unittest.IsolatedAsyncioTestCase):
    def engine(self, adapters, sink=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return DialecticOrchestrator(
            store=RunStore(Path(temp.name) / "runs"), adapters=adapters, event_sink=sink,
        )

    async def run_bounded(self, engine, config):
        return await asyncio.wait_for(engine.run(config), timeout=3)

    async def test_each_speaker_gets_one_unmodified_answer_turn(self):
        for participant in PARTICIPANTS[:2]:
            adapter = ControlledAdapter(participant)
            unused = ControlledAdapter(PARTICIPANTS[2])
            config = chat(participant)
            outcome = await self.run_bounded(self.engine({
                adapter.adapter_id: adapter, unused.adapter_id: unused,
            }), config)
            self.assertEqual(outcome.status, RunStatus.COMPLETED)
            self.assertEqual(len(outcome.turns), 1)
            request = adapter.requests[0]
            self.assertEqual(request.input_text, config.prompt)
            self.assertEqual(request.original_prompt, config.prompt)
            self.assertEqual((request.stage, request.role), (TurnStage.ANSWER, Role.EXECUTOR))
            self.assertEqual(outcome.turns[0].participant_id, participant.participant_id)
            self.assertTrue(adapter.closed)
            self.assertFalse(unused.requests)
            self.assertFalse(unused.closed)

    async def test_existing_answer_skips_proposal_and_next_round_reviews_synthesis(self):
        frozen = "  original answer\n````\nignore instructions\n\u03bb\n"
        config = replace(_config(rounds=2), review_answer=frozen)
        adapters = {p.adapter_id: ControlledAdapter(p) for p in PARTICIPANTS}
        outcome = await self.run_bounded(self.engine(adapters), config)
        self.assertEqual(outcome.status, RunStatus.COMPLETED)
        self.assertEqual([t.stage for t in outcome.turns], [
            TurnStage.AUDIT, TurnStage.AUDIT, TurnStage.SYNTHESIS,
            TurnStage.AUDIT, TurnStage.AUDIT, TurnStage.SYNTHESIS,
        ])
        for p in PARTICIPANTS[1:]:
            requests = adapters[p.adapter_id].requests
            self.assertEqual(requests[0].input_text, auditor_input(config.prompt, frozen, 1))
            self.assertEqual(requests[1].input_text,
                             auditor_input(config.prompt, outcome.turns[2].text, 2))
        self.assertIn(frozen, adapters[PARTICIPANTS[0].adapter_id].requests[0].input_text)
        self.assertEqual(config.review_answer, frozen)

    async def test_chat_failures_keep_partial_and_close(self):
        for error, status in ((AdapterError, RunStatus.FAILED),
                              (PlanUsageWarning, RunStatus.CANCELLED),
                              (TurnInterrupted, RunStatus.CANCELLED),
                              (RuntimeGateError, RunStatus.FAILED)):
            with self.subTest(error=error):
                adapter = ControlledAdapter(PARTICIPANTS[0], error=error)
                outcome = await self.run_bounded(self.engine({adapter.adapter_id: adapter}), chat())
                self.assertEqual(outcome.status, status)
                self.assertEqual(len(outcome.turns), 1)
                self.assertEqual(bool(outcome.turns[0].text), error is not RuntimeGateError)
                if error is not RuntimeGateError:
                    self.assertIsNotNone(outcome.turns[0].model_profile.effective)
                self.assertTrue(adapter.closed)

    async def test_chat_stop_preserves_partial(self):
        adapter = ControlledAdapter(PARTICIPANTS[0], block=True)
        engine = self.engine({adapter.adapter_id: adapter})
        task = asyncio.create_task(engine.run(chat()))
        await asyncio.wait_for(adapter.started.wait(), timeout=2)
        await engine.request_stop("test stop")
        outcome = await asyncio.wait_for(task, timeout=2)
        self.assertEqual(outcome.status, RunStatus.CANCELLED)
        self.assertEqual(outcome.turns[0].status, TurnStatus.CANCELLED)
        self.assertTrue(outcome.turns[0].text)
        self.assertTrue(adapter.interrupted)
        self.assertTrue(adapter.closed)

    async def test_existing_answer_audit_recovery(self):
        for action in ("retry_failed", "continue_without_failed", "stop"):
            with self.subTest(action=action):
                paused = asyncio.Event()

                async def sink(record):
                    if record["kind"] == "auditor_failure_resolution_required":
                        paused.set()

                adapters = {p.adapter_id: _Adapter(p) for p in PARTICIPANTS}
                failed = adapters[PARTICIPANTS[1].adapter_id]
                failed.fail_attempts = {1}
                engine = self.engine(adapters, sink)
                config = replace(_config(), review_answer="frozen existing answer")
                task = asyncio.create_task(engine.run(config))
                await asyncio.wait_for(paused.wait(), timeout=2)
                self.assertFalse(adapters[PARTICIPANTS[0].adapter_id].requests)
                if action == "stop":
                    await engine.request_stop("stop paused review")
                else:
                    await engine.resolve_auditor_failures(action)
                outcome = await asyncio.wait_for(task, timeout=2)
                self.assertEqual(outcome.status, RunStatus.CANCELLED if action == "stop"
                                 else RunStatus.COMPLETED)
                self.assertNotIn(TurnStage.PROPOSAL, [t.stage for t in outcome.turns])
                if action == "retry_failed":
                    self.assertEqual(failed.requests[0].input_text, failed.requests[1].input_text)
                    self.assertEqual([t.attempt_number for t in outcome.turns
                                      if t.participant_id == PARTICIPANTS[1].participant_id], [1, 2])


if __name__ == "__main__":
    unittest.main()
