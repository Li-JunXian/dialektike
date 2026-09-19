"""No-model JSONL integration contracts for chat and explicit answer review.

Run: venv/bin/python tests/chat_topic_sidecar_invariants.py -v
Only injected adapters run; temporary stores isolate every test.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from m2_topic_sidecar_invariants import _Adapter, _command, _participants
from dialektike.adapters.base import AdapterError, TurnInterrupted
from dialektike.compaction import checkpoint_source_from_state
from dialektike.domain import AgentSystem, Vendor
from dialektike.providers.approved import approved_descriptors
from dialektike.runs import RunStore
from dialektike.sidecar import JsonlSidecar


class ControlledAdapter(_Adapter):
    def __init__(self, *args):
        super().__init__(*args)
        self.started = asyncio.Event()
        self.behaviour = None
        self.interrupts = 0

    async def run_turn(self, request, cancellation):
        result = await super().run_turn(request, cancellation)
        self.started.set()
        if self.behaviour == "block":
            await cancellation.wait()
            raise TurnInterrupted("Live stopped", partial_result=result)
        if self.behaviour == "fail":
            raise AdapterError("scripted partial failure", partial_result=result)
        return result

    async def interrupt(self):
        self.interrupts += 1


class ChatTopicSidecarTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "runs"
        self.codex = ControlledAdapter("codex", Vendor.OPENAI, AgentSystem.CODEX)
        self.claude = ControlledAdapter("claude-code", Vendor.ANTHROPIC, AgentSystem.CLAUDE_CODE)
        self.adapters = {"codex": self.codex, "claude-code": self.claude}
        self.output = []
        self.paused = asyncio.Event()
        self.serial = 0
        self.sidecar = self.make_sidecar()
        await self.send("capabilities.discover")

    def make_sidecar(self):
        def write(line):
            self.output.append(json.loads(line))
            if self.output[-1]["event"] == "audit.failure.paused":
                self.paused.set()
        return JsonlSidecar(store=RunStore(self.root), adapters=self.adapters, write_line=write)

    async def asyncTearDown(self):
        await self.sidecar.input_closed()
        self.temp.cleanup()

    async def send(self, command, payload=None):
        self.serial += 1
        ident = f"request-{self.serial}"
        await self.sidecar.handle_line(_command(ident, command, payload))
        return [r for r in self.output if r.get("request_id") == ident]

    async def idle(self):
        await asyncio.wait_for(self.sidecar.wait_idle(), timeout=3)

    async def create(self, participants=None):
        records = await self.send("topic.create", {"participants": participants or _participants()})
        self.assertEqual(records[-1]["event"], "topic.created", records)
        return records[-1]["payload"]["topic"]["summary"]["id"]

    def state(self, topic):
        return self.sidecar.topic_store.read(topic)

    def payload(self, topic, **changes):
        payload = {"topic_id": topic, "prompt": "Original question λ", "rounds": 1,
                   "participants": self.state(topic)["participant_config"]["participants"],
                   "mode": "chat", "speaker_id": "executor-seat"}
        if "review_target" in changes:
            payload["prompt"] = None
        payload.update(changes)
        return payload

    async def start(self, topic, **changes):
        records = await self.send("run.start", self.payload(topic, **changes))
        errors = [r for r in records if r["event"] == "protocol.error"]
        self.assertFalse(errors, errors)
        return next(r["payload"]["run_id"] for r in records if r["event"] == "command.result")

    async def run_chat(self, topic, **changes):
        run_id = await self.start(topic, **changes)
        await self.idle()
        cycle = self.state(topic)["cycles"][-1]
        self.assertEqual(cycle["run_id"], run_id)
        self.assertEqual(cycle["status"], "completed")
        return cycle

    @staticmethod
    def target(cycle):
        return {"cycle_id": cycle["run_id"], "message_id": cycle["messages"][-1]["id"]}

    async def reject(self, topic, **changes):
        before = deepcopy(self.state(topic))
        counts = [len(a.requests) for a in self.adapters.values()]
        records = await self.send("run.start", self.payload(topic, **changes))
        await self.idle()
        self.assertIn("protocol.error", [r["event"] for r in records], records)
        self.assertNotIn("command.result", [r["event"] for r in records])
        self.assertEqual([len(a.requests) for a in self.adapters.values()], counts)
        self.assertEqual(self.state(topic), before)

    async def test_both_speakers_persist_reopen_and_follow_up(self):
        topic = await self.create()
        first = await self.run_chat(topic)
        self.assertEqual([m["stage"] for m in first["messages"]], ["answer"])
        self.assertEqual(len(self.codex.requests), 1)
        self.assertEqual(self.claude.requests, [])
        await self.sidecar.input_closed()
        self.sidecar = self.make_sidecar()
        await self.send("capabilities.discover")
        loaded = await self.send("topic.read", {"topic_id": topic})
        self.assertEqual(loaded[-1]["payload"]["topic"]["messages"], [{**m, "cycle": 1} for m in first["messages"]])
        second = await self.run_chat(topic, speaker_id="auditor-seat", prompt="Meaningful followup")
        self.assertEqual(len(self.codex.requests), 1)
        self.assertEqual(len(self.claude.requests), 1)
        request = self.claude.requests[-1]
        for text in ("Original question λ", "codex answer response", "Meaningful followup"):
            self.assertIn(text, request.input_text)
        self.assertEqual(second["messages"][0]["participant_id"], "auditor-seat")
        self.assertEqual(second["messages"][0]["stage"], "answer")
        await self.run_chat(topic, prompt="Switch back")
        self.assertIn("claude-code answer response", self.codex.requests[-1].input_text)
        self.assertEqual(len(self.state(topic)["participant_config"]["participants"]), 2)

    async def test_unavailable_dormant_reviewer_does_not_block(self):
        topic = await self.create()
        await self.sidecar.input_closed()
        self.claude.descriptor = next(d for d in approved_descriptors() if d.runtime_id == "claude-code")
        async def unavailable():
            raise RuntimeError("reviewer temporarily unavailable")
        self.claude.discover_capabilities = unavailable
        self.sidecar = self.make_sidecar()
        await self.send("capabilities.discover")
        await self.run_chat(topic)
        self.assertEqual(self.claude.requests, [])
        self.assertEqual(len(self.state(topic)["participant_config"]["participants"]), 2)

    async def test_stale_dormant_model_and_effort_do_not_block_selected_speaker(self):
        for field, stale in (("model", "retired-model"), ("effort", "retired-effort")):
            with self.subTest(field=field):
                topic = await self.create()
                participants = _participants()
                participants[1]["requested"][field] = stale
                records = await self.send("topic.update", {"topic_id": topic, "participants": participants})
                self.assertNotIn("protocol.error", [r["event"] for r in records], records)
                await self.run_chat(topic)
                self.assertEqual(self.claude.requests, [])
                self.assertEqual(self.state(topic)["participant_config"]["participants"][1]["requested"][field], stale)
                await self.reject(topic, speaker_id="auditor-seat")

    async def test_cross_mode_fields_are_rejected_without_execution(self):
        topic = await self.create()
        original = await self.run_chat(topic)
        await self.reject(topic, mode="review", speaker_id="executor-seat", review_target=self.target(original))
        await self.reject(topic, assignments=[])
        await self.reject(topic, review_target=self.target(original))
        await self.reject(topic, review_answer="client invented answer")

    async def test_review_resolves_frozen_source_and_next_send_is_chat(self):
        topic = await self.create()
        await self.run_chat(topic, prompt="Context before target")
        original = await self.run_chat(topic, prompt="Exact target question")
        await self.run_chat(topic, prompt="FUTURE-CONTEXT-MUST-NOT-LEAK")
        await self.send("topic.checkpoint.draft", {"topic_id": topic})
        await self.idle()
        checkpoint = self.state(topic)["context_checkpoints"][-1]
        await self.send("topic.checkpoint.approve", {"topic_id": topic, "checkpoint_id": checkpoint["checkpoint_id"]})
        await self.reject(topic, mode="review", speaker_id=None,
                          review_target=self.target(original), prompt="CLIENT-FORGED-QUESTION")
        counts = len(self.codex.requests), len(self.claude.requests)
        await self.start(topic, mode="review", speaker_id=None,
                         review_target=self.target(original))
        await self.idle()
        audit = self.claude.requests[counts[1]:]
        synthesis = self.codex.requests[counts[0]:]
        self.assertEqual([r.stage.value for r in audit], ["audit"])
        self.assertEqual([r.stage.value for r in synthesis], ["synthesis"])
        for request in audit + synthesis:
            for text in ("Context before target", "Exact target question", "codex answer response"):
                self.assertIn(text, request.input_text)
            self.assertNotIn("FUTURE-CONTEXT-MUST-NOT-LEAK", request.input_text)
            self.assertNotIn("CLIENT-FORGED-QUESTION", request.input_text)
            self.assertIn("Exact target question", request.original_prompt)
            self.assertNotIn("Review the answer to:", request.original_prompt)
        state = self.state(topic)
        self.assertEqual(state["cycles"][1], original)
        self.assertEqual(state["cycles"][-1]["live_prompt"], "Review the answer to: Exact target question")
        provenance = state["cycles"][-1]["review_target"]
        self.assertEqual(provenance["question"], "Exact target question")
        self.assertEqual(provenance["answer_sha256"], hashlib.sha256(original["messages"][-1]["text"].encode()).hexdigest())
        for key, value in self.target(original).items():
            self.assertEqual(provenance[key], value)
        await self.run_chat(topic, prompt="Ordinary next send")
        self.assertEqual(len(self.claude.requests), counts[1] + 1)
        self.assertEqual(self.codex.requests[-1].stage.value, "answer")

    async def test_invalid_missing_and_foreign_targets_never_execute(self):
        topic = await self.create()
        source = await self.run_chat(topic)
        foreign = await self.create()
        other = await self.run_chat(foreign)
        for target in ({}, {"cycle_id": source["run_id"]}, {"message_id": source["messages"][0]["id"]},
                       {"cycle_id": "missing", "message_id": "missing"},
                       {"cycle_id": source["run_id"], "message_id": other["messages"][0]["id"]},
                       self.target(other), "not-an-object"):
            with self.subTest(target=target):
                await self.reject(topic, mode="review", speaker_id=None, review_target=target)

    async def test_reviewer_matching_original_vendor_rejected_until_swap_back(self):
        topic = await self.create()
        original = await self.run_chat(topic)
        swapped = _participants()
        for seat, source in zip(swapped, reversed(_participants())):
            seat["runtime_id"], seat["requested"] = source["runtime_id"], source["requested"]
        await self.send("topic.update", {"topic_id": topic, "participants": swapped})
        await self.reject(topic, mode="review", speaker_id=None, review_target=self.target(original))
        await self.send("topic.update", {"topic_id": topic, "participants": _participants()})
        await self.start(topic, mode="review", speaker_id=None, review_target=self.target(original))
        await self.idle()
        self.assertEqual([m["stage"] for m in self.state(topic)["cycles"][-1]["messages"]], ["audit", "synthesis"])

    async def test_stop_partial_rejected_as_target_and_restart_recovers(self):
        topic = await self.create()
        self.codex.behaviour = "block"
        run_id = await self.start(topic)
        await asyncio.wait_for(self.codex.started.wait(), timeout=1)
        records = await self.send("run.stop", {"run_id": run_id})
        await self.idle()
        self.assertTrue(records[-1]["payload"]["stopped"])
        partial = self.state(topic)["cycles"][-1]
        self.assertEqual(partial["status"], "partial")
        self.assertTrue(partial["messages"][0]["partial"])
        self.assertEqual(partial["messages"][0]["text"], "codex answer response")
        self.assertEqual(self.codex.interrupts, 1)
        await self.reject(topic, mode="review", speaker_id=None, review_target=self.target(partial))
        self.codex.behaviour = None
        await self.sidecar.input_closed()
        self.sidecar = self.make_sidecar()
        await self.send("capabilities.discover")
        await self.run_chat(topic, prompt="Recover after stop")
        self.assertEqual(self.claude.requests, [])
        self.assertEqual(self.state(topic)["cycles"][0], partial)

    async def test_failed_direct_answer_preserved_and_later_send_recovers(self):
        topic = await self.create()
        self.codex.behaviour = "fail"
        await self.start(topic)
        await self.idle()
        partial = self.state(topic)["cycles"][0]
        self.assertEqual(partial["run_status"], "failed")
        self.assertTrue(partial["messages"][0]["partial"])
        self.codex.behaviour = None
        await self.run_chat(topic, prompt="Recovery")
        self.assertEqual(self.state(topic)["cycles"][0], partial)

    async def test_review_retry_keeps_original_and_identical_audit_source(self):
        topic = await self.create()
        original = await self.run_chat(topic)
        self.claude.fail_audit_attempts = {1}
        await self.start(topic, mode="review", speaker_id=None, review_target=self.target(original))
        await asyncio.wait_for(self.paused.wait(), timeout=1)
        pause = next(r["payload"] for r in self.output if r["event"] == "audit.failure.paused")
        self.assertEqual(len(self.codex.requests), 1)
        await self.send("audit.failure.resolve", {"run_id": pause["run_id"], "failure_id": pause["failure_id"], "resolution": "retry_failed"})
        await self.idle()
        self.assertEqual(self.claude.requests[0].input_text, self.claude.requests[1].input_text)
        self.assertEqual(self.state(topic)["cycles"][0], original)
        self.assertEqual([r.stage.value for r in self.codex.requests], ["answer", "synthesis"])

    async def test_reviewed_synthesis_resolves_original_question_recursively(self):
        topic = await self.create()
        original = await self.run_chat(topic, prompt="Original recursive question")
        await self.start(topic, mode="review", speaker_id=None, review_target=self.target(original))
        await self.idle()
        reviewed = deepcopy(self.state(topic)["cycles"][-1])
        await self.start(topic, mode="review", speaker_id=None, review_target=self.target(reviewed))
        await self.idle()
        request = self.claude.requests[-1]
        self.assertIn("Original recursive question", request.original_prompt)
        self.assertNotIn("Review the answer to:", request.original_prompt)
        self.assertIn("codex synthesis response", request.input_text)
        state = self.state(topic)
        self.assertEqual(state["cycles"][0], original)
        self.assertEqual(state["cycles"][1], reviewed)
        self.assertEqual(state["cycles"][-1]["review_target"]["question"], "Original recursive question")

    async def test_stop_paused_review_preserves_source_and_does_not_synthesize(self):
        topic = await self.create()
        original = await self.run_chat(topic)
        self.claude.fail_audit_attempts = {1}
        run_id = await self.start(topic, mode="review", speaker_id=None, review_target=self.target(original))
        await asyncio.wait_for(self.paused.wait(), timeout=1)
        await self.send("run.stop", {"run_id": run_id})
        await self.idle()
        self.assertEqual([r.stage.value for r in self.codex.requests], ["answer"])
        self.assertEqual(self.state(topic)["cycles"][0], original)
        self.assertEqual(self.state(topic)["cycles"][-1]["run_status"], "cancelled")
        await self.run_chat(topic, prompt="Ordinary send after cancelled review")
        self.assertEqual(len(self.claude.requests), 1)

    async def test_checkpoint_includes_direct_answers_and_legacy_digest_is_unchanged(self):
        topic = await self.create()
        legacy = await self.run_chat(topic, mode="review", speaker_id=None)
        expected = [{"anchor": legacy["run_id"] + ":live", "role": "live", "stage": "prompt",
                     "text": legacy["live_prompt"], "cycle_number": 1}]
        for message in legacy["messages"]:
            if message["stage"] == "synthesis":
                expected.append({"anchor": message["id"], "role": "executor", "stage": "synthesis",
                                 "text": message["text"], "cycle_number": 1})
        digest = hashlib.sha256(json.dumps(expected, ensure_ascii=False, allow_nan=False,
                                          sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(checkpoint_source_from_state(self.state(topic))["source_sha256"], digest)
        answer = await self.run_chat(topic, prompt="Direct context", speaker_id="auditor-seat")
        await self.send("topic.checkpoint.draft", {"topic_id": topic})
        await self.idle()
        self.assertIn("Direct context", self.codex.requests[-1].input_text)
        self.assertIn("claude-code answer response", self.codex.requests[-1].input_text)
        self.assertEqual(self.state(topic)["cycles"][-1], answer)
        self.assertEqual(len(self.state(topic)["context_checkpoints"]), 1)


if __name__ == "__main__":
    unittest.main()
