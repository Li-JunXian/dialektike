"""No-model invariants for the generic provider descriptor contract.

Run: ``./venv/bin/python tests/provider_contract_invariants.py``.
No provider runtime is contacted and no subscription turn is consumed.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.broker import ChainedLog, canonical, sha256_text  # noqa: E402
from core.relay import NormalizedRequest, PermissionRelay  # noqa: E402
from dialektike.domain import (  # noqa: E402
    AdapterCapabilities,
    ControlValue,
    ExecutionProfile,
    ModelCapability,
    ModelProfile,
    ModelSelection,
    Participant,
    RoundAssignment,
    RunConfig,
    StructuredContentBlock,
    TurnResult,
)
from dialektike.content import content_blocks_text  # noqa: E402
from dialektike.evidence import build_evidence_summary  # noqa: E402
from dialektike.orchestrator import DialecticOrchestrator  # noqa: E402
from dialektike.presenters.bridge import (  # noqa: E402
    BridgePermissionError,
    BridgePresenter,
    _desktop_runtime_id,
)
from dialektike.presenters.activity import RuntimeActivityBridge  # noqa: E402
from dialektike.providers import approved as approved_module  # noqa: E402
from dialektike.providers.approved import (  # noqa: E402
    approved_descriptor_payloads,
    approved_descriptor_records,
    approved_registry,
    approved_relay_runtime_ids,
)
from dialektike.providers.contract import (  # noqa: E402
    DescriptorError,
    descriptor_from_mapping,
    descriptor_to_mapping,
)
from dialektike.providers.registry import (  # noqa: E402
    ProviderRegistration,
    ProviderRegistry,
    ProviderRegistryError,
)
from dialektike.registry import ParticipantRegistry, RegistryError  # noqa: E402
from dialektike.runs import RunStore  # noqa: E402
from dialektike.sidecar import decode_run_config  # noqa: E402
from dialektike.topics import TopicStore  # noqa: E402


def synthetic_wire() -> dict:
    return {
        "schema_version": 1,
        "descriptor_version": 7,
        "runtime_id": "unexpected.runtime-7",
        "vendor_id": "verdant-labs",
        "agent_system_id": "agent-system-42",
        "relay_provider_id": "unexpected-relay",
        "display": {
            "name": "Unexpected Runtime",
            "short_name": "Unexpected",
            "mark": "U",
            "icon_token": "provider",
            "accent_token": "verdant",
        },
        "authentication": {
            "label": "Synthetic authenticated route",
            "authority": "adapter-authenticated-discovery",
            "not_observable_label": "Authentication not observable",
        },
        "version_evidence": {
            "label": "Synthetic runtime version",
            "authority": "adapter-runtime-probe",
            "not_observable_label": "Version not observable",
        },
        "default_selection": {
            "model": None,
            "effort": None,
            "service_tier": None,
            "execution_profile": "governed",
        },
        "control_schema": [
            {
                "control_id": "response-style",
                "label": "Response style",
                "group": "turn",
                "kind": "select",
                "description": "A provider-declared turn control.",
                "authority": "runtime-contract",
                "default": "lucid",
                "options": [
                    {
                        "value": "lucid",
                        "label": "Lucid",
                        "availability": {"available": True, "reason": None},
                    },
                    {
                        "value": "orbital",
                        "label": "Orbital",
                        "availability": {
                            "available": False,
                            "reason": "Not included in this subscription",
                        },
                    },
                ],
                "min_value": None,
                "max_value": None,
            },
            {
                "control_id": "network-access",
                "label": "Network access",
                "group": "execution",
                "kind": "boolean",
                "description": "Whether the governed profile requests network access.",
                "authority": "runtime-contract",
                "default": False,
                "options": [],
                "min_value": None,
                "max_value": None,
            },
        ],
        "supported_content_types": ["markdown", "code"],
        "execution_profiles": [
            {
                "profile_id": "governed",
                "label": "Governed",
                "description": "Use the governed permission relay.",
                "availability": {"available": True, "reason": None},
                "values": {"network-access": False},
            }
        ],
        "runtime_facilities": [
            {
                "facility_id": "memory",
                "label": "Memory",
                "description": "Runtime-managed memory.",
                "observability": "not-observable",
                "management": "runtime-native",
            }
        ],
        "permission_presentations": [
            {
                "request_kind": "native/approval",
                "title": "Native approval",
                "layout": "generic",
                "fields": [
                    {
                        "field_id": "operation",
                        "label": "Operation",
                        "pointer": "/operation",
                        "format": "text",
                    }
                ],
            }
        ],
        "connect": {
            "label": "Connect Unexpected Runtime",
            "help_text": "Authenticate the reviewed runtime, then refresh capabilities.",
            "action": "refresh-capabilities",
        },
    }


class SyntheticAdapter:
    adapter_id = "unexpected.runtime-7"
    relay_provider_id = "unexpected-relay"

    def __init__(self, presenter, activity_bridge=None, *, vendor_id="verdant-labs"):
        self.presenter = presenter
        self.activity_bridge = activity_bridge
        self.vendor_id = vendor_id

    async def discover_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id=self.adapter_id,
            vendor=self.vendor_id,
            agent_system="agent-system-42",
            models=(
                ModelCapability(
                    model_id="synthetic-model",
                    display_name="Synthetic Model",
                    is_default=True,
                ),
            ),
            runtime_version="synthetic-7",
            account_route="synthetic-subscription",
        )

    async def run_turn(self, request, cancellation):  # pragma: no cover - seam only
        raise AssertionError("provider turn must not run in contract tests")

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None


class UndeclaredContentAdapter(SyntheticAdapter):
    async def run_turn(self, request, cancellation) -> TurnResult:
        block = StructuredContentBlock.from_mapped(
            {
                "type": "diff",
                "title": "Provider patch",
                "diff": "+visible but undeclared\n",
            },
            declared_types=("diff",),
        )
        profile = request.participant.model_profile.resolved(
            ModelSelection(model_id="synthetic-model"),
            "synthetic runtime echo",
        )
        return TurnResult(
            text=content_blocks_text((asdict(block),)),
            blocks=(block,),
            model_profile=profile,
            account_route="synthetic-subscription",
            runtime_version="synthetic-7",
        )


class WrongRelaySyntheticAdapter(SyntheticAdapter):
    relay_provider_id = "other-relay"


class ConformanceSyntheticAdapter(SyntheticAdapter):
    """No-model adapter that crosses every shared provider boundary."""

    async def run_turn(self, request, cancellation) -> TurnResult:
        if self.activity_bridge is not None:
            self.activity_bridge.publish(
                request,
                f"{self.adapter_id} emitted a native conformance activity",
                activity="synthetic-conformance",
            )
            await asyncio.sleep(0)
        if request.stage.value == "proposal":
            relay = PermissionRelay(
                ChainedLog(Path(request.paths.decisions_path)),
                presenter=self.presenter,
                raw_dir=Path(request.paths.raw_dir),
            )
            native = NormalizedRequest(
                provider=self.relay_provider_id,
                case=request.run_id,
                phase=f"round-{request.round_number}-turn-{request.turn_number}",
                model="synthetic-model",
                role=request.role.value,
                kind="native/approval",
                payload={"operation": "Read the inert conformance fixture"},
                correlation_id="synthetic-e2e-permission",
            )
            decision, _ = await asyncio.to_thread(relay.relay, native)
            if decision != "allow":
                raise AssertionError("conformance presenter must allow the fixture")
        text = f"{request.stage.value} from {self.adapter_id}"
        block = StructuredContentBlock.markdown(text)
        requested = request.participant.model_profile.requested
        return TurnResult(
            text=text,
            blocks=(block,),
            model_profile=request.participant.model_profile.resolved(
                ModelSelection(
                    model_id="synthetic-model",
                    controls=requested.controls,
                ),
                "synthetic runtime echo",
            ),
            account_route="synthetic-subscription",
            runtime_version="synthetic-7",
            evidence=(("synthetic_conformance", "true"),),
        )


class ConformancePeerAdapter(ConformanceSyntheticAdapter):
    adapter_id = "alternate.runtime-8"
    relay_provider_id = "alternate-relay"

    def __init__(self, presenter, activity_bridge=None):
        super().__init__(
            presenter,
            activity_bridge,
            vendor_id="violet-labs",
        )

    async def discover_capabilities(self) -> AdapterCapabilities:
        catalog = await super().discover_capabilities()
        return AdapterCapabilities(
            adapter_id=self.adapter_id,
            vendor="violet-labs",
            agent_system="agent-system-43",
            models=catalog.models,
            runtime_version="synthetic-8",
            account_route="synthetic-peer-subscription",
        )


def synthetic_factory(presenter, activity_bridge=None):
    return SyntheticAdapter(presenter, activity_bridge)


def wrong_vendor_factory(presenter, activity_bridge=None):
    return SyntheticAdapter(presenter, activity_bridge, vendor_id="other-vendor")


def undeclared_content_factory(presenter, activity_bridge=None):
    return UndeclaredContentAdapter(presenter, activity_bridge)


def wrong_relay_factory(presenter, activity_bridge=None):
    return WrongRelaySyntheticAdapter(presenter, activity_bridge)


def conformance_factory(presenter, activity_bridge=None):
    return ConformanceSyntheticAdapter(presenter, activity_bridge)


def conformance_peer_factory(presenter, activity_bridge=None):
    return ConformancePeerAdapter(presenter, activity_bridge)


# The static registry requires declared frozen-module provenance even when this
# file is executed directly instead of imported by a test runner.
synthetic_factory.__module__ = "tests.provider_contract_invariants"
wrong_vendor_factory.__module__ = "tests.provider_contract_invariants"
undeclared_content_factory.__module__ = "tests.provider_contract_invariants"
wrong_relay_factory.__module__ = "tests.provider_contract_invariants"
conformance_factory.__module__ = "tests.provider_contract_invariants"
conformance_peer_factory.__module__ = "tests.provider_contract_invariants"


def registration(factory=synthetic_factory) -> ProviderRegistration:
    return ProviderRegistration(
        descriptor=descriptor_from_mapping(synthetic_wire()),
        factory=factory,
        descriptor_sha256="0" * 64,
        approval_reference="Synthetic conformance fixture only",
        frozen_modules=("tests.provider_contract_invariants",),
    )


def peer_registration() -> ProviderRegistration:
    wire = deepcopy(synthetic_wire())
    wire["runtime_id"] = "alternate.runtime-8"
    wire["vendor_id"] = "violet-labs"
    wire["agent_system_id"] = "agent-system-43"
    wire["relay_provider_id"] = "alternate-relay"
    wire["display"] = {
        **wire["display"],
        "name": "Alternate Runtime",
        "short_name": "Alternate",
        "mark": "A",
        "accent_token": "violet",
    }
    wire["connect"] = {
        "label": "Connect Alternate Runtime",
        "help_text": "Authenticate the alternate runtime, then refresh capabilities.",
        "action": "refresh-capabilities",
    }
    return ProviderRegistration(
        descriptor=descriptor_from_mapping(wire),
        factory=conformance_peer_factory,
        descriptor_sha256="1" * 64,
        approval_reference="Synthetic peer conformance fixture only",
        frozen_modules=("tests.provider_contract_invariants",),
    )


def participant(
    participant_id: str,
    *,
    runtime_id: str,
    vendor_id: str,
    agent_system_id: str,
) -> Participant:
    return Participant(
        participant_id=participant_id,
        vendor=vendor_id,
        agent_system=agent_system_id,
        adapter_id=runtime_id,
        auth_route=f"{vendor_id}-subscription",
        model_profile=ModelProfile(requested=ModelSelection()),
    )


class DescriptorTests(unittest.TestCase):
    def test_rich_sidecar_form_accepts_unanticipated_opaque_provider_ids(self):
        def wire_participant(
            participant_id: str,
            runtime_id: str,
            vendor_id: str,
        ) -> dict:
            return {
                "participant_id": participant_id,
                "vendor": vendor_id,
                "agent_system": f"{runtime_id}.agent",
                "adapter_id": runtime_id,
                "auth_route": f"{vendor_id}:subscription",
                "model_profile": {
                    "requested": {
                        "model_id": "synthetic-model",
                        "effort": "deliberate",
                        "service_tier": None,
                        "features": [],
                        "controls": {},
                    }
                },
                "execution_profile": {
                    "profile_id": "inherit-native",
                    "values": {},
                },
            }

        config = decode_run_config({
            "prompt": "Test opaque provider composition.",
            "participants": [
                wire_participant(
                    "executor-synthetic",
                    "unexpected.runtime-7",
                    "verdant-labs",
                ),
                wire_participant(
                    "auditor-synthetic",
                    "alternate.runtime-8",
                    "violet-labs",
                ),
            ],
            "assignments": [{
                "round_number": 1,
                "executor_id": "executor-synthetic",
                "auditor_ids": ["auditor-synthetic"],
            }],
        })

        self.assertEqual(config.participants[0].runtime_id, "unexpected.runtime-7")
        self.assertEqual(config.participants[0].vendor_id, "verdant-labs")
        self.assertEqual(config.participants[1].agent_system_id, "alternate.runtime-8.agent")

    def test_unanticipated_identifier_and_controls_round_trip(self):
        source = synthetic_wire()
        descriptor = descriptor_from_mapping(source)
        self.assertEqual(descriptor.runtime_id, "unexpected.runtime-7")
        self.assertEqual(descriptor.vendor_id, "verdant-labs")
        self.assertEqual(descriptor.control_schema[0].options[1].availability.reason,
                         "Not included in this subscription")
        self.assertEqual(descriptor.execution_profiles[0].values[0].value, False)
        self.assertEqual(descriptor_to_mapping(descriptor), source)
        descriptor.validate_model_selection(
            ModelSelection(
                controls=(ControlValue("response-style", "lucid"),)
            )
        )
        descriptor.validate_execution_profile(
            ExecutionProfile(
                profile_id="governed",
                values=(ControlValue("network-access", False),),
            )
        )
        with self.assertRaisesRegex(DescriptorError, "subscription"):
            descriptor.validate_model_selection(
                ModelSelection(
                    controls=(ControlValue("response-style", "orbital"),)
                )
            )

    def test_unknown_executable_and_html_like_metadata_are_rejected(self):
        entry_point = synthetic_wire()
        entry_point["adapter_entry_point"] = "external.module:factory"
        with self.assertRaises(DescriptorError):
            descriptor_from_mapping(entry_point)

        html = synthetic_wire()
        html["display"]["name"] = "<script>alert(1)</script>"
        with self.assertRaises(DescriptorError):
            descriptor_from_mapping(html)

        malformed = synthetic_wire()
        malformed["control_schema"][0]["options"][0]["availability"] = {
            "available": True,
            "reason": "contradictory",
        }
        with self.assertRaises(DescriptorError):
            descriptor_from_mapping(malformed)

    def test_approved_bundle_hashes_are_verified_and_inert(self):
        records = approved_descriptor_records()
        self.assertEqual(
            {record.descriptor.runtime_id for record in records},
            {"claude-code", "codex"},
        )
        for record in records:
            path = REPO / "dialektike" / "providers" / "descriptors" / (
                f"{record.descriptor.runtime_id}.json"
            )
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                record.descriptor_sha256,
            )
        manifest = json.loads(
            (REPO / "dialektike" / "providers" / "approved-providers.json")
            .read_text(encoding="utf-8")
        )
        for item in manifest["providers"]:
            self.assertNotIn("entry_point", item)
            self.assertNotIn("factory", item)
        self.assertEqual(
            approved_relay_runtime_ids(),
            {"claude": "claude-code", "codex": "codex"},
        )
        self.assertEqual(
            [item["runtime_id"] for item in approved_descriptor_payloads()],
            ["claude-code", "codex"],
        )
        approved = approved_registry()
        self.assertEqual(
            [item.descriptor.runtime_id for item in approved.registrations],
            ["claude-code", "codex"],
        )
        self.assertEqual(
            tuple(approved.build_adapters(lambda request, card: "deny")),
            ("claude-code", "codex"),
        )

    def test_approved_descriptor_path_rejects_file_and_directory_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            (root / "linked.json").symlink_to(target)
            real_directory = root / "real"
            real_directory.mkdir()
            (real_directory / "nested.json").write_text("{}", encoding="utf-8")
            (root / "linked-directory").symlink_to(real_directory)

            with patch.object(approved_module, "_ROOT", root):
                with self.assertRaisesRegex(
                    ProviderRegistryError, "must not traverse a symlink"
                ):
                    approved_module._descriptor_path("linked.json")
                with self.assertRaisesRegex(
                    ProviderRegistryError, "must not traverse a symlink"
                ):
                    approved_module._descriptor_path(
                        "linked-directory/nested.json"
                    )
                self.assertEqual(
                    approved_module._descriptor_path("target.json"), target
                )

    def test_provider_identities_are_opaque_without_shared_known_pairing(self):
        synthetic = participant(
            "synthetic",
            runtime_id="unexpected.runtime-7",
            vendor_id="verdant-labs",
            agent_system_id="agent-system-42",
        )
        self.assertEqual(synthetic.vendor_id, "verdant-labs")
        unanticipated_pairing = participant(
            "descriptor-owned-pair",
            runtime_id="codex",
            vendor_id="anthropic",
            agent_system_id="codex",
        )
        self.assertEqual(unanticipated_pairing.vendor_id, "anthropic")


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_binds_descriptor_to_factory_and_catalog(self):
        registry = ProviderRegistry((registration(),))
        adapters = registry.build_adapters(lambda request, card: "deny")
        self.assertEqual(tuple(adapters), ("unexpected.runtime-7",))
        adapter = adapters["unexpected.runtime-7"]
        self.assertEqual(adapter.descriptor.vendor_id, "verdant-labs")
        catalog = await adapter.discover_capabilities()
        self.assertEqual(catalog.vendor_id, "verdant-labs")

    async def test_catalog_identity_drift_fails_closed(self):
        registry = ProviderRegistry((registration(wrong_vendor_factory),))
        adapter = registry.build_adapters(lambda request, card: "deny")[
            "unexpected.runtime-7"
        ]
        with self.assertRaisesRegex(ProviderRegistryError, "returned vendor"):
            await adapter.discover_capabilities()

    def test_registration_binds_descriptor_relay_identity_to_adapter(self):
        registry = ProviderRegistry((registration(wrong_relay_factory),))
        with self.assertRaisesRegex(
            ProviderRegistryError,
            "relay identity 'other-relay'.*expected 'unexpected-relay'",
        ):
            registry.build_adapters(lambda request, card: "deny")

    async def test_run_turn_revalidates_descriptor_controls_before_delegate(self):
        adapter = ProviderRegistry((registration(),)).build_adapters(
            lambda request, card: "deny"
        )["unexpected.runtime-7"]
        invalid_participant = Participant(
            participant_id="synthetic",
            vendor="verdant-labs",
            agent_system="agent-system-42",
            adapter_id="unexpected.runtime-7",
            auth_route="synthetic-subscription",
            model_profile=ModelProfile(
                requested=ModelSelection(
                    controls=(ControlValue("response-style", "orbital"),)
                )
            ),
            execution_profile=ExecutionProfile(
                profile_id="governed",
                values=(ControlValue("network-access", False),),
            ),
        )
        with self.assertRaisesRegex(ProviderRegistryError, "subscription"):
            await adapter.run_turn(
                SimpleNamespace(participant=invalid_participant),
                None,
            )

    async def test_descriptor_downgrades_undeclared_content_without_id_branches(self):
        adapter = ProviderRegistry(
            (registration(undeclared_content_factory),)
        ).build_adapters(lambda request, card: "deny")["unexpected.runtime-7"]
        turn_participant = participant(
            "synthetic",
            runtime_id="unexpected.runtime-7",
            vendor_id="verdant-labs",
            agent_system_id="agent-system-42",
        )
        turn_participant = Participant(
            participant_id=turn_participant.participant_id,
            vendor=turn_participant.vendor,
            agent_system=turn_participant.agent_system,
            adapter_id=turn_participant.adapter_id,
            auth_route=turn_participant.auth_route,
            model_profile=turn_participant.model_profile,
            execution_profile=ExecutionProfile(
                profile_id="governed",
                values=(ControlValue("network-access", False),),
            ),
        )

        result = await adapter.run_turn(
            SimpleNamespace(participant=turn_participant),
            None,
        )

        self.assertEqual([block.type for block in result.blocks], ["unknown"])
        unknown = asdict(result.blocks[0])
        self.assertEqual(unknown["provider_type"], "diff")
        self.assertEqual(unknown["text"], "+visible but undeclared\n")
        self.assertIsNone(unknown["diff"])
        self.assertEqual(
            result.text,
            content_blocks_text(asdict(block) for block in result.blocks),
        )

    async def test_distinct_seats_compare_opaque_vendor_id(self):
        first = participant(
            "first",
            runtime_id="unexpected.runtime-7",
            vendor_id="verdant-labs",
            agent_system_id="agent-system-42",
        )
        second = participant(
            "second",
            runtime_id="second.runtime",
            vendor_id="cobalt-labs",
            agent_system_id="second-agent",
        )
        config = RunConfig(
            prompt="Review this.",
            participants=(first, second),
            assignments=(RoundAssignment(1, "first", "second"),),
        )

        class Adapter:
            def __init__(self, adapter_id):
                self.adapter_id = adapter_id

        ParticipantRegistry((first, second)).validate_run(
            config,
            {
                first.runtime_id: Adapter(first.runtime_id),
                second.runtime_id: Adapter(second.runtime_id),
            },
        )

        duplicate_vendor = participant(
            "second",
            runtime_id="second.runtime",
            vendor_id="verdant-labs",
            agent_system_id="second-agent",
        )
        duplicate_config = RunConfig(
            prompt="Review this.",
            participants=(first, duplicate_vendor),
            assignments=(RoundAssignment(1, "first", "second"),),
        )
        with self.assertRaisesRegex(RegistryError, "distinct vendor"):
            ParticipantRegistry((first, duplicate_vendor)).validate_run(
                duplicate_config,
                {
                    first.runtime_id: Adapter(first.runtime_id),
                    duplicate_vendor.runtime_id: Adapter(
                        duplicate_vendor.runtime_id
                    ),
                },
            )


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthetic_relay_mapping_flows_without_shared_id_branch(self):
        events: list[tuple[str, dict]] = []
        delivered = asyncio.Event()
        presenter = BridgePresenter(
            {"unexpected-relay": "unexpected.runtime-7"}
        )

        async def emit(event: str, payload: dict) -> None:
            events.append((event, payload))
            delivered.set()

        presenter.bind(asyncio.get_running_loop(), emit)
        request = NormalizedRequest(
            provider="unexpected-relay",
            case="synthetic-case",
            phase="turn-1",
            model="synthetic-model",
            role="auditor",
            kind="native/approval",
            payload={"operation": "Inspect an inert fixture"},
            correlation_id="synthetic-correlation",
        )
        expected_fingerprint = sha256_text(
            canonical(
                {
                    "provider": request.provider,
                    "case": request.case,
                    "phase": request.phase,
                    "model": request.model,
                    "role": request.role,
                    "kind": request.kind,
                    "payload": request.payload,
                }
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            relay = PermissionRelay(
                ChainedLog(Path(temporary) / "decisions.jsonl"),
                presenter=presenter,
            )
            task = asyncio.create_task(asyncio.to_thread(relay.relay, request))
            await asyncio.wait_for(delivered.wait(), timeout=2)
            event, payload = events[0]
            self.assertEqual(event, "permission.request")
            self.assertEqual(payload["runtime_id"], "unexpected.runtime-7")
            self.assertEqual(request.provider, "unexpected-relay")
            self.assertEqual(request.fingerprint, expected_fingerprint)
            self.assertTrue(
                presenter.respond(payload["permission_id"], "allow_once")
            )
            decision, _ = await asyncio.wait_for(task, timeout=2)
            self.assertEqual(decision, "allow")
            self.assertEqual(request.provider, "unexpected-relay")
            self.assertEqual(request.fingerprint, expected_fingerprint)

    async def test_unknown_relay_provider_fails_closed(self):
        self.assertEqual(
            _desktop_runtime_id("claude"),
            "claude-code",
        )
        with self.assertRaises(BridgePermissionError):
            _desktop_runtime_id(
                "unapproved-relay",
                {"unexpected-relay": "unexpected.runtime-7"},
            )


class SyntheticEndToEndConformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_eight_provider_contract_stages_cross_shared_code(self):
        registry = ProviderRegistry(
            (
                registration(conformance_factory),
                peer_registration(),
            )
        )
        presenter = BridgePresenter(registry.relay_runtime_ids)
        activity = RuntimeActivityBridge()
        trusted_events: list[tuple[str, dict]] = []

        async def emit(event: str, payload: dict) -> None:
            trusted_events.append((event, payload))
            if event == "permission.request":
                self.assertTrue(
                    presenter.respond(payload["permission_id"], "allow_once")
                )

        loop = asyncio.get_running_loop()
        presenter.bind(loop, emit)
        activity.bind(loop, emit)
        adapters = registry.build_adapters(presenter, activity)
        catalogs = {
            runtime_id: await adapter.discover_capabilities()
            for runtime_id, adapter in adapters.items()
        }

        def configured_participant(
            participant_id: str,
            runtime_id: str,
        ) -> Participant:
            descriptor = registry.descriptor(runtime_id)
            catalog = catalogs[runtime_id]
            return Participant(
                participant_id=participant_id,
                vendor=descriptor.vendor_id,
                agent_system=descriptor.agent_system_id,
                adapter_id=runtime_id,
                auth_route=catalog.account_route or "missing",
                model_profile=ModelProfile(
                    requested=ModelSelection(
                        model_id="synthetic-model",
                        controls=(ControlValue("response-style", "lucid"),),
                    )
                ),
                execution_profile=ExecutionProfile(
                    profile_id="governed",
                    values=(ControlValue("network-access", False),),
                ),
            )

        executor = configured_participant("executor", "unexpected.runtime-7")
        auditor = configured_participant("auditor", "alternate.runtime-8")
        config = RunConfig.fixed_roles(
            prompt="Exercise every synthetic provider boundary.",
            participants=(executor, auditor),
            executor_id=executor.participant_id,
            auditor_ids=(auditor.participant_id,),
            rounds=1,
        )
        participant_config = {
            "rounds": 1,
            "participants": [
                {
                    "participant_id": item.participant_id,
                    "runtime_id": item.runtime_id,
                    "vendor_id": item.vendor_id,
                    "role": "executor" if item is executor else "auditor",
                }
                for item in (executor, auditor)
            ],
        }
        orchestration_events: list[dict] = []

        async def capture_orchestration(event: dict) -> None:
            orchestration_events.append(event)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            topic_store = TopicStore(root / "topic-store")
            topic_store.create(
                topic_id="synthetic-topic",
                first_prompt=config.prompt,
                participant_config=participant_config,
            )
            outcome = await DialecticOrchestrator(
                store=RunStore(root / "run-store"),
                adapters=adapters,
                event_sink=capture_orchestration,
            ).run(config, run_id="synthetic-e2e")
            # RuntimeActivityBridge deliberately schedules without blocking
            # provider execution. Drain those already-queued callbacks before
            # asserting the conformance surface.
            for _ in range(10):
                if sum(
                    event == "participant.activity"
                    for event, _payload in trusted_events
                ) == 3:
                    break
                await asyncio.sleep(0)
            self.assertEqual(outcome.status.value, "completed")
            self.assertEqual(
                [turn.stage.value for turn in outcome.turns],
                ["proposal", "audit", "synthesis"],
            )

            projected_messages = [
                {
                    "id": f"{outcome.run_id}:{turn.turn_number}",
                    "participant_id": turn.participant_id,
                    "role": turn.role.value,
                    "stage": turn.stage.value,
                    "runtime_id": turn.adapter_id,
                    "text": turn.text,
                    "blocks": [asdict(block) for block in turn.blocks],
                }
                for turn in outcome.turns
            ]
            topic_store.append_cycle(
                "synthetic-topic",
                live_prompt=config.prompt,
                run_id=outcome.run_id,
                run_status=outcome.status.value,
                status="completed",
                messages=projected_messages,
                participant_config=participant_config,
            )
            persisted = topic_store.read("synthetic-topic")
            summary = build_evidence_summary(
                config=config,
                outcome=outcome,
                catalogs=catalogs,
                environment_gate={
                    "policy": "allowlist",
                    "kept": ["HOME"],
                    "dropped_count": 0,
                },
            )

        # Discovery/catalog + controls.
        self.assertEqual(
            catalogs["unexpected.runtime-7"].models[0].model_id,
            "synthetic-model",
        )
        self.assertTrue(
            all(
                turn.model_profile.effective is not None
                and turn.model_profile.effective.controls
                == (ControlValue("response-style", "lucid"),)
                for turn in outcome.turns
            )
        )
        # Topic persistence.
        self.assertEqual(persisted["cycles"][0]["run_id"], "synthetic-e2e")
        self.assertEqual(len(persisted["cycles"][0]["messages"]), 3)
        # Run + genuine native activity.
        self.assertTrue(
            any(event["kind"] == "run_completed" for event in orchestration_events)
        )
        activity_events = [
            payload
            for event, payload in trusted_events
            if event == "participant.activity"
        ]
        self.assertEqual(len(activity_events), 3)
        self.assertTrue(all(item["trusted"] for item in activity_events))
        # Permission request + Live decision through the generic mapping.
        permission_events = [
            payload
            for event, payload in trusted_events
            if event == "permission.request"
        ]
        self.assertEqual(len(permission_events), 1)
        self.assertEqual(
            permission_events[0]["runtime_id"],
            "unexpected.runtime-7",
        )
        # Evidence + provider-owned labels.
        self.assertTrue(summary["decision_chain"]["verified"])
        self.assertEqual(
            summary["governance"]["permission_decisions"],
            {"allow": 1, "deny": 0, "total": 1},
        )
        self.assertTrue(summary["event_log_readable"])
        self.assertEqual(
            {item["runtime_id"] for item in summary["runtime_gates"]},
            {"unexpected.runtime-7", "alternate.runtime-8"},
        )
        self.assertEqual(
            registry.descriptor("unexpected.runtime-7").display.name,
            "Unexpected Runtime",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
