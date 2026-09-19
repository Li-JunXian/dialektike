"""JSONL-boundary invariants for topic search and context checkpoints."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dialektike.adapters.base import TurnInterrupted  # noqa: E402
from dialektike.compaction import canonical_entries_from_state  # noqa: E402
from dialektike.domain import (  # noqa: E402
    AdapterCapabilities,
    AgentSystem,
    ModelCapability,
    ModelSelection,
    Role,
    StructuredContentBlock,
    TurnResult,
    TurnStage,
    Vendor,
)
from dialektike.runs import RunStore  # noqa: E402
from dialektike.sidecar import JsonlSidecar, PROTOCOL_NAME  # noqa: E402


def _command(command_id: str, command: str, payload: dict | None = None) -> str:
    return json.dumps(
        {
            "protocol": PROTOCOL_NAME,
            "id": command_id,
            "command": command,
            "payload": payload or {},
        },
        ensure_ascii=False,
    )


def _participants() -> list[dict[str, Any]]:
    return [
        {
            "participant_id": "executor-seat",
            "role": "executor",
            "runtime_id": "codex",
            "requested": {
                "model": "codex-model",
                "effort": "high",
                "service_tier": "native-default",
            },
        },
        {
            "participant_id": "auditor-seat",
            "role": "auditor",
            "runtime_id": "claude-code",
            "requested": {
                "model": "claude-code-model",
                "effort": "high",
                "service_tier": "native-default",
            },
        },
    ]


class _Adapter:
    def __init__(
        self,
        adapter_id: str,
        vendor: Vendor,
        agent_system: AgentSystem,
    ) -> None:
        self.adapter_id = adapter_id
        self.vendor = vendor
        self.agent_system = agent_system
        self.requests: list[Any] = []
        self.checkpoint_requests: list[Any] = []
        self.checkpoint_mode = "success"
        self.checkpoint_summary = "Compact summary Ω\n"
        self.checkpoint_started = asyncio.Event()
        self.interrupt_count = 0
        self.native_compact_calls = 0

    async def discover_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id=self.adapter_id,
            vendor=self.vendor,
            agent_system=self.agent_system,
            models=(
                ModelCapability(
                    model_id=f"{self.adapter_id}-model",
                    display_name=f"{self.adapter_id} model",
                    efforts=("high",),
                    is_default=True,
                ),
            ),
            runtime_version=f"{self.adapter_id}-test",
            account_route=f"{self.adapter_id}:subscription",
        )

    async def run_turn(self, request, cancellation) -> TurnResult:
        self.requests.append(request)
        is_checkpoint = (
            request.original_prompt
            == "Create a reviewable topic context checkpoint."
        )
        if is_checkpoint:
            self.checkpoint_requests.append(request)
            self.checkpoint_started.set()
            if self.checkpoint_mode == "fail":
                raise RuntimeError("private checkpoint failure /tmp/must-not-cross")
            if self.checkpoint_mode == "block":
                await cancellation.wait()
                raise TurnInterrupted(
                    cancellation.reason or "checkpoint generation stopped"
                )
            text = self.checkpoint_summary
        else:
            text = f"{self.adapter_id} {request.stage.value} response"
        requested = request.participant.model_profile.requested
        result = TurnResult(
            text=text,
            blocks=(StructuredContentBlock.markdown(text),),
            model_profile=request.participant.model_profile.resolved(
                ModelSelection(
                    model_id=requested.model_id,
                    effort=requested.effort,
                    service_tier=requested.service_tier,
                    features=requested.features,
                    controls=requested.controls,
                ),
                "fake runtime echo",
            ),
            account_route=f"{self.adapter_id}:subscription",
            runtime_version=f"{self.adapter_id}-test",
            evidence=(("owner_only_secret", "OWNER-RAW-DO-NOT-INDEX"),),
        )
        return result

    async def interrupt(self) -> None:
        self.interrupt_count += 1
        # A native interrupt is an I/O boundary. Yield so the cancellation race
        # exercises command/result correlation against task cleanup.
        await asyncio.sleep(0)

    async def close(self) -> None:
        return None

    async def compact(self, *_args: Any, **_kwargs: Any) -> None:
        """Trap any dishonest provider-native compaction attempt."""

        self.native_compact_calls += 1
        raise AssertionError("checkpoint generation must use a fresh model turn")


class TopicSearchCheckpointSidecarTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output: list[str] = []
        self.run_store = RunStore(Path(self.temp.name) / "runs")
        self.codex = _Adapter("codex", Vendor.OPENAI, AgentSystem.CODEX)
        self.claude = _Adapter(
            "claude-code", Vendor.ANTHROPIC, AgentSystem.CLAUDE_CODE
        )
        self.sidecar = JsonlSidecar(
            store=self.run_store,
            adapters={"codex": self.codex, "claude-code": self.claude},
            write_line=self.output.append,
        )
        self._serial = 0
        await self._send("capabilities.discover")

    async def asyncTearDown(self) -> None:
        await self.sidecar.input_closed()
        self.temp.cleanup()

    def _records(self, *, request_id: str | None = None) -> list[dict[str, Any]]:
        records = [json.loads(line) for line in self.output]
        if request_id is None:
            return records
        return [item for item in records if item.get("request_id") == request_id]

    async def _send(
        self,
        command: str,
        payload: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        self._serial += 1
        chosen_id = command_id or f"command-{self._serial}"
        await self.sidecar.handle_line(_command(chosen_id, command, payload))
        return chosen_id, self._records(request_id=chosen_id)

    async def _create_topic(self, title: str) -> str:
        command_id, _ = await self._send(
            "topic.create",
            {"title": title, "participants": _participants()},
        )
        created = next(
            item
            for item in self._records(request_id=command_id)
            if item["event"] == "topic.created"
        )
        return str(created["payload"]["topic"]["summary"]["id"])

    async def _run_topic(self, topic_id: str, prompt: str) -> str:
        command_id, records = await self._send(
            "run.start",
            {
                "topic_id": topic_id,
                "prompt": prompt,
                "rounds": 1,
                "participants": _participants(),
            },
        )
        run_id = str(
            next(item for item in records if item["event"] == "command.result")[
                "payload"
            ]["run_id"]
        )
        await self.sidecar.wait_idle()
        self.assertTrue(
            any(
                item["event"] == "run.completed"
                for item in self._records(request_id=command_id)
            )
        )
        return run_id

    async def _draft_checkpoint(self, topic_id: str) -> tuple[str, str]:
        command_id, records = await self._send(
            "topic.checkpoint.draft", {"topic_id": topic_id}
        )
        started = next(
            item for item in records if item["event"] == "command.result"
        )
        run_id = str(started["payload"]["run_id"])
        await self.sidecar.wait_idle()
        return command_id, run_id

    async def _activate_initial_checkpoint(self, topic_id: str) -> str:
        await self._draft_checkpoint(topic_id)
        state = self.sidecar.topic_store.read(topic_id)
        checkpoint_id = str(state["context_checkpoints"][-1]["checkpoint_id"])
        await self._send(
            "topic.checkpoint.approve",
            {"topic_id": topic_id, "checkpoint_id": checkpoint_id},
        )
        return checkpoint_id

    async def test_topic_search_is_backend_authoritative_through_jsonl(self) -> None:
        active_id = await self._create_topic("Ordinary active topic")
        await self._run_topic(active_id, "Straße ﬁle visible only in content")

        archived_id = await self._create_topic("Archived Straße ﬁle title")
        await self._send(
            "topic.update", {"topic_id": archived_id, "archived": True}
        )
        deleted_id = await self._create_topic("Deleted Straße ﬁle title")
        await self._send("topic.delete", {"topic_id": deleted_id})

        command_id, records = await self._send(
            "topic.search", {"query": "STRASSE FILE"}
        )
        result = next(
            item for item in records if item["event"] == "topic.search.result"
        )
        self.assertEqual(result["request_id"], command_id)
        self.assertEqual(result["payload"]["query"], "STRASSE FILE")
        occurrences = result["payload"]["occurrences"]
        self.assertEqual(
            {item["topic_id"] for item in occurrences},
            {active_id, archived_id},
        )
        self.assertNotIn(deleted_id, {item["topic_id"] for item in occurrences})
        active_hit = next(
            item
            for item in occurrences
            if item["topic_id"] == active_id
            and item["source_anchor"].endswith(":live")
        )
        highlighted = "".join(
            segment["text"]
            for segment in active_hit["snippet_segments"]
            if segment["highlighted"]
        )
        self.assertEqual(highlighted, "Straße ﬁle")
        self.assertIsInstance(active_hit["prefix_truncated"], bool)
        self.assertIsInstance(active_hit["suffix_truncated"], bool)
        self.assertNotIn("snippet_prefix_truncated", active_hit)
        self.assertNotIn("snippet_suffix_truncated", active_hit)
        self.assertIsInstance(active_hit["timestamp"], str)
        archived_hit = next(
            item for item in occurrences if item["topic_id"] == archived_id
        )
        self.assertTrue(archived_hit["archived"])
        self.assertNotIn("OWNER-RAW-DO-NOT-INDEX", json.dumps(result))

        _, active_only_records = await self._send(
            "topic.search",
            {"query": "STRASSE FILE", "include_archived": False},
        )
        active_only = next(
            item
            for item in active_only_records
            if item["event"] == "topic.search.result"
        )["payload"]["occurrences"]
        self.assertEqual({item["topic_id"] for item in active_only}, {active_id})

    async def test_checkpoint_draft_approval_and_deactivation_are_live_gated(
        self,
    ) -> None:
        topic_id = await self._create_topic("Checkpoint lifecycle")
        first_run_id = await self._run_topic(topic_id, "First Live requirement")
        original = self.sidecar.topic_store.canonical_context(topic_id)
        auditor_request_count = len(self.claude.requests)

        _, inactive_records = await self._send(
            "topic.checkpoint.deactivate", {"topic_id": topic_id}
        )
        inactive_event = next(
            item
            for item in inactive_records
            if item["event"] == "topic.checkpoint.deactivated"
        )
        self.assertFalse(inactive_event["payload"]["active_context_changed"])
        self.assertEqual(self.sidecar.topic_store.canonical_context(topic_id), original)

        draft_command_id, checkpoint_run_id = await self._draft_checkpoint(topic_id)

        state = self.sidecar.topic_store.read(topic_id)
        self.assertEqual(len(state["context_checkpoints"]), 1)
        checkpoint = state["context_checkpoints"][0]
        checkpoint_id = str(checkpoint["checkpoint_id"])
        self.assertIsNone(state["active_context_checkpoint_id"])
        self.assertEqual(self.sidecar.topic_store.canonical_context(topic_id), original)
        self.assertNotEqual(checkpoint_run_id, first_run_id)
        self.assertNotIn(checkpoint_run_id, state["linked_run_ids"])
        request = self.codex.checkpoint_requests[-1]
        self.assertIs(request.role, Role.EXECUTOR)
        self.assertIs(request.stage, TurnStage.SYNTHESIS)
        self.assertTrue(request.fresh_session)
        self.assertEqual(request.round_number, 1)
        self.assertEqual(request.turn_number, 1)
        self.assertIn("First Live requirement", request.input_text)
        self.assertIn("codex synthesis response", request.input_text)
        self.assertNotIn("claude-code audit response", request.input_text)
        self.assertNotIn("/compact", request.input_text)
        self.assertEqual(len(self.claude.requests), auditor_request_count)
        self.assertEqual(self.codex.native_compact_calls, 0)
        self.assertTrue(checkpoint["creator"]["fresh_session"])
        draft_events = self._records(request_id=draft_command_id)
        self.assertTrue(
            any(item["event"] == "topic.checkpoint.drafted" for item in draft_events)
        )
        self.assertTrue(
            all(
                item["payload"].get("active_context_changed") is not True
                for item in draft_events
                if isinstance(item.get("payload"), dict)
            )
        )
        read_id, read_records = await self._send(
            "topic.read", {"topic_id": topic_id}
        )
        projected_draft = next(
            item for item in read_records if item["event"] == "topic.loaded"
        )
        self.assertEqual(projected_draft["request_id"], read_id)
        self.assertIsNone(
            projected_draft["payload"]["topic"]["active_context_checkpoint_id"]
        )
        self.assertEqual(
            projected_draft["payload"]["topic"]["context_checkpoints"][0][
                "status"
            ],
            "draft",
        )

        approve_id, approve_records = await self._send(
            "topic.checkpoint.approve",
            {"topic_id": topic_id, "checkpoint_id": checkpoint_id},
        )
        activated = next(
            item
            for item in approve_records
            if item["event"] == "topic.checkpoint.activated"
        )
        self.assertEqual(activated["request_id"], approve_id)
        self.assertEqual(activated["payload"]["approved_by"], "live")
        state = self.sidecar.topic_store.read(topic_id)
        self.assertEqual(state["active_context_checkpoint_id"], checkpoint_id)
        effective = self.sidecar.topic_store.canonical_context(topic_id)
        self.assertEqual(effective[0]["stage"], "checkpoint")
        self.assertEqual(effective[0]["text"], self.codex.checkpoint_summary)

        await self._run_topic(topic_id, "Requirement after checkpoint boundary")
        effective_with_later_cycle = self.sidecar.topic_store.canonical_context(
            topic_id
        )
        self.assertEqual(
            [item["role"] for item in effective_with_later_cycle],
            ["context", "live", "executor"],
        )
        before_deactivation = self.sidecar.topic_store.read(topic_id)
        original_cycles = deepcopy(before_deactivation["cycles"])
        expected_full = canonical_entries_from_state(before_deactivation)

        _, deactivate_records = await self._send(
            "topic.checkpoint.deactivate", {"topic_id": topic_id}
        )
        self.assertTrue(
            any(
                item["event"] == "topic.checkpoint.deactivated"
                for item in deactivate_records
            )
        )
        deactivated = self.sidecar.topic_store.read(topic_id)
        self.assertIsNone(deactivated["active_context_checkpoint_id"])
        self.assertEqual(deactivated["cycles"], original_cycles)
        self.assertEqual(
            self.sidecar.topic_store.canonical_context(topic_id), expected_full
        )
        self.assertEqual(len(deactivated["context_checkpoints"]), 1)
        self.assertEqual(
            [
                event["kind"]
                for event in self.sidecar.topic_store.events(topic_id)
                if event["kind"].startswith("context_checkpoint_")
            ],
            [
                "context_checkpoint_drafted",
                "context_checkpoint_approved",
                "context_checkpoint_deactivated",
            ],
        )

    async def test_failed_and_cancelled_drafts_preserve_prior_active_checkpoint(
        self,
    ) -> None:
        topic_id = await self._create_topic("Checkpoint failure safety")
        await self._run_topic(topic_id, "Stable source context")
        active_checkpoint_id = await self._activate_initial_checkpoint(topic_id)
        prior_state = self.sidecar.topic_store.read(topic_id)
        prior_context = self.sidecar.topic_store.canonical_context(topic_id)
        prior_count = len(prior_state["context_checkpoints"])

        self.codex.checkpoint_mode = "fail"
        failure_command_id, failure_run_id = await self._draft_checkpoint(topic_id)
        failed_state = self.sidecar.topic_store.read(topic_id)
        self.assertEqual(
            failed_state["active_context_checkpoint_id"], active_checkpoint_id
        )
        self.assertEqual(len(failed_state["context_checkpoints"]), prior_count)
        self.assertEqual(
            self.sidecar.topic_store.canonical_context(topic_id), prior_context
        )
        failed_events = self._records(request_id=failure_command_id)
        failed = next(
            item for item in failed_events if item["event"] == "topic.checkpoint.failed"
        )
        self.assertNotIn("/tmp", json.dumps(failed))
        failure_snapshot = json.loads(
            (self.run_store.root / failure_run_id / "transcript.json").read_text()
        )
        self.assertEqual(failure_snapshot["status"], "failed")
        self.assertFalse(failure_snapshot["active_context_changed"])

        self.codex.checkpoint_mode = "block"
        self.codex.checkpoint_started = asyncio.Event()
        cancel_command_id, start_records = await self._send(
            "topic.checkpoint.draft", {"topic_id": topic_id}
        )
        cancel_run_id = str(
            next(
                item for item in start_records if item["event"] == "command.result"
            )["payload"]["run_id"]
        )
        await asyncio.wait_for(self.codex.checkpoint_started.wait(), timeout=1)
        stop_id, _ = await self._send(
            "run.stop",
            {"run_id": cancel_run_id, "reason": "Live cancelled checkpoint"},
        )
        await self.sidecar.wait_idle()

        stop_result = next(
            item
            for item in self._records(request_id=stop_id)
            if item["event"] == "command.result"
        )
        self.assertTrue(stop_result["payload"]["stopped"])
        self.assertEqual(stop_result["payload"]["run_id"], cancel_run_id)
        cancelled_events = self._records(request_id=cancel_command_id)
        cancelled = next(
            item
            for item in cancelled_events
            if item["event"] == "topic.checkpoint.failed"
        )
        self.assertIn("was stopped", cancelled["payload"]["message"])
        cancelled_state = self.sidecar.topic_store.read(topic_id)
        self.assertEqual(
            cancelled_state["active_context_checkpoint_id"], active_checkpoint_id
        )
        self.assertEqual(len(cancelled_state["context_checkpoints"]), prior_count)
        self.assertEqual(
            self.sidecar.topic_store.canonical_context(topic_id), prior_context
        )
        cancel_snapshot = json.loads(
            (self.run_store.root / cancel_run_id / "transcript.json").read_text()
        )
        self.assertEqual(cancel_snapshot["status"], "cancelled")
        self.assertFalse(cancel_snapshot["active_context_changed"])
        self.assertEqual(self.codex.interrupt_count, 1)
        self.assertEqual(self.codex.native_compact_calls, 0)

    async def test_checkpoint_create_failure_emits_one_terminal_and_clears_state(
        self,
    ) -> None:
        topic_id = await self._create_topic("Checkpoint setup failure")
        await self._run_topic(topic_id, "Stable completed synthesis")

        with patch.object(
            self.run_store,
            "create",
            side_effect=OSError("private setup path /tmp/must-not-cross"),
        ):
            command_id, run_id = await self._draft_checkpoint(topic_id)

        terminal = [
            item
            for item in self._records(request_id=command_id)
            if item["event"]
            in {"topic.checkpoint.drafted", "topic.checkpoint.failed"}
        ]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0]["event"], "topic.checkpoint.failed")
        self.assertEqual(terminal[0]["payload"]["run_id"], run_id)
        self.assertNotIn("/tmp", json.dumps(terminal[0]))
        self.assertIsNone(self.sidecar._active_run_id)
        self.assertIsNone(self.sidecar._checkpoint_token)
        self.assertIsNone(self.sidecar._checkpoint_adapter)
        self.assertIsNone(self.sidecar._checkpoint_task)
        self.assertEqual(
            self.sidecar.topic_store.read(topic_id)["context_checkpoints"], []
        )


if __name__ == "__main__":
    unittest.main()
