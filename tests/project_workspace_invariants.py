"""No-model invariants for folder-backed Projects and topic workspaces."""

from __future__ import annotations

import json
import stat
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
from dialektike.projects import (  # noqa: E402
    PROJECT_RISK_ACKNOWLEDGEMENT,
    ProjectStore,
    ProjectUnavailableError,
)
from dialektike.runs import RunStore  # noqa: E402
from dialektike.sidecar import JsonlSidecar, PROTOCOL_NAME  # noqa: E402
from dialektike.topics import TopicStore  # noqa: E402


def _command(command_id: str, command: str, payload: dict | None = None) -> str:
    return json.dumps(
        {
            "protocol": PROTOCOL_NAME,
            "id": command_id,
            "command": command,
            "payload": payload or {},
        }
    )


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


class _Adapter:
    def __init__(self, adapter_id: str, vendor: Vendor, system: AgentSystem):
        self.adapter_id = adapter_id
        self.vendor = vendor
        self.system = system
        self.requests = []

    async def discover_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id=self.adapter_id,
            vendor=self.vendor,
            agent_system=self.system,
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
        text = f"{self.adapter_id} {request.stage.value} response"
        requested = request.participant.model_profile.requested
        return TurnResult(
            text=text,
            blocks=(StructuredContentBlock.markdown(text),),
            model_profile=request.participant.model_profile.resolved(
                ModelSelection(
                    model_id=requested.model_id,
                    effort=requested.effort,
                    service_tier=requested.service_tier,
                ),
                "fixture runtime echo",
            ),
            account_route=request.participant.auth_route,
            runtime_version=f"{self.adapter_id}-test",
        )

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None


class ProjectStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp.name).resolve()
        self.state_root = self.temp_root / "state"
        self.workspace = self.temp_root / "Live Project"
        self.workspace.mkdir(mode=0o751)
        self.store = ProjectStore(self.state_root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_registration_requires_exact_live_ack_and_preserves_external_mode(self):
        with self.assertRaises(ValueError):
            self.store.register(self.workspace, acknowledgement="yes")
        before_mode = stat.S_IMODE(self.workspace.stat().st_mode)
        project = self.store.register(
            self.workspace,
            acknowledgement=PROJECT_RISK_ACKNOWLEDGEMENT,
        )
        self.assertEqual(project["canonical_path"], str(self.workspace))
        self.assertEqual(stat.S_IMODE(self.workspace.stat().st_mode), before_mode)
        self.assertEqual(
            stat.S_IMODE((self.state_root / "projects").stat().st_mode), 0o700
        )
        for path in (
            self.state_root / "projects" / "events.jsonl",
            self.state_root / "projects" / "projects.json",
        ):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_registered_path_is_revalidated_and_never_silently_retargeted(self):
        project = self.store.register(
            self.workspace,
            acknowledgement=PROJECT_RISK_ACKNOWLEDGEMENT,
        )
        moved = self.temp_root / "moved-project"
        self.workspace.rename(moved)
        with self.assertRaises(ProjectUnavailableError):
            self.store.resolve_workspace(project["project_id"])
        listed = self.store.list_projects()
        self.assertFalse(listed[0]["available"])

    def test_replacement_at_same_path_fails_closed_until_live_reselects_it(self):
        project = self.store.register(
            self.workspace,
            acknowledgement=PROJECT_RISK_ACKNOWLEDGEMENT,
        )
        original_identity = project["workspace_identity"]
        self.workspace.rename(self.temp_root / "original-project")
        self.workspace.mkdir(mode=0o751)

        with self.assertRaises(ProjectUnavailableError):
            self.store.resolve_workspace(project["project_id"])
        self.assertFalse(self.store.list_projects()[0]["available"])

        rebound = self.store.register(
            self.workspace,
            acknowledgement=PROJECT_RISK_ACKNOWLEDGEMENT,
        )
        self.assertEqual(rebound["project_id"], project["project_id"])
        self.assertNotEqual(rebound["workspace_identity"], original_identity)
        self.assertEqual(
            [record["kind"] for record in self.store._read_records()],
            ["project_registered", "project_workspace_rebound"],
        )
        self.assertEqual(
            self.store.resolve_workspace(project["project_id"]), self.workspace
        )

    def test_legacy_identity_is_unavailable_until_explicit_reselection(self):
        project = self.store.register(
            self.workspace,
            acknowledgement=PROJECT_RISK_ACKNOWLEDGEMENT,
        )
        record = self.store._read_records()[0]
        record["schema_version"] = 1
        record["payload"].pop("workspace_identity")
        self.store.events_path.write_text(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        legacy = ProjectStore(self.state_root)
        self.assertFalse(legacy.list_projects()[0]["available"])
        with self.assertRaises(ProjectUnavailableError):
            legacy.resolve_workspace(project["project_id"])

        rebound = legacy.register(
            self.workspace,
            acknowledgement=PROJECT_RISK_ACKNOWLEDGEMENT,
        )
        self.assertEqual(rebound["project_id"], project["project_id"])
        self.assertTrue(legacy.list_projects()[0]["available"])
        self.assertEqual(
            [record["kind"] for record in legacy._read_records()],
            ["project_registered", "project_workspace_rebound"],
        )

    def test_topic_links_are_append_only_and_legacy_topics_are_unassigned(self):
        topic_store = TopicStore(self.state_root)
        legacy = topic_store.create(
            topic_id="legacy",
            participant_config={"rounds": 1, "participants": []},
        )
        events_path = self.state_root / "topics" / "legacy" / "events.jsonl"
        legacy_event = json.loads(events_path.read_text(encoding="utf-8"))
        legacy_event["payload"].pop("project_id")
        events_path.write_text(
            json.dumps(legacy_event, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        legacy = TopicStore(self.state_root).read("legacy")
        self.assertIsNone(legacy["project_id"])
        project = self.store.register(
            self.workspace,
            acknowledgement=PROJECT_RISK_ACKNOWLEDGEMENT,
        )
        linked = topic_store.set_project("legacy", project["project_id"])
        self.assertEqual(linked["project_id"], project["project_id"])
        unlinked = topic_store.set_project("legacy", None)
        self.assertIsNone(unlinked["project_id"])
        self.assertEqual(
            [event["kind"] for event in topic_store.events("legacy")],
            ["topic_created", "project_link_changed", "project_link_changed"],
        )


class ProjectSidecarTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp.name).resolve()
        self.workspace = self.temp_root / "project"
        self.workspace.mkdir(mode=0o751)
        self.output: list[str] = []
        self.codex = _Adapter("codex", Vendor.OPENAI, AgentSystem.CODEX)
        self.claude = _Adapter(
            "claude-code", Vendor.ANTHROPIC, AgentSystem.CLAUDE_CODE
        )
        self.sidecar = JsonlSidecar(
            store=RunStore(self.temp_root / "state" / "runs"),
            adapters={"codex": self.codex, "claude-code": self.claude},
            write_line=self.output.append,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _records(self) -> list[dict]:
        return [json.loads(line) for line in self.output]

    async def _discover(self) -> None:
        await self.sidecar.handle_line(
            _command("discover", "capabilities.discover")
        )

    async def _register_project(self) -> str:
        await self.sidecar.handle_line(
            _command(
                "register",
                "project.register",
                {
                    "path": str(self.workspace),
                    "acknowledgement": PROJECT_RISK_ACKNOWLEDGEMENT,
                },
            )
        )
        event = next(
            item for item in self._records() if item["event"] == "project.registered"
        )
        self.assertNotIn(str(self.workspace), json.dumps(event))
        return event["payload"]["project"]["id"]

    async def _create_topic(self, project_id: str | None) -> str:
        payload = {
            "title": "Project topic",
            "participants": _participants(),
        }
        if project_id is not None:
            payload["project_id"] = project_id
        await self.sidecar.handle_line(_command("create", "topic.create", payload))
        event = [
            item for item in self._records() if item["event"] == "topic.created"
        ][-1]
        self.assertEqual(
            event["payload"]["topic"]["summary"]["project_id"], project_id
        )
        return event["payload"]["topic"]["summary"]["id"]

    async def test_all_provider_turns_share_exact_project_cwd_without_mode_change(self):
        await self._discover()
        project_id = await self._register_project()
        first_topic = await self._create_topic(project_id)
        second_topic = await self._create_topic(project_id)
        self.assertNotEqual(first_topic, second_topic)
        before_mode = stat.S_IMODE(self.workspace.stat().st_mode)
        await self.sidecar.handle_line(
            _command(
                "run",
                "run.start",
                {
                    "topic_id": first_topic,
                    "prompt": "Inspect this project",
                    "rounds": 1,
                    "participants": _participants(),
                },
            )
        )
        await self.sidecar.wait_idle()
        requests = [*self.codex.requests, *self.claude.requests]
        self.assertEqual(len(requests), 3)
        self.assertEqual(
            {request.paths.workspace_dir for request in requests},
            {str(self.workspace)},
        )
        self.assertEqual(
            {request.paths.workspace_source for request in requests}, {"project"}
        )
        self.assertEqual(stat.S_IMODE(self.workspace.stat().st_mode), before_mode)
        run_events = next((self.temp_root / "state" / "runs").glob("*/events.jsonl"))
        self.assertIn(str(self.workspace), run_events.read_text(encoding="utf-8"))
        self.assertNotIn(str(self.workspace), "".join(self.output))

        await self.sidecar.handle_line(
            _command(
                "checkpoint",
                "topic.checkpoint.draft",
                {"topic_id": first_topic},
            )
        )
        await self.sidecar.wait_idle()
        checkpoint_request = self.codex.requests[-1]
        self.assertEqual(checkpoint_request.paths.workspace_dir, str(self.workspace))
        self.assertEqual(checkpoint_request.paths.workspace_source, "project")
        self.assertEqual(stat.S_IMODE(self.workspace.stat().st_mode), before_mode)
        self.assertNotIn(str(self.workspace), "".join(self.output))

    async def test_run_cannot_supply_a_workspace_and_unavailable_project_fails_closed(self):
        await self._discover()
        project_id = await self._register_project()
        topic_id = await self._create_topic(project_id)
        await self.sidecar.handle_line(
            _command(
                "injected",
                "run.start",
                {
                    "topic_id": topic_id,
                    "prompt": "Do not run",
                    "rounds": 1,
                    "participants": _participants(),
                    "cwd": str(self.temp_root),
                },
            )
        )
        injected_error = self._records()[-1]
        self.assertEqual(injected_error["event"], "protocol.error")
        self.assertIn("cannot supply a working directory", injected_error["payload"]["message"])
        self.workspace.rename(self.temp_root / "moved")
        await self.sidecar.handle_line(
            _command(
                "unavailable",
                "run.start",
                {
                    "topic_id": topic_id,
                    "prompt": "Do not run",
                    "rounds": 1,
                    "participants": _participants(),
                },
            )
        )
        unavailable = self._records()[-1]
        self.assertEqual(unavailable["event"], "protocol.error")
        self.assertIn("project folder is unavailable", unavailable["payload"]["message"])
        self.assertEqual(self.codex.requests, [])
        self.assertEqual(self.claude.requests, [])

    async def test_same_path_replacement_blocks_run_and_checkpoint_before_provider_calls(self):
        await self._discover()
        project_id = await self._register_project()
        topic_id = await self._create_topic(project_id)
        await self.sidecar.handle_line(
            _command(
                "seed-run",
                "run.start",
                {
                    "topic_id": topic_id,
                    "prompt": "Create checkpointable history",
                    "rounds": 1,
                    "participants": _participants(),
                },
            )
        )
        await self.sidecar.wait_idle()
        self.assertEqual(len(self.codex.requests) + len(self.claude.requests), 3)
        self.codex.requests.clear()
        self.claude.requests.clear()

        self.workspace.rename(self.temp_root / "original-project")
        self.workspace.mkdir(mode=0o751)
        await self.sidecar.handle_line(_command("list-replaced", "project.list"))
        project_list = next(
            item
            for item in self._records()
            if item.get("request_id") == "list-replaced"
        )
        self.assertFalse(project_list["payload"]["projects"][0]["available"])
        self.assertNotIn("workspace_identity", json.dumps(project_list))
        self.assertNotIn(str(self.workspace), json.dumps(project_list))

        await self.sidecar.handle_line(
            _command(
                "run-replaced",
                "run.start",
                {
                    "topic_id": topic_id,
                    "prompt": "Must not reach a provider",
                    "rounds": 1,
                    "participants": _participants(),
                },
            )
        )
        await self.sidecar.handle_line(
            _command(
                "checkpoint-replaced",
                "topic.checkpoint.draft",
                {"topic_id": topic_id},
            )
        )
        for request_id in ("run-replaced", "checkpoint-replaced"):
            failure = next(
                item
                for item in self._records()
                if item.get("request_id") == request_id
            )
            self.assertEqual(failure["event"], "protocol.error")
            self.assertIn("project folder is unavailable", failure["payload"]["message"])
        self.assertEqual(self.codex.requests, [])
        self.assertEqual(self.claude.requests, [])

    async def test_replacement_during_proposal_blocks_every_later_turn(self):
        await self._discover()
        project_id = await self._register_project()
        topic_id = await self._create_topic(project_id)
        original_run_turn = self.codex.run_turn

        async def replace_after_proposal(request, cancellation):
            result = await original_run_turn(request, cancellation)
            if request.stage.value == "proposal":
                self.workspace.rename(self.temp_root / "proposal-workspace")
                self.workspace.mkdir(mode=0o751)
            return result

        self.codex.run_turn = replace_after_proposal
        await self.sidecar.handle_line(
            _command(
                "replace-mid-run",
                "run.start",
                {
                    "topic_id": topic_id,
                    "prompt": "The replacement must stop later turns",
                    "rounds": 1,
                    "participants": _participants(),
                },
            )
        )
        await self.sidecar.wait_idle()

        self.assertEqual(len(self.codex.requests), 1)
        self.assertEqual(self.codex.requests[0].stage.value, "proposal")
        self.assertEqual(self.claude.requests, [])
        terminal = [
            item
            for item in self._records()
            if item.get("request_id") == "replace-mid-run"
            and item["event"] in {"run.completed", "run.failed", "run.cancelled"}
        ][-1]
        self.assertEqual(terminal["event"], "run.failed")
        self.assertFalse(self.sidecar.project_store.list_projects()[0]["available"])


if __name__ == "__main__":
    unittest.main()
