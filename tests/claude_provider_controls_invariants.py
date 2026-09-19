"""No-model invariants for Claude descriptor controls and SDK options.

Run: ``./venv/bin/python tests/claude_provider_controls_invariants.py``.
No provider runtime is contacted and no subscription turn is consumed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import warnings
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from claude_agent_sdk import (
    AssistantMessage,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    PermissionResultAllow,
    ResultMessage,
    TextBlock,
)
from claude_agent_sdk.types import (
    _get_can_use_tool_shadowed_warning,
    _warn_if_can_use_tool_shadowed,
)

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dialektike.adapters.base import AdapterError  # noqa: E402
from dialektike.adapters.claude import (  # noqa: E402
    CLAUDE_CALLBACK_SHORT_CIRCUIT_PERMISSION_MODES,
    CLAUDE_EPHEMERAL_ARGS,
    CLAUDE_PERMISSION_MECHANISM_MATRIX,
    CLAUDE_SDK_OPTION_AUTHORITY,
    CLAUDE_TYPED_PERMISSION_MODES,
    _claude_requested_options,
    _claude_sdk_option_snapshot,
    _claude_sdk_options,
)
from core.broker import ChainedLog  # noqa: E402
from dialektike.domain import (  # noqa: E402
    AgentSystem,
    ControlValue,
    ExecutionProfile,
    ModelProfile,
    ModelSelection,
    Participant,
    Role,
    TurnPaths,
    TurnRequest,
    TurnStage,
    Vendor,
)
from dialektike.providers.approved import approved_descriptor_records  # noqa: E402
from dialektike.providers.contract import DescriptorError  # noqa: E402
from dialektike.orchestrator import CancellationToken  # noqa: E402


def claude_descriptor():
    return next(
        record.descriptor
        for record in approved_descriptor_records()
        if record.descriptor.runtime_id == "claude-code"
    )


def profile_values(profile_id: str) -> tuple[ControlValue, ...]:
    descriptor = claude_descriptor()
    return next(
        profile.values
        for profile in descriptor.execution_profiles
        if profile.profile_id == profile_id
    )


def turn_request(
    *,
    profile_id: str = "inherit-native",
    values: tuple[ControlValue, ...] | None = None,
    thinking: str | None = None,
) -> TurnRequest:
    controls = () if thinking is None else (ControlValue("thinking", thinking),)
    participant = Participant(
        participant_id="claude-auditor",
        vendor=Vendor.ANTHROPIC,
        agent_system=AgentSystem.CLAUDE_CODE,
        adapter_id="claude-code",
        auth_route="claude-subscription",
        model_profile=ModelProfile(
            requested=ModelSelection(
                model_id="claude-opus-5",
                effort="xhigh",
                controls=controls,
            )
        ),
        execution_profile=ExecutionProfile(
            profile_id=profile_id,
            values=profile_values(profile_id) if values is None else values,
        ),
    )
    return TurnRequest(
        run_id="control-fixture",
        round_number=1,
        turn_number=1,
        role=Role.AUDITOR,
        participant=participant,
        original_prompt="Review this.",
        input_text="Review this proposal.",
        paths=TurnPaths(
            run_path="/tmp/control-fixture",
            raw_dir="/tmp/control-fixture/raw",
            workspace_dir="/tmp/control-fixture/workspace",
            decisions_path="/tmp/control-fixture/decisions.jsonl",
        ),
        stage=TurnStage.AUDIT,
    )


class ClaudeDescriptorTests(unittest.TestCase):
    def test_profiles_are_fixed_reviewed_mappings_with_native_default(self):
        descriptor = claude_descriptor()
        profiles = {
            profile.profile_id: {
                item.control_id: item.value for item in profile.values
            }
            for profile in descriptor.execution_profiles
        }
        self.assertEqual(descriptor.default_selection.execution_profile,
                         "inherit-native")
        self.assertEqual(profiles["inherit-native"], {})
        self.assertEqual(
            profiles,
            {
                "inherit-native": {},
                "manual": {
                    "permission-mode": "default",
                    "setting-sources": "native-default",
                },
                "edit-automatically": {
                    "permission-mode": "acceptEdits",
                    "setting-sources": "native-default",
                },
                "plan": {
                    "permission-mode": "plan",
                    "setting-sources": "native-default",
                },
                "auto": {
                    "permission-mode": "auto",
                    "setting-sources": "native-default",
                },
                "dont-ask": {
                    "permission-mode": "dontAsk",
                    "setting-sources": "native-default",
                },
            },
        )
        for profile in descriptor.execution_profiles:
            descriptor.validate_execution_profile(
                ExecutionProfile(profile.profile_id, profile.values)
            )
        with self.assertRaisesRegex(DescriptorError, "exactly match"):
            descriptor.validate_execution_profile(ExecutionProfile("manual"))

    def test_bypass_and_isolated_values_remain_unavailable(self):
        controls = {
            control.control_id: control for control in claude_descriptor().control_schema
        }
        permission_options = {
            option.value: option for option in controls["permission-mode"].options
        }
        settings_options = {
            option.value: option for option in controls["setting-sources"].options
        }
        self.assertFalse(
            permission_options["bypassPermissions"].availability.available
        )
        self.assertIn(
            "separate ruling from Live",
            permission_options["bypassPermissions"].availability.reason or "",
        )
        self.assertFalse(settings_options["isolated"].availability.available)
        self.assertIn(
            "separate ruling from Live",
            settings_options["isolated"].availability.reason or "",
        )

    def test_external_rules_are_explicitly_not_observable(self):
        descriptor = claude_descriptor()
        permissions = next(
            facility
            for facility in descriptor.runtime_facilities
            if facility.facility_id == "permissions"
        )
        self.assertEqual(permissions.observability, "not-observable")
        self.assertEqual(permissions.management, "runtime-native")
        manual = next(
            profile
            for profile in descriptor.execution_profiles
            if profile.profile_id == "manual"
        )
        self.assertIn("not observable", manual.description)
        inherited = next(
            profile
            for profile in descriptor.execution_profiles
            if profile.profile_id == "inherit-native"
        )
        self.assertIn("Ask requests that reach can_use_tool", inherited.description)
        self.assertIn("may bypass the callback", inherited.description)
        self.assertIn("Ask requests that reach can_use_tool", permissions.description)
        self.assertIn("effective external rule source is not observable",
                      permissions.description)


class ClaudePermissionMechanismTests(unittest.TestCase):
    def test_installed_sdk_shadow_matrix_is_exhaustive_and_fail_honest(self):
        by_id = {
            item.mechanism_id: item
            for item in CLAUDE_PERMISSION_MECHANISM_MATRIX
        }
        self.assertEqual(
            set(by_id),
            {
                "permission-mode.accept-edits",
                "permission-mode.auto",
                "permission-mode.dont-ask",
                "permission-mode.bypass-permissions",
                "allowed-tools.whole-tool",
                "skills.derived-whole-tool",
                "settings.permissions-default-mode",
                "settings.permissions-allow",
                "settings.permissions-deny",
                "hooks.pre-tool-use-decision",
                "sandbox.auto-allow-bash",
            },
        )
        self.assertTrue(all(not item.effective_observable for item in by_id.values()))
        self.assertEqual(
            {
                item.mechanism_id
                for item in by_id.values()
                if item.sdk_warning_detects
            },
            {
                "permission-mode.bypass-permissions",
                "allowed-tools.whole-tool",
                "skills.derived-whole-tool",
            },
        )
        self.assertIn("separate ruling from Live",
                      by_id["permission-mode.bypass-permissions"].adapter_state)
        self.assertIn("not enumerable",
                      by_id["hooks.pre-tool-use-decision"].adapter_state)

        # This is anchored to the installed SDK's Literal rather than merely
        # comparing two hand-written copies of the matrix. ``default`` is the
        # ordinary ask path and ``plan`` performs no actual execution; every
        # typed mode that can pre-resolve an execution decision has a row.
        self.assertEqual(
            CLAUDE_TYPED_PERMISSION_MODES,
            {
                "default",
                "acceptEdits",
                "plan",
                "bypassPermissions",
                "dontAsk",
                "auto",
            },
        )
        self.assertEqual(
            set(CLAUDE_CALLBACK_SHORT_CIRCUIT_PERMISSION_MODES),
            CLAUDE_TYPED_PERMISSION_MODES - {"default", "plan"},
        )
        self.assertTrue(
            set(CLAUDE_CALLBACK_SHORT_CIRCUIT_PERMISSION_MODES.values())
            <= set(by_id)
        )
        inherited_default = by_id["settings.permissions-default-mode"]
        self.assertFalse(inherited_default.requested_observable)
        self.assertFalse(inherited_default.sdk_warning_detects)

    def test_installed_sdk_warning_is_advisory_not_a_complete_detector(self):
        self.assertIsNone(_get_can_use_tool_shadowed_warning("acceptEdits", []))
        self.assertIsNone(_get_can_use_tool_shadowed_warning("auto", []))
        self.assertIsNone(_get_can_use_tool_shadowed_warning("dontAsk", []))
        self.assertIn(
            "bypassPermissions",
            _get_can_use_tool_shadowed_warning("bypassPermissions", []) or "",
        )
        self.assertIn(
            "Read",
            _get_can_use_tool_shadowed_warning("default", ["Read"]) or "",
        )

        async def callback(tool_name, tool_input, context):
            raise AssertionError("warning inspection must not invoke callback")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", CanUseToolShadowedWarning)
            _warn_if_can_use_tool_shadowed(
                ClaudeAgentOptions(can_use_tool=callback, skills="all")
            )
        self.assertEqual(len(caught), 1)
        self.assertIn("Skill", str(caught[0].message))

        defaults = ClaudeAgentOptions()
        self.assertEqual(defaults.allowed_tools, [])
        self.assertIsNone(defaults.skills)
        self.assertIsNone(defaults.sandbox)
        self.assertIsNone(defaults.setting_sources)


class ClaudeSdkOptionTests(unittest.TestCase):
    def test_inherit_native_does_not_override_permission_or_settings(self):
        request = turn_request()
        mapped = _claude_requested_options(request)
        self.assertEqual(
            mapped,
            {
                "thinking": None,
                "permission_mode": None,
                "setting_sources": None,
                "execution_profile": "inherit-native",
            },
        )

        async def can_use_tool(tool_name, tool_input, context):
            raise AssertionError("construction test must not invoke the callback")

        options = _claude_sdk_options(
            workspace=Path("/tmp/control-fixture/workspace"),
            cli_path=Path("/Applications/Claude.app/Contents/MacOS/claude"),
            requested=request.participant.model_profile.requested,
            requested_options=mapped,
            can_use_tool=can_use_tool,
            hooks={},
        )
        self.assertIsNone(options.permission_mode)
        self.assertIsNone(options.setting_sources)
        self.assertIsNone(options.thinking)
        self.assertEqual(options.allowed_tools, [])
        self.assertIsNone(options.skills)
        self.assertIsNone(options.sandbox)
        self.assertEqual(options.extra_args, CLAUDE_EPHEMERAL_ARGS)
        self.assertIs(options.can_use_tool, can_use_tool)
        self.assertEqual(
            _claude_sdk_option_snapshot(options),
            {
                "snapshot_scope": "turn-and-permission-options",
                "model": "claude-opus-5",
                "effort": "xhigh",
                "thinking": None,
                "permission_mode": None,
                "setting_sources": None,
                "allowed_tools": [],
                "skills": None,
                "sandbox": None,
                "can_use_tool_installed": True,
                "pre_tool_use_hooks": [],
                "pre_compact_hooks": [],
                "post_tool_use_hooks": [],
            },
        )

    def test_each_reviewed_profile_maps_to_the_exact_sdk_permission_mode(self):
        expected = {
            "manual": "default",
            "edit-automatically": "acceptEdits",
            "plan": "plan",
            "auto": "auto",
            "dont-ask": "dontAsk",
        }
        for profile_id, permission_mode in expected.items():
            with self.subTest(profile_id=profile_id):
                mapped = _claude_requested_options(
                    turn_request(profile_id=profile_id, thinking="adaptive")
                )
                self.assertEqual(mapped["permission_mode"], permission_mode)
                self.assertEqual(mapped["setting_sources"], None)
                self.assertEqual(mapped["thinking"], {"type": "adaptive"})

    def test_thinking_disabled_maps_to_the_sdk_typed_shape(self):
        request = turn_request(thinking="disabled")
        mapped = _claude_requested_options(request)
        options = _claude_sdk_options(
            workspace=Path("/tmp/workspace"),
            cli_path=Path("/tmp/claude"),
            requested=request.participant.model_profile.requested,
            requested_options=mapped,
            can_use_tool=None,
            hooks={},
        )
        self.assertEqual(options.thinking, {"type": "disabled"})
        self.assertEqual(options.model, "claude-opus-5")
        self.assertEqual(options.effort, "xhigh")

    def test_adapter_rejects_unapproved_bypass_and_isolation_defensively(self):
        bypass = turn_request(
            profile_id="manual",
            values=(
                ControlValue("permission-mode", "bypassPermissions"),
                ControlValue("setting-sources", "native-default"),
            ),
        )
        with self.assertRaisesRegex(AdapterError, "unsupported governed"):
            _claude_requested_options(bypass)

        isolated = turn_request(
            profile_id="manual",
            values=(
                ControlValue("permission-mode", "default"),
                ControlValue("setting-sources", "isolated"),
            ),
        )
        with self.assertRaisesRegex(AdapterError, "separate Live ruling"):
            _claude_requested_options(isolated)


class ClaudePermissionFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_ask_is_exactly_once_and_native_auto_has_no_fabricated_card(self):
        presenter_calls: list[str] = []
        clients = []

        def presenter(request, card):
            presenter_calls.append(request.correlation_id)
            return "allow"

        class FakeClaudeClient:
            def __init__(self, *, options):
                self.options = options
                self.permission_results = []
                clients.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get_server_info(self):
                return {
                    "models": [
                        {
                            "value": "claude-opus-5",
                            "displayName": "Claude Opus 5",
                            "resolvedModel": "claude-opus-5",
                            "supportedEffortLevels": ["xhigh"],
                        }
                    ]
                }

            async def query(self, text):
                self.query_text = text

            async def receive_response(self):
                context = SimpleNamespace(
                    title="Claude wants to read fixture.txt",
                    display_name="Read file",
                    description="Read a fixture",
                    blocked_path="fixture.txt",
                    decision_reason="Native policy asks",
                    suggestions=[],
                    tool_use_id="ask-tool-1",
                    agent_id=None,
                )
                self.permission_results.append(
                    await self.options.can_use_tool(
                        "Read", {"file_path": "fixture.txt"}, context
                    )
                )
                # The same native wire identity is a retransmission, not a
                # second permission card.
                self.permission_results.append(
                    await self.options.can_use_tool(
                        "Read", {"file_path": "fixture.txt"}, context
                    )
                )
                post = self.options.hooks["PostToolUse"][0].hooks[0]
                await post(
                    {
                        "tool_name": "Read",
                        "tool_input": {"file_path": "fixture.txt"},
                        "tool_response": "relayed result",
                    },
                    "ask-tool-1",
                    {"signal": None},
                )
                # This completion was never delivered to can_use_tool. It
                # represents a native rule that auto-permitted the action.
                await post(
                    {
                        "tool_name": "Read",
                        "tool_input": {"file_path": "native-auto.txt"},
                        "tool_response": "native result",
                    },
                    "native-auto-tool-1",
                    {"signal": None},
                )
                pre_compact = self.options.hooks["PreCompact"][0].hooks[0]
                await pre_compact(
                    {
                        "hook_event_name": "PreCompact",
                        "trigger": "auto",
                        "session_id": "private-native-session",
                        "transcript_path": "/private/transcripts/secret.jsonl",
                        "cwd": "/private/workspace",
                        "custom_instructions": "private compact instructions",
                    },
                    None,
                    {"signal": None},
                )
                yield AssistantMessage(
                    content=[TextBlock("Permission flow complete")],
                    model="claude-opus-5",
                )
                yield ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="session-1",
                    result="Permission flow complete",
                )

            async def interrupt(self):
                return None

            async def disconnect(self):
                return None

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = TurnPaths(
                run_path=str(root),
                raw_dir=str(root / "raw"),
                workspace_dir=str(root / "workspace"),
                decisions_path=str(root / "decisions.jsonl"),
            )
            request = replace(
                turn_request(thinking="adaptive"),
                paths=paths,
            )
            from dialektike.adapters import claude as claude_adapter_module

            with (
                patch.object(
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
                ),
                patch.object(
                    claude_adapter_module,
                    "ClaudeSDKClient",
                    FakeClaudeClient,
                ),
            ):
                result = await claude_adapter_module.ClaudeCodeRuntimeAdapter(
                    presenter
                ).run_turn(request, CancellationToken())

            self.assertEqual(len(presenter_calls), 1)
            self.assertEqual(len(clients), 1)
            self.assertTrue(
                all(
                    isinstance(item, PermissionResultAllow)
                    for item in clients[0].permission_results
                )
            )
            records = ChainedLog(root / "decisions.jsonl").verified_records()
            self.assertEqual(
                sum(record["kind"] == "permission_decision" for record in records),
                1,
            )
            self.assertEqual(
                sum(record["kind"] == "replay_returned" for record in records),
                1,
            )
            relayed = next(
                record for record in records if record["kind"] == "tool_completed"
            )
            native_auto = next(
                record
                for record in records
                if record["kind"] == "native_auto_permitted"
            )
            self.assertEqual(
                relayed["annotations"]["decision_provenance"],
                "relayed_approval",
            )
            self.assertEqual(
                native_auto["annotations"]["decision_provenance"],
                "native_auto",
            )

            effective = result.model_profile.effective
            self.assertIsNotNone(effective)
            self.assertEqual(effective.model_id, "claude-opus-5")
            self.assertIsNone(effective.effort)
            self.assertEqual(effective.controls, ())
            evidence = dict(result.evidence)
            self.assertEqual(evidence["effort_requested"], "xhigh")
            self.assertEqual(evidence["effort_effective_observable"], "false")
            self.assertEqual(
                json.loads(evidence["thinking_requested"]),
                {"type": "adaptive"},
            )
            self.assertEqual(evidence["thinking_effective_observable"], "false")
            self.assertEqual(
                evidence["permission_mode_effective_observable"],
                "false",
            )
            self.assertEqual(
                evidence["execution_profile_effective_observable"],
                "false",
            )
            self.assertEqual(
                evidence["sdk_options_authority"],
                CLAUDE_SDK_OPTION_AUTHORITY,
            )
            self.assertEqual(
                CLAUDE_SDK_OPTION_AUTHORITY,
                "claude-agent-sdk 0.2.116 typed options",
            )
            sdk_options = json.loads(evidence["sdk_options_requested"])
            self.assertEqual(
                sdk_options["snapshot_scope"],
                "turn-and-permission-options",
            )
            self.assertEqual(sdk_options["allowed_tools"], [])
            self.assertIsNone(sdk_options["skills"])
            self.assertIsNone(sdk_options["sandbox"])
            self.assertIsNone(sdk_options["setting_sources"])
            self.assertEqual(sdk_options["pre_tool_use_hooks"], [])
            self.assertEqual(sdk_options["pre_compact_hooks"], ["PreCompact"])
            self.assertEqual(
                sdk_options["post_tool_use_hooks"],
                ["PostToolUse", "PostToolUseFailure"],
            )
            self.assertTrue(sdk_options["can_use_tool_installed"])
            self.assertEqual(
                evidence["external_allow_rules_observable"],
                "false",
            )
            self.assertEqual(
                evidence["external_pre_tool_use_hooks_observable"],
                "false",
            )
            self.assertEqual(
                evidence["external_sandbox_rules_observable"],
                "false",
            )
            self.assertEqual(evidence["native_compaction_event_count"], "1")
            self.assertEqual(
                json.loads(evidence["native_compaction_triggers"]),
                ["auto"],
            )
            self.assertIn(
                "PreCompact hook; observation only",
                evidence["native_compaction_authority"],
            )

            capture = [
                json.loads(line)
                for line in (root / "raw" / "claude_events.redacted.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            started = next(item for item in capture if item["type"] == "capture_started")
            self.assertEqual(started["sdk_options_requested"], sdk_options)
            self.assertEqual(
                started["sdk_options_authority"],
                CLAUDE_SDK_OPTION_AUTHORITY,
            )
            self.assertFalse(started["external_allow_rules_observable"])
            self.assertFalse(started["external_pre_tool_use_hooks_observable"])
            self.assertFalse(started["external_sandbox_rules_observable"])
            self.assertFalse(started["effort_effective_observable"])
            self.assertFalse(started["thinking_effective_observable"])
            self.assertFalse(started["permission_mode_effective_observable"])
            self.assertFalse(started["execution_profile_effective_observable"])
            observed = next(
                item
                for item in capture
                if item["type"] == "native_compaction_observed"
            )
            self.assertEqual(observed["hook_event"], "PreCompact")
            self.assertEqual(observed["trigger"], "auto")
            self.assertFalse(observed["topic_checkpoint_mutated"])
            self.assertTrue(observed["custom_instructions_present"])
            serialized_capture = json.dumps(capture, ensure_ascii=False)
            self.assertNotIn("private-native-session", serialized_capture)
            self.assertNotIn(
                "/private/transcripts/secret.jsonl", serialized_capture
            )
            self.assertNotIn("/private/workspace", serialized_capture)
            self.assertNotIn("private compact instructions", serialized_capture)


if __name__ == "__main__":
    unittest.main(verbosity=2)
