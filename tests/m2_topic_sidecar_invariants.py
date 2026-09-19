"""No-model invariants for the desktop topic/protocol integration."""

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

from dialektike.domain import (  # noqa: E402
    AdapterCapabilities,
    AgentSystem,
    ModelCapability,
    ModelSelection,
    StructuredContentBlock,
    TurnResult,
    Vendor,
)
from dialektike.runs import RunStore  # noqa: E402
from dialektike.sidecar import (  # noqa: E402
    JsonlSidecar,
    PROTOCOL_NAME,
    _effective_settings_for_desktop,
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


class EffectiveProjectionTests(unittest.TestCase):
    def test_only_certified_effective_controls_cross_to_the_webview(self):
        projected = _effective_settings_for_desktop({
            "effective": {
                "model_id": "runtime-echoed-model",
                "effort": None,
                "service_tier": None,
                "features": [],
                "controls": [
                    {"control_id": "runtime-style", "value": "lucid"},
                ],
            },
            "effective_authority": "runtime echo",
        })

        self.assertEqual(projected["effort"], None)
        self.assertEqual(projected["service_tier"], None)
        self.assertEqual(
            projected["controls"],
            {
                "runtime-style": {
                    "value": "lucid",
                    "authority": "runtime echo",
                    "observable": True,
                }
            },
        )


class _Adapter:
    def __init__(
        self,
        adapter_id: str,
        vendor: Vendor,
        system: AgentSystem,
        *,
        fail_first_audit: bool = False,
        efforts: tuple[str, ...] = ("high",),
        include_default_alias: bool = False,
    ) -> None:
        self.adapter_id = adapter_id
        self.vendor = vendor
        self.system = system
        self.fail_first_audit = fail_first_audit
        self.fail_audit_attempts = {1} if fail_first_audit else set()
        self.efforts = efforts
        self.include_default_alias = include_default_alias
        self.requests = []
        self.audit_attempts = 0

    async def discover_capabilities(self) -> AdapterCapabilities:
        concrete = ModelCapability(
            model_id=f"{self.adapter_id}-model",
            display_name=f"{self.adapter_id} model",
            efforts=self.efforts,
            is_default=not self.include_default_alias,
        )
        default_alias = ModelCapability(
            model_id="default",
            display_name="Default (recommended)",
            resolved_model_id=concrete.model_id,
            efforts=self.efforts,
            is_default=True,
            explicit_selectable=False,
        )
        return AdapterCapabilities(
            adapter_id=self.adapter_id,
            vendor=self.vendor,
            agent_system=self.system,
            models=(default_alias, concrete) if self.include_default_alias else (concrete,),
            runtime_version=f"{self.adapter_id}-test",
            account_route=f"{self.adapter_id}:subscription",
        )

    async def run_turn(self, request, cancellation) -> TurnResult:
        self.requests.append(request)
        if request.stage.value == "audit":
            self.audit_attempts += 1
            if self.audit_attempts in self.fail_audit_attempts:
                raise RuntimeError("private path /tmp/must-not-cross")
        requested = request.participant.model_profile.requested
        text = f"{self.adapter_id} {request.stage.value} response"
        return TurnResult(
            text=text,
            blocks=(StructuredContentBlock.markdown(text),),
            model_profile=request.participant.model_profile.resolved(
                ModelSelection(
                    model_id=requested.model_id,
                    effort=requested.effort,
                    service_tier=requested.service_tier,
                ),
                "fake runtime echo",
            ),
            account_route=request.participant.auth_route,
            runtime_version=f"{self.adapter_id}-test",
        )

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _participants() -> list[dict]:
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


def _unconfigured_participants() -> list[dict]:
    participants = _participants()
    for participant in participants:
        participant["requested"]["model"] = ""
        participant["requested"]["effort"] = ""
    return participants


class TopicSidecarTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output: list[str] = []
        self.codex = _Adapter("codex", Vendor.OPENAI, AgentSystem.CODEX)
        self.claude = _Adapter(
            "claude-code", Vendor.ANTHROPIC, AgentSystem.CLAUDE_CODE
        )
        self.sidecar = JsonlSidecar(
            store=RunStore(Path(self.temp.name) / "runs"),
            adapters={"codex": self.codex, "claude-code": self.claude},
            write_line=self.output.append,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _records(self) -> list[dict]:
        return [json.loads(line) for line in self.output]

    async def _discover_and_create(self) -> str:
        await self.sidecar.handle_line(
            _command("discover", "capabilities.discover")
        )
        await self.sidecar.handle_line(
            _command(
                "create",
                "topic.create",
                {"title": "Persistent topic", "participants": _participants()},
            )
        )
        created = next(
            item for item in self._records() if item["event"] == "topic.created"
        )
        summary = created["payload"]["topic"]["summary"]
        self.assertIsInstance(summary["created_at"], str)
        self.assertIsInstance(summary["updated_at"], str)
        self.assertIsInstance(summary["active_run"], bool)
        return created["payload"]["topic"]["summary"]["id"]

    async def _run(self, topic_id: str, prompt: str, command_id: str) -> None:
        await self.sidecar.handle_line(
            _command(
                command_id,
                "run.start",
                {
                    "topic_id": topic_id,
                    "prompt": prompt,
                    "rounds": 1,
                    "participants": _participants(),
                },
            )
        )
        await self.sidecar.wait_idle()

    async def test_cycles_persist_and_follow_up_context_is_lean(self) -> None:
        topic_id = await self._discover_and_create()
        await self._run(topic_id, "First Live message", "run-1")
        await self._run(topic_id, "Second Live message", "run-2")

        second_proposal = self.codex.requests[2]
        self.assertIn("First Live message", second_proposal.input_text)
        self.assertIn("codex synthesis response", second_proposal.input_text)
        self.assertNotIn("claude-code audit response", second_proposal.input_text)
        self.assertIn("Second Live message", second_proposal.input_text)

        await self.sidecar.handle_line(
            _command("read", "topic.read", {"topic_id": topic_id})
        )
        detail = [
            item["payload"]["topic"]
            for item in self._records()
            if item["event"] == "topic.loaded"
        ][-1]
        self.assertEqual([item["cycle"] for item in detail["prompts"]], [1, 2])
        self.assertEqual(
            [item["stage"] for item in detail["messages"]],
            ["proposal", "audit", "synthesis"] * 2,
        )
        for message in detail["messages"]:
            self.assertEqual(
                message["blocks"],
                [
                    {
                        "type": "markdown",
                        "text": message["text"],
                        "code": None,
                        "diff": None,
                        "language": None,
                        "title": None,
                        "summary": None,
                        "status": None,
                        "label": None,
                        "url": None,
                    }
                ],
            )
            self.assertEqual(
                set(message["effective"]),
                {"model", "effort", "service_tier", "authority"},
            )
            self.assertIsInstance(message["effective"]["model"], str)
            self.assertIsInstance(message["effective"]["authority"], str)

    async def test_topic_may_store_unconfigured_seats_but_run_requires_live_choices(self) -> None:
        await self.sidecar.handle_line(
            _command("discover-unconfigured", "capabilities.discover")
        )
        await self.sidecar.handle_line(
            _command(
                "create-unconfigured",
                "topic.create",
                {"participants": _unconfigured_participants()},
            )
        )
        created = next(
            item
            for item in self._records()
            if item.get("request_id") == "create-unconfigured"
        )
        self.assertEqual(created["event"], "topic.created")
        detail = created["payload"]["topic"]
        self.assertEqual(
            [seat["requested"]["model"] for seat in detail["participants"]],
            ["", ""],
        )
        self.assertEqual(
            [seat["requested"]["effort"] for seat in detail["participants"]],
            ["", ""],
        )

        await self.sidecar.handle_line(
            _command(
                "run-unconfigured",
                "run.start",
                {
                    "topic_id": detail["summary"]["id"],
                    "prompt": "Must not run",
                    "rounds": 1,
                    "participants": _unconfigured_participants(),
                },
            )
        )
        failure = next(
            item
            for item in self._records()
            if item.get("request_id") == "run-unconfigured"
        )
        self.assertEqual(failure["event"], "protocol.error")
        self.assertIn("select an explicit advertised model", failure["payload"]["message"])

    async def test_run_requires_effort_only_when_the_model_advertises_it(self) -> None:
        await self.sidecar.handle_line(
            _command("discover-effort", "capabilities.discover")
        )
        missing_effort = _participants()
        for participant in missing_effort:
            participant["requested"]["effort"] = ""
        await self.sidecar.handle_line(
            _command(
                "create-missing-effort",
                "topic.create",
                {"participants": missing_effort},
            )
        )
        created = next(
            item
            for item in self._records()
            if item.get("request_id") == "create-missing-effort"
        )
        await self.sidecar.handle_line(
            _command(
                "run-missing-effort",
                "run.start",
                {
                    "topic_id": created["payload"]["topic"]["summary"]["id"],
                    "prompt": "Must not run",
                    "rounds": 1,
                    "participants": missing_effort,
                },
            )
        )
        failure = next(
            item
            for item in self._records()
            if item.get("request_id") == "run-missing-effort"
        )
        self.assertEqual(failure["event"], "protocol.error")
        self.assertIn("requires an explicit effort selection", failure["payload"]["message"])

        effortless_output: list[str] = []
        effortless = JsonlSidecar(
            store=RunStore(Path(self.temp.name) / "effortless-runs"),
            adapters={
                "codex": _Adapter("codex", Vendor.OPENAI, AgentSystem.CODEX, efforts=()),
                "claude-code": _Adapter("claude-code", Vendor.ANTHROPIC, AgentSystem.CLAUDE_CODE, efforts=()),
            },
            write_line=effortless_output.append,
        )
        await effortless.handle_line(_command("discover-none", "capabilities.discover"))
        await effortless.handle_line(
            _command("create-none", "topic.create", {"participants": missing_effort})
        )
        effortless_created = next(
            json.loads(line)
            for line in effortless_output
            if json.loads(line).get("request_id") == "create-none"
        )
        await effortless.handle_line(
            _command(
                "run-none",
                "run.start",
                {
                    "topic_id": effortless_created["payload"]["topic"]["summary"]["id"],
                    "prompt": "Run without an invented effort",
                    "rounds": 1,
                    "participants": missing_effort,
                },
            )
        )
        await effortless.wait_idle()
        effortless_events = [json.loads(line)["event"] for line in effortless_output]
        self.assertIn("run.completed", effortless_events)

    async def test_runtime_default_alias_is_not_an_explicit_desktop_model_choice(self) -> None:
        alias_output: list[str] = []
        aliased = JsonlSidecar(
            store=RunStore(Path(self.temp.name) / "alias-runs"),
            adapters={
                "codex": _Adapter(
                    "codex",
                    Vendor.OPENAI,
                    AgentSystem.CODEX,
                    include_default_alias=True,
                ),
                "claude-code": _Adapter(
                    "claude-code",
                    Vendor.ANTHROPIC,
                    AgentSystem.CLAUDE_CODE,
                    include_default_alias=True,
                ),
            },
            write_line=alias_output.append,
        )
        await aliased.handle_line(_command("discover-alias", "capabilities.discover"))
        discovery = next(
            json.loads(line)
            for line in alias_output
            if json.loads(line).get("request_id") == "discover-alias"
        )
        for runtime in discovery["payload"]["providers"]:
            alias = next(model for model in runtime["models"] if model["id"] == "default")
            self.assertFalse(alias["explicit_selectable"])

        alias_participants = _participants()
        for participant in alias_participants:
            participant["requested"]["model"] = "default"
        await aliased.handle_line(
            _command("create-alias", "topic.create", {"participants": alias_participants})
        )
        create_failure = next(
            json.loads(line)
            for line in alias_output
            if json.loads(line).get("request_id") == "create-alias"
        )
        self.assertEqual(create_failure["event"], "protocol.error")
        self.assertIn("runtime-default alias", create_failure["payload"]["message"])

        await aliased.handle_line(
            _command("create-concrete", "topic.create", {"participants": _participants()})
        )
        concrete = next(
            json.loads(line)
            for line in alias_output
            if json.loads(line).get("request_id") == "create-concrete"
        )
        topic_id = concrete["payload"]["topic"]["summary"]["id"]
        await aliased.handle_line(
            _command(
                "update-alias",
                "topic.update",
                {"topic_id": topic_id, "participants": alias_participants},
            )
        )
        update_failure = next(
            json.loads(line)
            for line in alias_output
            if json.loads(line).get("request_id") == "update-alias"
        )
        self.assertEqual(update_failure["event"], "protocol.error")
        self.assertIn("runtime-default alias", update_failure["payload"]["message"])

        await aliased.handle_line(
            _command(
                "run-alias",
                "run.start",
                {
                    "topic_id": topic_id,
                    "prompt": "Must choose a concrete model",
                    "rounds": 1,
                    "participants": alias_participants,
                },
            )
        )
        failure = next(
            json.loads(line)
            for line in alias_output
            if json.loads(line).get("request_id") == "run-alias"
        )
        self.assertEqual(failure["event"], "protocol.error")
        self.assertIn("runtime-default alias", failure["payload"]["message"])

    async def test_latest_topic_evidence_reloads_after_sidecar_restart(self) -> None:
        topic_id = await self._discover_and_create()
        await self._run(topic_id, "Persist evidence", "run-evidence")
        state = self.sidecar.topic_store.read(topic_id)
        latest_run_id = state["linked_run_ids"][-1]

        restarted_output: list[str] = []
        restarted = JsonlSidecar(
            store=RunStore(Path(self.temp.name) / "runs"),
            adapters={"codex": self.codex, "claude-code": self.claude},
            write_line=restarted_output.append,
        )
        await restarted.handle_line(
            _command(
                "historical-evidence",
                "topic.evidence.read",
                {"topic_id": topic_id},
            )
        )
        event = json.loads(restarted_output[-1])
        self.assertEqual(event["event"], "topic.evidence.loaded")
        self.assertEqual(event["request_id"], "historical-evidence")
        self.assertEqual(event["payload"]["topic_id"], topic_id)
        self.assertEqual(
            event["payload"]["summary"]["run_id"], latest_run_id
        )
        encoded = json.dumps(event)
        self.assertNotIn(str(Path(self.temp.name)), encoded)
        self.assertNotIn("evidence_summary.json", encoded)

    async def test_topic_evidence_distinguishes_none_from_unavailable_latest(self) -> None:
        topic_id = await self._discover_and_create()
        await self.sidecar.handle_line(
            _command(
                "no-evidence",
                "topic.evidence.read",
                {"topic_id": topic_id},
            )
        )
        none_event = self._records()[-1]
        self.assertEqual(none_event["event"], "topic.evidence.unavailable")
        self.assertIn("No saved", none_event["payload"]["message"])

        await self._run(topic_id, "First evidence", "run-first-evidence")
        await self._run(topic_id, "Latest evidence", "run-latest-evidence")
        state = self.sidecar.topic_store.read(topic_id)
        latest_run_id = state["linked_run_ids"][-1]
        summary_path = (
            Path(self.temp.name)
            / "runs"
            / latest_run_id
            / "evidence_summary.json"
        )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["raw_capture"]["path"] = "/private/must-not-cross"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        summary_path.chmod(0o600)

        await self.sidecar.handle_line(
            _command(
                "bad-latest-evidence",
                "topic.evidence.read",
                {"topic_id": topic_id},
            )
        )
        unavailable = self._records()[-1]
        self.assertEqual(unavailable["event"], "topic.evidence.unavailable")
        self.assertIn("unavailable", unavailable["payload"]["message"])
        self.assertNotIn("/private", json.dumps(unavailable))
        self.assertEqual(unavailable["request_id"], "bad-latest-evidence")

    async def test_sidebar_crud_events_are_real_and_delete_is_a_tombstone(self) -> None:
        topic_id = await self._discover_and_create()
        await self.sidecar.handle_line(
            _command(
                "update",
                "topic.update",
                {"topic_id": topic_id, "pinned": True, "archived": True},
            )
        )
        updated = [
            item for item in self._records() if item["event"] == "topic.updated"
        ][-1]["payload"]["topic"]["summary"]
        self.assertTrue(updated["pinned"])
        self.assertTrue(updated["archived"])

        await self.sidecar.handle_line(
            _command("delete", "topic.delete", {"topic_id": topic_id})
        )
        await self.sidecar.handle_line(
            _command("list", "topic.list", {"archived": None})
        )
        listed = [
            item for item in self._records() if item["event"] == "topic.list.result"
        ][-1]["payload"]["topics"]
        self.assertEqual(listed, [])
        retained = self.sidecar.topic_store.read(topic_id, include_deleted=True)
        self.assertTrue(retained["deleted"])
        self.assertEqual(
            [item["kind"] for item in self.sidecar.topic_store.events(topic_id)][-1],
            "topic_deleted",
        )

    async def test_failed_audit_pauses_and_only_matching_live_resolution_resumes(self) -> None:
        self.claude.fail_audit_attempts = {1, 2}
        topic_id = await self._discover_and_create()
        await self.sidecar.handle_line(
            _command(
                "start",
                "run.start",
                {
                    "topic_id": topic_id,
                    "prompt": "Pause safely",
                    "rounds": 1,
                    "participants": _participants(),
                },
            )
        )
        for _ in range(100):
            paused = [
                item
                for item in self._records()
                if item["event"] == "audit.failure.paused"
            ]
            if paused:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(paused)
        pause = paused[-1]["payload"]
        self.assertNotIn("/tmp", json.dumps(pause))

        await self.sidecar.handle_line(
            _command(
                "stale-stop",
                "run.stop",
                {"run_id": "not-the-active-run"},
            )
        )
        self.assertEqual(
            [
                item
                for item in self._records()
                if item.get("request_id") == "stale-stop"
            ][-1]["event"],
            "protocol.error",
        )

        await self.sidecar.handle_line(
            _command(
                "resolve",
                "audit.failure.resolve",
                {
                    "run_id": pause["run_id"],
                    "failure_id": pause["failure_id"],
                    "resolution": "retry_failed",
                },
            )
        )
        for _ in range(100):
            paused = [
                item
                for item in self._records()
                if item["event"] == "audit.failure.paused"
            ]
            if len(paused) >= 2:
                break
            await asyncio.sleep(0.01)
        self.assertGreaterEqual(len(paused), 2)
        second_pause = paused[-1]["payload"]
        self.assertNotEqual(pause["failure_id"], second_pause["failure_id"])

        await self.sidecar.handle_line(
            _command(
                "stale-resolution",
                "audit.failure.resolve",
                {
                    "run_id": pause["run_id"],
                    "failure_id": pause["failure_id"],
                    "resolution": "retry_failed",
                },
            )
        )
        self.assertEqual(
            [
                item
                for item in self._records()
                if item.get("request_id") == "stale-resolution"
            ][-1]["event"],
            "protocol.error",
        )

        await self.sidecar.handle_line(
            _command(
                "resolve-again",
                "audit.failure.resolve",
                {
                    "run_id": second_pause["run_id"],
                    "failure_id": second_pause["failure_id"],
                    "resolution": "retry_failed",
                },
            )
        )
        await self.sidecar.wait_idle()
        events = [item["event"] for item in self._records()]
        self.assertIn("audit.failure.resumed", events)
        self.assertIn("run.completed", events)
        self.assertEqual(self.claude.audit_attempts, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
