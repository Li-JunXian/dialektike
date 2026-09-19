"""No-model invariants for the owner-only Dialektikḗ topic store."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dialektike.topics import (  # noqa: E402
    TopicDeletedError,
    TopicIntegrityError,
    TopicStore,
    derive_topic_title,
)


def _participants(executor: str = "codex") -> dict:
    auditor = "claude-code" if executor == "codex" else "codex"
    return {
        "executor": {"runtime_id": executor, "model": "default"},
        "auditors": [{"runtime_id": auditor, "model": "default"}],
    }


def _messages(label: str = "one") -> list[dict]:
    return [
        {
            "role": "executor",
            "stage": "proposal",
            "text": f"proposal {label}",
        },
        {
            "role": "auditor",
            "stage": "audit",
            "text": f"audit {label}",
        },
        {
            "role": "executor",
            "stage": "synthesis",
            "text": f"synthesis {label}",
            "format": {"markdown": True},
        },
    ]


class TopicStoreInvariants(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "dialektike-state"
        self.store = TopicStore(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create(self, topic_id: str, *, title: str | None = None) -> dict:
        return self.store.create(
            topic_id=topic_id,
            title=title,
            participant_config=_participants(),
        )

    def _append(
        self,
        topic_id: str,
        label: str = "one",
        *,
        status: str = "completed",
        run_status: str = "completed",
    ) -> dict:
        return self.store.append_cycle(
            topic_id,
            live_prompt=f"Live prompt {label}",
            run_id=f"run-{label.replace(' ', '-')}",
            run_status=run_status,
            status=status,
            messages=_messages(label),
        )

    def test_owner_only_permissions_cover_all_persistent_paths(self) -> None:
        self._create("permissions")
        self._append("permissions")

        topic_dir = self.root / "topics" / "permissions"
        for directory in (self.root, self.root / "topics", topic_dir):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for path in (topic_dir / "events.jsonl", topic_dir / "topic.json"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(list(topic_dir.glob("*.tmp")), [])

    def test_safe_identifiers_reject_traversal_and_bad_run_ids(self) -> None:
        for topic_id in ("../escape", ".", "a/b", "", "topic space"):
            with self.subTest(topic_id=topic_id):
                with self.assertRaises(ValueError):
                    self.store.create(
                        topic_id=topic_id,
                        participant_config=_participants(),
                    )
        self._create("safe")
        with self.assertRaises(ValueError):
            self.store.append_cycle(
                "safe",
                live_prompt="prompt",
                run_id="../run",
                run_status="completed",
                status="completed",
                messages=[],
            )
        self.assertFalse((self.root.parent / "escape").exists())

    def test_append_order_and_reopen_recover_stale_snapshot(self) -> None:
        self._create("recovery")
        self.store.rename("recovery", "Recovered title")
        self.store.pin("recovery")
        events = self.store.events("recovery")
        self.assertEqual([item["sequence"] for item in events], [1, 2, 3])
        self.assertEqual(
            [item["kind"] for item in events],
            ["topic_created", "title_renamed", "pin_changed"],
        )

        snapshot_path = self.root / "topics" / "recovery" / "topic.json"
        snapshot_path.write_text('{"title":"stale"}\n', encoding="utf-8")
        reopened = TopicStore(self.root)
        recovered = reopened.read("recovery")
        self.assertEqual(recovered["title"], "Recovered title")
        self.assertTrue(recovered["pinned"])
        self.assertEqual(
            json.loads(snapshot_path.read_text(encoding="utf-8")), recovered
        )

    def test_crud_filters_search_and_deterministic_title(self) -> None:
        auto = self._create("auto")
        self.assertEqual(auto["title"], "New topic")
        auto = self._append("auto", "about password reset security")
        self.assertEqual(auto["title"], "Live prompt about password reset security")
        self.assertEqual(auto["title_source"], "derived")
        self.assertEqual(
            derive_topic_title("  several   spaces become one  "),
            "several spaces become one",
        )
        self.assertLessEqual(derive_topic_title("word " * 40).__len__(), 72)

        self._create("manual", title="Incident response")
        self.store.pin("manual")
        self.store.archive("auto")
        active = self.store.list_topics()
        archived = self.store.list_topics(archived=True)
        self.assertEqual([item["topic_id"] for item in active], ["manual"])
        self.assertEqual([item["topic_id"] for item in archived], ["auto"])
        self.assertEqual(
            [item["topic_id"] for item in self.store.search("PASSWORD")],
            ["auto"],
        )
        self.assertEqual(
            [item["topic_id"] for item in self.store.search("synthesis one")],
            [],
        )
        self.store.unarchive("auto")
        self.store.unpin("manual")
        self.store.rename("auto", "Manual title")
        self._append("auto", "later prompt")
        self.assertEqual(self.store.read("auto")["title"], "Manual title")

    def test_tombstone_hides_topic_but_retains_history_and_run_evidence(self) -> None:
        self._create("delete-me")
        before = self._append("delete-me")
        runs_root = self.root.parent / "runs"
        evidence_dir = runs_root / "run-one"
        evidence_dir.mkdir(parents=True)
        evidence_file = evidence_dir / "decisions.jsonl"
        evidence_file.write_text("immutable evidence\n", encoding="utf-8")

        deleted = self.store.delete("delete-me")
        self.assertTrue(deleted["deleted"])
        self.assertEqual(deleted["cycles"], before["cycles"])
        self.assertEqual(deleted["linked_run_ids"], ["run-one"])
        self.assertEqual(self.store.list_topics(), [])
        with self.assertRaises(TopicDeletedError):
            self.store.read("delete-me")
        retained = self.store.read("delete-me", include_deleted=True)
        self.assertEqual(retained["linked_run_ids"], ["run-one"])
        self.assertEqual(
            [item["topic_id"] for item in self.store.list_topics(
                archived=None, include_deleted=True
            )],
            ["delete-me"],
        )
        self.assertEqual(evidence_file.read_text(), "immutable evidence\n")
        with self.assertRaises(TopicDeletedError):
            self.store.rename("delete-me", "cannot mutate")

    def test_topics_are_independent_and_return_values_are_detached(self) -> None:
        first = self._create("first", title="First")
        self._create("second", title="Second")
        first["participant_config"]["executor"]["runtime_id"] = "tampered"
        self._append("first")
        self.store.archive("second")

        persisted_first = self.store.read("first")
        persisted_second = self.store.read("second")
        self.assertEqual(
            persisted_first["participant_config"]["executor"]["runtime_id"],
            "codex",
        )
        self.assertEqual(len(persisted_first["cycles"]), 1)
        self.assertEqual(len(persisted_second["cycles"]), 0)
        self.assertFalse(persisted_first["archived"])
        self.assertTrue(persisted_second["archived"])

    def test_participant_changes_version_only_future_cycles(self) -> None:
        self._create("versions")
        first = self._append("versions", "first")
        old_config = first["cycles"][0]["participant_config"]
        changed = _participants(executor="claude-code")
        updated = self.store.update_participants("versions", changed)
        self.assertEqual(updated["participant_revision"], 2)
        second = self._append("versions", "second")

        self.assertEqual(second["cycles"][0]["participant_revision"], 1)
        self.assertEqual(second["cycles"][0]["participant_config"], old_config)
        self.assertEqual(second["cycles"][1]["participant_revision"], 2)
        self.assertEqual(second["cycles"][1]["participant_config"], changed)
        with self.assertRaises(ValueError):
            self.store.append_cycle(
                "versions",
                live_prompt="mismatched participants",
                run_id="run-mismatch",
                run_status="completed",
                status="completed",
                messages=[],
                participant_config=_participants(),
            )

    def test_canonical_context_selects_live_and_synthesis_only(self) -> None:
        self._create("context")
        self._append("context", "first")
        partial_messages = [
            {"role": "executor", "stage": "proposal", "text": "proposal"},
            {"role": "auditor", "stage": "audit", "text": "audit"},
            {
                "role": "executor",
                "stage": "synthesis",
                "content": "synthesis second",
                "partial": True,
            },
        ]
        self.store.append_cycle(
            "context",
            live_prompt="Live prompt second",
            run_id="run-second",
            run_status="cancelled",
            status="partial",
            messages=partial_messages,
        )

        context = self.store.canonical_context("context")
        self.assertEqual(
            [(item["role"], item["stage"]) for item in context],
            [
                ("live", "prompt"),
                ("executor", "synthesis"),
                ("live", "prompt"),
            ],
        )
        self.assertEqual([item["cycle_number"] for item in context], [1, 1, 2])
        serialized = json.dumps(context)
        self.assertNotIn("proposal first", serialized)
        self.assertNotIn("audit first", serialized)
        self.assertIn("synthesis first", serialized)
        self.assertNotIn("synthesis second", serialized)
        self.assertNotIn("format", serialized)

    def test_unterminated_tail_is_durably_removed_before_future_appends(self) -> None:
        self._create("torn-tail", title="Torn tail")
        events_path = self.root / "topics" / "torn-tail" / "events.jsonl"
        committed = events_path.read_bytes()
        with events_path.open("ab") as stream:
            stream.write(b'{"kind":"topic_updated"')
            stream.flush()
            os.fsync(stream.fileno())

        reopened = TopicStore(self.root)
        self.assertEqual(reopened.read("torn-tail")["title"], "Torn tail")
        self.assertEqual(events_path.read_bytes(), committed)
        self.assertTrue(reopened.pin("torn-tail")["pinned"])
        self.assertTrue(reopened.read("torn-tail")["pinned"])

        committed_after_pin = events_path.read_bytes()
        with events_path.open("ab") as stream:
            stream.write(b'{"syntactically":"valid but not committed"}')
            stream.flush()
            os.fsync(stream.fileno())
        self.assertTrue(TopicStore(self.root).read("torn-tail")["pinned"])
        self.assertEqual(events_path.read_bytes(), committed_after_pin)

        with events_path.open("ab") as stream:
            stream.write(b"{}\n")
            stream.flush()
            os.fsync(stream.fileno())
        with self.assertRaises(TopicIntegrityError):
            TopicStore(self.root).read("torn-tail")

    def test_snapshot_failure_keeps_old_snapshot_and_event_recovers(self) -> None:
        self._create("atomic")
        snapshot_path = self.root / "topics" / "atomic" / "topic.json"
        old_snapshot = snapshot_path.read_bytes()
        with mock.patch("dialektike.topics.os.replace", side_effect=OSError("crash")):
            with self.assertRaisesRegex(OSError, "crash"):
                self.store.pin("atomic")

        self.assertEqual(snapshot_path.read_bytes(), old_snapshot)
        self.assertEqual(list(snapshot_path.parent.glob("*.tmp")), [])
        events = self.store.events("atomic")
        self.assertEqual(
            [item["kind"] for item in events],
            ["topic_created", "pin_changed"],
        )
        reopened = TopicStore(self.root)
        self.assertTrue(reopened.read("atomic")["pinned"])

    def test_partial_cycle_and_linked_run_ids_are_preserved(self) -> None:
        self._create("partial")
        state = self._append(
            "partial", "partial", status="partial", run_status="cancelled"
        )
        self.assertEqual(state["cycles"][0]["status"], "partial")
        self.assertEqual(state["cycles"][0]["run_status"], "cancelled")
        self.assertEqual(state["linked_run_ids"], ["run-partial"])


if __name__ == "__main__":
    unittest.main()
