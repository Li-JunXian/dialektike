"""No-model invariants for next-update topic search and checkpoints."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dialektike.topics import TopicDeletedError, TopicStore  # noqa: E402
from dialektike import search as search_module  # noqa: E402
from dialektike.search import TopicSearchIndex  # noqa: E402


def _participants() -> dict:
    return {
        "executor": {"runtime_id": "codex", "model": "default"},
        "auditors": [{"runtime_id": "claude-code", "model": "default"}],
    }


def _messages(label: str, *, secret: str | None = None) -> list[dict]:
    synthesis = {
        "id": f"run-{label}:synthesis",
        "participant_id": "executor-seat",
        "role": "executor",
        "runtime_id": "codex",
        "stage": "synthesis",
        "text": f"Synthesis {label}",
        "blocks": [{"type": "markdown", "text": f"Synthesis {label}"}],
    }
    if secret is not None:
        synthesis["owner_only_evidence"] = {"raw": secret}
    return [
        {
            "id": f"run-{label}:proposal",
            "participant_id": "executor-seat",
            "role": "executor",
            "runtime_id": "codex",
            "stage": "proposal",
            "text": f"Proposal {label}",
            "blocks": [{"type": "markdown", "text": f"Proposal {label}"}],
        },
        {
            "id": f"run-{label}:audit",
            "participant_id": "auditor-seat",
            "role": "auditor",
            "runtime_id": "claude-code",
            "stage": "audit",
            "text": f"Audit {label}",
            "blocks": [{"type": "markdown", "text": f"Audit {label}"}],
        },
        synthesis,
    ]


class TopicSearchAndCheckpointInvariants(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "state"
        self.store = TopicStore(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create(self, topic_id: str, title: str) -> None:
        self.store.create(
            topic_id=topic_id,
            title=title,
            participant_config=_participants(),
        )

    def _append(self, topic_id: str, label: str, *, prompt: str | None = None) -> None:
        self.store.append_cycle(
            topic_id,
            live_prompt=prompt or f"Live prompt {label}",
            run_id=f"run-{label}",
            run_status="completed",
            status="completed",
            messages=_messages(label, secret="OWNER-RAW-DO-NOT-INDEX"),
        )

    def test_occurrence_search_is_nfkc_casefolded_and_preserves_authored_text(self) -> None:
        self._create("unicode", "Café security")
        authored = "Straße ﬁle ⁧שלום⁩"
        self._append("unicode", "unicode", prompt=authored)
        before = self.store.read("unicode")

        title_hits = self.store.search_occurrences("Cafe\N{COMBINING ACUTE ACCENT}")
        self.assertEqual(len(title_hits), 1)
        self.assertEqual(title_hits[0]["source_anchor"], "topic:unicode:title")
        self.assertEqual(
            [segment["text"] for segment in title_hits[0]["snippet_segments"]],
            ["Café", " security"],
        )
        self.assertTrue(title_hits[0]["snippet_segments"][0]["highlighted"])

        content_hits = self.store.search_occurrences("STRASSE FILE")
        self.assertEqual(len(content_hits), 1)
        hit = content_hits[0]
        self.assertEqual(hit["source_anchor"], "run-unicode:live")
        highlighted = "".join(
            segment["text"]
            for segment in hit["snippet_segments"]
            if segment["highlighted"]
        )
        self.assertEqual(highlighted, "Straße ﬁle")
        self.assertEqual(hit["match_start_utf8"], 0)
        self.assertEqual(hit["match_end_utf8"], len("Straße ﬁle".encode()))
        self.assertEqual(self.store.read("unicode"), before)

    def test_fold_expansions_emit_one_hit_per_authored_occurrence(self) -> None:
        state = {
            "topic_id": "fold-expansion",
            "title": "Ω",
            "archived": False,
            "deleted": False,
            "pinned": False,
            "updated_at": 1.0,
            "last_sequence": 1,
            "cycles": [
                {
                    "run_id": "run-fold",
                    "live_prompt": "ßs ﬀf",
                    "messages": [],
                }
            ],
        }
        index = TopicSearchIndex()

        s_hits = index.search([state], "s")
        self.assertEqual(len(s_hits), 2)
        self.assertEqual(
            [
                "".join(
                    part["text"]
                    for part in hit["snippet_segments"]
                    if part["highlighted"]
                )
                for hit in s_hits
            ],
            ["ß", "s"],
        )

        f_hits = index.search([state], "f")
        self.assertEqual(len(f_hits), 2)
        self.assertEqual(
            [
                "".join(
                    part["text"]
                    for part in hit["snippet_segments"]
                    if part["highlighted"]
                )
                for hit in f_hits
            ],
            ["ﬀ", "f"],
        )

    def test_canonical_reordering_maps_to_every_authored_dependency(self) -> None:
        authored = "a\N{COMBINING COMMA ABOVE RIGHT}\N{COMBINING GRAVE ACCENT}"
        state = {
            "topic_id": "canonical-reordering",
            "title": "Ω",
            "archived": False,
            "deleted": False,
            "pinned": False,
            "updated_at": 1.0,
            "last_sequence": 1,
            "cycles": [
                {
                    "run_id": "run-reorder",
                    "live_prompt": authored,
                    "messages": [],
                }
            ],
        }

        hits = TopicSearchIndex().search([state], "à")
        self.assertEqual(len(hits), 1)
        highlighted = "".join(
            part["text"]
            for part in hits[0]["snippet_segments"]
            if part["highlighted"]
        )
        self.assertEqual(highlighted, authored)
        self.assertEqual(hits[0]["match_start_utf8"], 0)
        self.assertEqual(
            hits[0]["match_end_utf8"], len(authored.encode("utf-8"))
        )

    def test_pathological_combining_run_has_bounded_normalization_work(self) -> None:
        authored = (
            "a"
            + "\N{COMBINING COMMA ABOVE RIGHT}" * 4096
            + "\N{COMBINING GRAVE ACCENT}"
        )
        state = {
            "topic_id": "long-combining-run",
            "title": "Ω",
            "archived": False,
            "deleted": False,
            "pinned": False,
            "updated_at": 1.0,
            "last_sequence": 1,
            "cycles": [
                {
                    "run_id": "run-long-combining",
                    "live_prompt": authored,
                    "messages": [],
                }
            ],
        }
        original = search_module.normalize_for_search
        normalized_input_characters = 0

        def counted(value: str) -> str:
            nonlocal normalized_input_characters
            normalized_input_characters += len(value)
            return original(value)

        with patch.object(search_module, "normalize_for_search", counted):
            hits = TopicSearchIndex().search([state], "à")

        self.assertEqual(len(hits), 1)
        self.assertLess(
            normalized_input_characters,
            len(authored) * 5,
        )

    def test_topic_filter_uses_the_same_nfkc_matching_contract(self) -> None:
        self._create("topic-filter", "Ｆｕｌｌｗｉｄｔｈ Café")
        self.assertEqual(
            [item["topic_id"] for item in self.store.search("fullwidth café")],
            ["topic-filter"],
        )

    def test_search_returns_visible_occurrences_and_never_owner_raw_evidence(self) -> None:
        self._create("visible", "Ordinary topic")
        self._append("visible", "visible")

        proposal = self.store.search_occurrences("proposal visible")
        audit = self.store.search_occurrences("audit visible")
        synthesis = self.store.search_occurrences("synthesis visible")
        self.assertEqual(proposal[0]["stage"], "proposal")
        self.assertEqual(audit[0]["speaker"], "auditor-seat")
        self.assertEqual(
            synthesis[0]["source_anchor"], "run-visible:synthesis"
        )
        self.assertIsInstance(synthesis[0]["timestamp"], str)
        self.assertEqual(
            self.store.search_occurrences("OWNER-RAW-DO-NOT-INDEX"), []
        )

    def test_archived_topics_are_included_by_default_and_tombstones_excluded(self) -> None:
        self._create("active", "Shared needle active")
        self._create("archived", "Shared needle archived")
        self._create("deleted", "Shared needle deleted")
        self.store.archive("archived")
        self.store.delete("deleted")

        all_hits = self.store.search_occurrences("shared needle")
        self.assertEqual(
            {hit["topic_id"] for hit in all_hits}, {"active", "archived"}
        )
        self.assertTrue(
            next(hit for hit in all_hits if hit["topic_id"] == "archived")[
                "archived"
            ]
        )
        self.assertEqual(
            {hit["topic_id"] for hit in self.store.search_occurrences(
                "shared needle", archived=False
            )},
            {"active"},
        )

    def test_derived_index_tracks_every_topic_mutation_and_rebuilds(self) -> None:
        self._create("updates", "Initial title")
        self.assertEqual(len(self.store.search_occurrences("initial")), 1)
        self.store.rename("updates", "Renamed title")
        self.assertEqual(self.store.search_occurrences("initial"), [])
        self.assertEqual(len(self.store.search_occurrences("renamed")), 1)

        self._append("updates", "later", prompt="New body occurrence")
        self.assertEqual(
            self.store.search_occurrences("new body")[0]["source_anchor"],
            "run-later:live",
        )
        self.store.archive("updates")
        self.assertTrue(self.store.search_occurrences("new body")[0]["archived"])
        self.store.rebuild_search_index()
        self.assertEqual(len(self.store.search_occurrences("new body")), 1)
        self.store.delete("updates")
        self.assertEqual(self.store.search_occurrences("new body"), [])

    def test_checkpoint_requires_valid_source_and_draft_does_not_change_context(self) -> None:
        self._create("checkpoint", "Checkpoint topic")
        self._append("checkpoint", "first")
        original = self.store.canonical_context("checkpoint")
        source = self.store.checkpoint_source("checkpoint")
        tampered = {**source, "source_sha256": "0" * 64}

        with self.assertRaisesRegex(ValueError, "source_sha256"):
            self.store.draft_context_checkpoint(
                "checkpoint",
                checkpoint_id="checkpoint-bad",
                source=tampered,
                summary="Must not persist",
                creator={"kind": "runtime", "runtime_id": "codex"},
            )
        tampered_entries = json.loads(json.dumps(source))
        tampered_entries["entries"][0]["text"] = "fabricated source"
        with self.assertRaisesRegex(ValueError, "source entries"):
            self.store.draft_context_checkpoint(
                "checkpoint",
                checkpoint_id="checkpoint-bad-entries",
                source=tampered_entries,
                summary="Must not persist",
                creator={"kind": "runtime", "runtime_id": "codex"},
            )
        self.assertEqual(self.store.canonical_context("checkpoint"), original)
        self.assertNotIn(
            "context_checkpoint_drafted",
            [event["kind"] for event in self.store.events("checkpoint")],
        )

        summary = "  Reviewable authored summary.  "
        drafted = self.store.draft_context_checkpoint(
            "checkpoint",
            checkpoint_id="checkpoint-good",
            source=source,
            summary=summary,
            creator={
                "kind": "runtime",
                "runtime_id": "codex",
                "effective_model": "gpt-test",
                "authority": "test echo",
            },
        )
        self.assertIsNone(drafted["active_context_checkpoint_id"])
        self.assertEqual(self.store.canonical_context("checkpoint"), original)
        self.assertEqual(drafted["context_checkpoints"][0]["summary"], summary)
        self.assertEqual(
            drafted["context_checkpoints"][0]["context_estimate"]["unit"],
            "utf8_bytes",
        )

    def test_checkpoint_requires_a_completed_nonpartial_executor_synthesis(self) -> None:
        self._create("no-synthesis", "No synthesis")
        self.store.append_cycle(
            "no-synthesis",
            live_prompt="Live prompt",
            run_id="run-no-synthesis",
            run_status="completed",
            status="completed",
            messages=_messages("no-synthesis")[:2],
        )
        with self.assertRaisesRegex(ValueError, "completed answer or synthesis"):
            self.store.checkpoint_source("no-synthesis")

        self._create("partial-synthesis", "Partial synthesis")
        partial_messages = _messages("partial-synthesis")
        partial_messages[-1]["partial"] = True
        self.store.append_cycle(
            "partial-synthesis",
            live_prompt="Live prompt",
            run_id="run-partial-synthesis",
            run_status="cancelled",
            status="partial",
            messages=partial_messages,
        )
        with self.assertRaisesRegex(ValueError, "completed answer or synthesis"):
            self.store.checkpoint_source("partial-synthesis")

        self._create("completed-synthesis", "Completed synthesis")
        self._append("completed-synthesis", "completed-synthesis")
        source = self.store.checkpoint_source("completed-synthesis")
        self.assertEqual(source["source_end_anchor"], "run-completed-synthesis:synthesis")

    def test_checkpoint_leaves_a_later_partial_cycle_outside_the_compacted_prefix(self) -> None:
        self._create("partial-tail", "Partial tail")
        self._append("partial-tail", "complete")
        partial_messages = _messages("partial-tail")
        partial_messages[-1]["partial"] = True
        self.store.append_cycle(
            "partial-tail",
            live_prompt="Unresolved Live prompt",
            run_id="run-partial-tail",
            run_status="cancelled",
            status="partial",
            messages=partial_messages,
        )
        source = self.store.checkpoint_source("partial-tail")
        self.assertEqual(source["source_end_anchor"], "run-complete:synthesis")
        self.assertNotIn(
            "Unresolved Live prompt",
            [entry["text"] for entry in source["entries"]],
        )

    def test_approval_uses_checkpoint_plus_post_boundary_and_deactivation_restores_all(self) -> None:
        self._create("lifecycle", "Lifecycle")
        self._append("lifecycle", "first")
        source = self.store.checkpoint_source("lifecycle")
        self.store.draft_context_checkpoint(
            "lifecycle",
            checkpoint_id="checkpoint-one",
            source=source,
            summary="Approved compact summary",
            creator={"kind": "runtime", "runtime_id": "codex"},
        )
        # Appending after draft is safe: approval validates the immutable source
        # prefix while retaining the later entries outside the checkpoint.
        self._append("lifecycle", "second")
        before_approval = self.store.read("lifecycle")
        self.store.approve_context_checkpoint("lifecycle", "checkpoint-one")

        effective = self.store.canonical_context("lifecycle")
        self.assertEqual(
            [(entry["role"], entry["stage"]) for entry in effective],
            [
                ("context", "checkpoint"),
                ("live", "prompt"),
                ("executor", "synthesis"),
            ],
        )
        self.assertEqual(effective[0]["text"], "Approved compact summary")
        self.assertEqual(effective[1]["text"], "Live prompt second")
        # Approval did not mutate or remove any original cycle/message.
        self.assertEqual(
            self.store.read("lifecycle")["cycles"], before_approval["cycles"]
        )

        self.store.deactivate_context_checkpoint("lifecycle")
        restored = self.store.canonical_context("lifecycle")
        self.assertEqual(
            [entry["text"] for entry in restored],
            [
                "Live prompt first",
                "Synthesis first",
                "Live prompt second",
                "Synthesis second",
            ],
        )
        reopened = TopicStore(self.root)
        self.assertIsNone(
            reopened.read("lifecycle")["active_context_checkpoint_id"]
        )
        self.assertEqual(reopened.canonical_context("lifecycle"), restored)
        self.assertEqual(
            [event["kind"] for event in reopened.events("lifecycle")][-3:],
            [
                "cycle_appended",
                "context_checkpoint_approved",
                "context_checkpoint_deactivated",
            ],
        )

    def test_failed_new_draft_leaves_existing_checkpoint_active(self) -> None:
        self._create("failure", "Failure safety")
        self._append("failure", "first")
        source = self.store.checkpoint_source("failure")
        self.store.draft_context_checkpoint(
            "failure",
            checkpoint_id="checkpoint-active",
            source=source,
            summary="Still active",
            creator={"kind": "runtime", "runtime_id": "codex"},
        )
        self.store.approve_context_checkpoint("failure", "checkpoint-active")
        broken = {**source, "topic_id": "different-topic"}
        with self.assertRaisesRegex(ValueError, "different topic"):
            self.store.draft_context_checkpoint(
                "failure",
                checkpoint_id="checkpoint-failed",
                source=broken,
                summary="Never active",
                creator={"kind": "runtime", "runtime_id": "codex"},
            )
        state = self.store.read("failure")
        self.assertEqual(
            state["active_context_checkpoint_id"], "checkpoint-active"
        )
        self.assertEqual(
            self.store.canonical_context("failure")[0]["text"], "Still active"
        )

    def test_tombstoned_topics_cannot_create_or_change_checkpoints(self) -> None:
        self._create("deleted-checkpoint", "Deleted checkpoint")
        self._append("deleted-checkpoint", "deleted")
        source = self.store.checkpoint_source("deleted-checkpoint")
        self.store.delete("deleted-checkpoint")
        with self.assertRaises(TopicDeletedError):
            self.store.draft_context_checkpoint(
                "deleted-checkpoint",
                source=source,
                summary="Unavailable",
                creator={"kind": "runtime", "runtime_id": "codex"},
            )

    def test_checkpoint_event_history_keeps_summary_and_originals_append_only(self) -> None:
        self._create("evidence", "Evidence")
        self._append("evidence", "one")
        source = self.store.checkpoint_source("evidence")
        self.store.draft_context_checkpoint(
            "evidence",
            checkpoint_id="checkpoint-evidence",
            source=source,
            summary="Evidence summary",
            creator={"kind": "live-authored"},
        )
        self.store.approve_context_checkpoint("evidence", "checkpoint-evidence")
        encoded = json.dumps(self.store.events("evidence"), ensure_ascii=False)
        self.assertIn("Live prompt one", encoded)
        self.assertIn("Synthesis one", encoded)
        self.assertIn("Evidence summary", encoded)
        self.assertIn(source["source_sha256"], encoded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
