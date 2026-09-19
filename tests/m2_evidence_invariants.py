"""No-model invariants for the M2 desktop evidence projection."""

from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.broker import ChainedLog  # noqa: E402
from dialektike.adapters.claude import (  # noqa: E402
    _redacted_rate_capture,
)
from dialektike.domain import (  # noqa: E402
    AdapterCapabilities,
    AgentSystem,
    ModelCapability,
    ModelProfile,
    ModelSelection,
    Participant,
    Role,
    RunConfig,
    RunOutcome,
    RunStatus,
    TurnRecord,
    TurnStatus,
    Vendor,
)
from dialektike.evidence import (  # noqa: E402
    MAX_SAVED_SUMMARY_BYTES,
    EvidenceSummaryIntegrityError,
    build_evidence_summary,
    load_saved_evidence_summary,
    save_evidence_summary,
)
from dialektike.runs import RunStore  # noqa: E402


def _participant(
    runtime_id: str,
    vendor: Vendor,
    system: AgentSystem,
    model: str,
) -> Participant:
    return Participant(
        participant_id=f"{runtime_id}-participant",
        vendor=vendor,
        agent_system=system,
        adapter_id=runtime_id,
        auth_route=(
            "chatgpt:plus"
            if runtime_id == "codex"
            else "claude.ai:firstParty:pro"
        ),
        model_profile=ModelProfile(
            requested=ModelSelection(model_id=model, effort="high")
        ),
    )


def _empty_verified_summary(run_id: str) -> dict:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "run_status": "completed",
        "environment_gate": {
            "verified": False,
            "policy": None,
            "kept": [],
            "dropped_count": None,
        },
        "runtime_gates": [],
        "rate_limits": {
            "observed_event_count": 0,
            "by_runtime": {},
            "warning_count": 0,
            "warnings": [],
            "capture_parse_failures": 0,
        },
        "governance": {
            "derived_from_verified_chain": True,
            "permission_decisions": {"allow": 0, "deny": 0, "total": 0},
            "audit_counts": {},
        },
        "raw_capture": {
            "file_count": 0,
            "total_bytes": 0,
            "turns_with_capture": 0,
            "by_category": {},
            "contents_exposed": False,
        },
        "decision_chain": {
            "verified": True,
            "record_count": 0,
            "head_sha256": None,
            "error": None,
        },
        "event_log_readable": True,
    }


class EvidenceSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.codex = _participant(
            "codex", Vendor.OPENAI, AgentSystem.CODEX, "gpt-5.6-sol"
        )
        self.claude = _participant(
            "claude-code",
            Vendor.ANTHROPIC,
            AgentSystem.CLAUDE_CODE,
            "opus",
        )
        self.config = RunConfig.fixed_roles(
            prompt="Review this.",
            participants=(self.codex, self.claude),
            executor_id=self.codex.participant_id,
            auditor_id=self.claude.participant_id,
            rounds=1,
        )
        self.catalogs = {
            "codex": AdapterCapabilities(
                adapter_id="codex",
                vendor=Vendor.OPENAI,
                agent_system=AgentSystem.CODEX,
                models=(
                    ModelCapability(
                        "gpt-5.6-sol",
                        "GPT-5.6 Sol",
                        efforts=("high",),
                    ),
                ),
                runtime_version="0.145.0",
                account_route="chatgpt:plus",
            ),
            "claude-code": AdapterCapabilities(
                adapter_id="claude-code",
                vendor=Vendor.ANTHROPIC,
                agent_system=AgentSystem.CLAUDE_CODE,
                models=(
                    ModelCapability("opus", "Claude Opus", efforts=("high",)),
                ),
                runtime_version="claude-code test",
                account_route="claude.ai:firstParty:pro",
            ),
        }

    def _turn(
        self, number: int, participant: Participant, role: Role
    ) -> TurnRecord:
        profile = participant.model_profile.resolved(
            ModelSelection(
                model_id=participant.model_profile.requested.model_id,
                effort="high",
            ),
            "runtime echo / validated request",
        )
        return TurnRecord(
            round_number=1,
            turn_number=number,
            role=role,
            participant_id=participant.participant_id,
            adapter_id=participant.adapter_id,
            status=TurnStatus.COMPLETED,
            input_text="input",
            text="output",
            model_profile=profile,
            account_route=participant.auth_route,
            runtime_version=self.catalogs[
                participant.adapter_id
            ].runtime_version,
        )

    def test_summary_verifies_chain_and_exposes_inventory_not_contents(self):
        with tempfile.TemporaryDirectory() as td:
            handle = RunStore(Path(td) / "runs").create("evidence-run")
            codex_paths = handle.turn_paths(1, self.codex.participant_id)
            claude_paths = handle.turn_paths(2, self.claude.participant_id)
            Path(codex_paths.raw_dir, "codex_events.json").write_text(
                json.dumps(
                    [
                        {
                            "id": 3,
                            "result": {
                                "rateLimits": {
                                    "planType": "plus",
                                    "credits": {
                                        "hasCredits": False,
                                        "unlimited": False,
                                        "balance": "0",
                                    },
                                }
                            },
                        },
                        {"method": "account/rateLimits/updated"},
                        {"method": "account/rateLimits/updated"},
                    ]
                )
            )
            Path(
                claude_paths.raw_dir, "claude_events.redacted.jsonl"
            ).write_text(
                json.dumps({"type": "rate_limit", "status": "allowed"}) + "\n"
            )
            Path(claude_paths.raw_dir, "relay-secret.json").write_text(
                '{"secret":"owner-only payload"}'
            )
            log = ChainedLog(handle.decisions_path)
            log.append(
                {
                    "kind": "permission_decision",
                    "decision": "allow",
                    "payload_sha256": "a" * 64,
                }
            )
            log.append({"kind": "native_auto_permitted"})
            log.append({"kind": "tool_failed"})
            handle.append_event(
                "turn_completed",
                {
                    "turn": self._turn(1, self.codex, Role.EXECUTOR),
                    "evidence": (("rate_limit_snapshot_count", "2"),),
                },
            )
            handle.append_event(
                "turn_completed",
                {
                    "turn": self._turn(2, self.claude, Role.AUDITOR),
                    "evidence": (("rate_limit_event_count", "1"),),
                },
            )

            turns = (
                self._turn(1, self.codex, Role.EXECUTOR),
                self._turn(2, self.claude, Role.AUDITOR),
            )
            outcome = RunOutcome(
                run_id=handle.run_id,
                status=RunStatus.COMPLETED,
                turns=turns,
                run_path=str(handle.path),
            )
            summary = build_evidence_summary(
                config=self.config,
                outcome=outcome,
                catalogs=self.catalogs,
                environment_gate={
                    "policy": "allowlist",
                    "kept": ["HOME", "PATH"],
                    "dropped_count": 12,
                },
            )

            self.assertTrue(summary["environment_gate"]["verified"])
            self.assertEqual(
                summary["environment_gate"]["kept"], ["HOME", "PATH"]
            )
            self.assertTrue(summary["decision_chain"]["verified"])
            self.assertEqual(summary["decision_chain"]["record_count"], 3)
            self.assertEqual(
                summary["governance"]["permission_decisions"],
                {"allow": 1, "deny": 0, "total": 1},
            )
            self.assertEqual(
                summary["governance"]["audit_counts"]["tool_failed"], 1
            )
            self.assertEqual(
                summary["rate_limits"]["observed_event_count"], 4
            )
            self.assertEqual(summary["raw_capture"]["file_count"], 3)
            self.assertFalse(summary["raw_capture"]["contents_exposed"])
            serialized = json.dumps(summary)
            self.assertNotIn("owner-only payload", serialized)
            self.assertNotIn(str(handle.path), serialized)
            self.assertNotIn("relay-secret.json", serialized)

            saved = save_evidence_summary(handle.path, summary)
            self.assertEqual(
                stat.S_IMODE(saved.stat().st_mode), 0o600
            )

    def test_broken_chain_withholds_governance_counts(self):
        with tempfile.TemporaryDirectory() as td:
            handle = RunStore(Path(td) / "runs").create("broken-run")
            handle.decisions_path.write_text(
                '{"kind":"permission_decision","decision":"allow",'
                '"hash":"broken","prev_hash":"dialektike-genesis"}\n'
            )
            outcome = RunOutcome(
                run_id=handle.run_id,
                status=RunStatus.CANCELLED,
                turns=(),
                run_path=str(handle.path),
                stop_reason="test",
            )
            summary = build_evidence_summary(
                config=self.config,
                outcome=outcome,
                catalogs=self.catalogs,
            )

            self.assertFalse(summary["decision_chain"]["verified"])
            self.assertIsNone(
                summary["governance"]["permission_decisions"]
            )
            self.assertIsNone(summary["governance"]["audit_counts"])

    def test_missing_decision_log_is_not_verified_as_an_empty_chain(self):
        with tempfile.TemporaryDirectory() as td:
            handle = RunStore(Path(td) / "runs").create("missing-chain-run")
            handle.decisions_path.unlink()
            outcome = RunOutcome(
                run_id=handle.run_id,
                status=RunStatus.FAILED,
                turns=(),
                run_path=str(handle.path),
                failure="test",
            )
            summary = build_evidence_summary(
                config=self.config,
                outcome=outcome,
                catalogs=self.catalogs,
            )

            self.assertFalse(summary["decision_chain"]["verified"])
            self.assertIsNone(summary["decision_chain"]["record_count"])
            self.assertFalse(
                summary["governance"]["derived_from_verified_chain"]
            )
            self.assertIsNone(
                summary["governance"]["permission_decisions"]
            )

    def test_saved_summary_reloads_only_from_its_owner_only_linked_run(self):
        with tempfile.TemporaryDirectory() as td:
            store = RunStore(Path(td) / "runs")
            handle = store.create("saved-run")
            summary = _empty_verified_summary(handle.run_id)
            save_evidence_summary(handle.path, summary)

            loaded = load_saved_evidence_summary(store.root, handle.run_id)
            self.assertEqual(loaded, summary)
            encoded = json.dumps(loaded)
            self.assertNotIn(str(handle.path), encoded)
            self.assertNotIn("evidence_summary.json", encoded)

            (handle.path / "evidence_summary.json").chmod(0o644)
            with self.assertRaises(EvidenceSummaryIntegrityError):
                load_saved_evidence_summary(store.root, handle.run_id)
            (handle.path / "evidence_summary.json").chmod(0o600)
            handle.decisions_path.chmod(0o644)
            with self.assertRaises(EvidenceSummaryIntegrityError):
                load_saved_evidence_summary(store.root, handle.run_id)
            handle.decisions_path.chmod(0o600)
            handle.path.chmod(0o755)
            with self.assertRaises(EvidenceSummaryIntegrityError):
                load_saved_evidence_summary(store.root, handle.run_id)

    def test_saved_summary_rejects_unknown_raw_fields_wrong_binding_and_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            store = RunStore(Path(td) / "runs")
            handle = store.create("guarded-run")
            summary = _empty_verified_summary(handle.run_id)
            summary["raw_capture"]["path"] = "/private/owner/raw"
            save_evidence_summary(handle.path, summary)
            with self.assertRaises(EvidenceSummaryIntegrityError):
                load_saved_evidence_summary(store.root, handle.run_id)

            summary = _empty_verified_summary("different-run")
            save_evidence_summary(handle.path, summary)
            with self.assertRaisesRegex(
                EvidenceSummaryIntegrityError, "run binding"
            ):
                load_saved_evidence_summary(store.root, handle.run_id)

            target = handle.path / "owner-only-target.json"
            target.write_text("{}", encoding="utf-8")
            target.chmod(0o600)
            summary_path = handle.path / "evidence_summary.json"
            summary_path.unlink()
            summary_path.symlink_to(target)
            with self.assertRaises(EvidenceSummaryIntegrityError):
                load_saved_evidence_summary(store.root, handle.run_id)

            real = store.create("real-run")
            save_evidence_summary(
                real.path, _empty_verified_summary(real.run_id)
            )
            linked_path = store.root / "linked-run"
            linked_path.symlink_to(real.path, target_is_directory=True)
            with self.assertRaises(EvidenceSummaryIntegrityError):
                load_saved_evidence_summary(store.root, "linked-run")

    def test_saved_summary_revalidates_chain_and_enforces_read_bound(self):
        with tempfile.TemporaryDirectory() as td:
            store = RunStore(Path(td) / "runs")
            handle = store.create("revalidated-run")
            ChainedLog(handle.decisions_path).append(
                {
                    "kind": "permission_decision",
                    "decision": "allow",
                    "payload_sha256": "a" * 64,
                }
            )
            tampered = _empty_verified_summary(handle.run_id)
            tampered["decision_chain"] = {
                "verified": True,
                "record_count": 1,
                "head_sha256": "b" * 64,
                "error": None,
            }
            tampered["governance"]["permission_decisions"] = {
                "allow": 1,
                "deny": 0,
                "total": 1,
            }
            save_evidence_summary(handle.path, tampered)
            with self.assertRaisesRegex(
                EvidenceSummaryIntegrityError, "does not match"
            ):
                load_saved_evidence_summary(store.root, handle.run_id)

            summary_path = handle.path / "evidence_summary.json"
            summary_path.write_bytes(b"{" + b" " * MAX_SAVED_SUMMARY_BYTES + b"}")
            summary_path.chmod(0o600)
            with self.assertRaisesRegex(EvidenceSummaryIntegrityError, "size"):
                load_saved_evidence_summary(store.root, handle.run_id)

    def test_claude_rate_capture_hashes_opaque_native_fields(self):
        native = SimpleNamespace(
            status="allowed",
            rate_limit_type=None,
            utilization=0.25,
            resets_at=123,
            overage_status="disabled",
            raw={"authorization": "SECRET-CREDENTIAL"},
        )
        capture = _redacted_rate_capture(native)
        serialized = json.dumps(capture)

        self.assertNotIn("SECRET-CREDENTIAL", serialized)
        self.assertNotIn("authorization", serialized)
        self.assertRegex(capture["raw_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
