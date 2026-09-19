"""No-runtime invariants for the R0 inert content normalization boundary."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dialektike.content import (  # noqa: E402
    ContentNormalizationError,
    ContentPolicy,
    content_blocks_text,
    normalize_content_block,
    normalize_content_blocks,
)
from dialektike.adapters.claude import _render_claude_reply  # noqa: E402
from dialektike.adapters.codex import _render_codex_reply  # noqa: E402
from dialektike.domain import (  # noqa: E402
    ExtendedStructuredContentBlock,
    ModelProfile,
    ModelSelection,
    Role,
    StructuredContentBlock,
    TurnRecord,
    TurnResult,
    TurnStatus,
)
from dialektike.runs import RunStore  # noqa: E402
from dialektike.sidecar import JsonlSidecar, PROTOCOL_NAME  # noqa: E402
from dialektike.topics import TopicStore  # noqa: E402


# One raw source fixture is consumed by Python persistence/JSONL tests and by
# the TypeScript parser/DOM/copy tests. Do not duplicate or reconstruct it in
# either language: its authored trailing spaces and final newline are evidence.
UTF8_CONFORMANCE_FIXTURE_PATH = (
    REPO / "tests" / "fixtures" / "r0-canonical-response.md"
)
UTF8_CONFORMANCE_FIXTURE_BYTES = UTF8_CONFORMANCE_FIXTURE_PATH.read_bytes()
UTF8_CONFORMANCE_FIXTURE = UTF8_CONFORMANCE_FIXTURE_BYTES.decode("utf-8")
UTF8_CONFORMANCE_FIXTURE_SHA256 = (
    "51a9b9c21de835584af106221bb10c867101ec0c9acdaa16f2d28c04cbc88330"
)


class ContentNormalizationInvariants(unittest.TestCase):
    def test_utf8_fixture_is_byte_identical_for_every_descriptor(self) -> None:
        self.assertEqual(
            hashlib.sha256(UTF8_CONFORMANCE_FIXTURE_BYTES).hexdigest(),
            UTF8_CONFORMANCE_FIXTURE_SHA256,
        )
        provider_mapped = {
            "type": "markdown",
            "text": UTF8_CONFORMANCE_FIXTURE_BYTES.decode("utf-8", errors="strict"),
        }
        before = deepcopy(provider_mapped)

        # These names deliberately do not enter the normalizer.  A future
        # provider uses the same declared-content contract without an ID branch.
        for runtime_id in ("codex", "claude-code", "future-provider"):
            with self.subTest(runtime_id=runtime_id):
                (block,) = normalize_content_blocks(
                    [provider_mapped], declared_types=("markdown",)
                )
                self.assertEqual(block["text"], UTF8_CONFORMANCE_FIXTURE)
                self.assertEqual(
                    block["text"].encode("utf-8"),
                    UTF8_CONFORMANCE_FIXTURE_BYTES,
                )

        self.assertEqual(provider_mapped, before)

    def test_typed_blocks_keep_order_and_authored_strings_exactly(self) -> None:
        mapped: list[dict[str, Any]] = [
            {"type": "markdown", "text": "  prose Cafe\u0301  \n"},
            {
                "type": "code",
                "code": "\tprint('ﬁ')  \n",
                "language": " python ",
                "title": " Example ",
                "ignored": "must not cross",
            },
            {"type": "diff", "diff": "-old  \n+new\n", "title": " Patch "},
            {"type": "math", "text": "  x^2  ", "display": False},
            {
                "type": "diagram",
                "source": "  graph TD\nA-->B  \n",
                "language": " mermaid ",
                "title": " Flow ",
            },
            {
                "type": "tool",
                "title": " Shell ",
                "summary": "  exited 0\n",
                "status": " complete ",
            },
        ]
        before = deepcopy(mapped)

        blocks = normalize_content_blocks(
            mapped,
            declared_types=("markdown", "code", "diff", "math", "diagram", "tool"),
        )

        self.assertEqual(
            [block["type"] for block in blocks],
            ["markdown", "code", "diff", "math", "diagram", "tool"],
        )
        self.assertEqual(blocks[0]["text"], "  prose Cafe\u0301  \n")
        self.assertEqual(blocks[1]["code"], "\tprint('ﬁ')  \n")
        self.assertEqual(blocks[1]["language"], " python ")
        self.assertEqual(blocks[1]["title"], " Example ")
        self.assertNotIn("ignored", blocks[1])
        self.assertEqual(blocks[2]["diff"], "-old  \n+new\n")
        self.assertEqual(
            blocks[3],
            {
                "schema_version": 1,
                "type": "math",
                "text": "  x^2  ",
                "display": False,
            },
        )
        self.assertEqual(blocks[4]["source"], "  graph TD\nA-->B  \n")
        self.assertEqual(blocks[4]["language"], " mermaid ")
        self.assertEqual(blocks[5]["summary"], "  exited 0\n")
        self.assertEqual(mapped, before)

    def test_html_and_unknown_types_are_readable_inert_text(self) -> None:
        executable = (
            "<img src=x onerror=globalThis.__dialektike_executed__=true>"
            "<script>alert(1)</script>"
        )
        raw = {
            "type": "html<script>",
            "html": executable,
            "payload": {"owner_only_secret": "NEVER COPY THIS"},
            "action": "execute",
        }

        block = normalize_content_block(raw)

        self.assertEqual(block["type"], "unknown")
        self.assertEqual(block["provider_type"], "htmlscript")
        self.assertEqual(block["text"], executable)
        self.assertEqual(block["presentation"], "inert-text")
        self.assertNotIn("html", block)
        self.assertNotIn("payload", block)
        self.assertNotIn("action", block)
        self.assertNotIn("NEVER COPY THIS", repr(block))

    def test_descriptor_is_authoritative_without_provider_id_branches(self) -> None:
        raw = {"type": "code", "code": "print('not declared')"}

        block = normalize_content_block(raw, declared_types=("markdown",))

        self.assertEqual(block["type"], "unknown")
        self.assertEqual(block["provider_type"], "code")
        self.assertEqual(block["text"], raw["code"])
        self.assertIn("absent from its descriptor", block["reason"])

    def test_citations_accept_only_unambiguous_http_urls(self) -> None:
        safe_url = "https://例え.example/a%20b?q=Cafe%CC%81#fragment"
        safe = normalize_content_block(
            {"type": "citation", "label": "  Source  ", "url": safe_url},
            declared_types=("citation",),
        )
        self.assertEqual(safe["label"], "  Source  ")
        self.assertEqual(safe["url"], safe_url)

        unsafe_urls = (
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///private/etc/passwd",
            "https://user:secret@example.test/path",
            "https://example.test\\@attacker.test/path",
            "https://example.test/path\njavascript:alert(1)",
            "https://example.test:invalid/path",
            "/relative/path",
        )
        for url in unsafe_urls:
            with self.subTest(url=url):
                block = normalize_content_block(
                    {"type": "citation", "label": "Blocked", "url": url},
                    declared_types=("citation",),
                )
                self.assertEqual(block["type"], "unknown")
                self.assertEqual(block["text"], f"Blocked\n{url}")
                self.assertNotIn("url", block)

        disabled = normalize_content_block(
            {"type": "citation", "label": "Safe but disabled", "url": safe_url},
            policy=ContentPolicy(allow_http_citations=False),
        )
        self.assertEqual(disabled["type"], "unknown")

    def test_remote_media_never_becomes_a_renderable_reference(self) -> None:
        references = (
            ("url", "https://attacker.test/model-image.png"),
            ("url", "data:image/svg+xml,<svg onload=alert(1) />"),
            ("url", "file:///private/tmp/model-image.png"),
            ("path", "/private/tmp/model-image.png"),
        )
        for field_name, reference in references:
            with self.subTest(field_name=field_name, reference=reference):
                block = normalize_content_block(
                    {"type": "image", "label": "Model image", field_name: reference},
                    declared_types=("image",),
                )
                self.assertEqual(block["type"], "unknown")
                self.assertEqual(block["presentation"], "inert-text")
                self.assertNotIn("url", block)
                self.assertNotIn("path", block)
                self.assertNotIn("asset_id", block)

    def test_only_app_trusted_media_asset_ids_cross_the_boundary(self) -> None:
        raw = {
            "type": "image",
            "label": "  Architecture diagram  ",
            "asset_id": "asset:sha256.abc-123",
            "url": "https://attacker.test/ignored.png",
            "path": "/private/tmp/ignored.png",
            "alt": "  boxes and arrows  ",
            "mime_type": "image/png",
        }
        policy = ContentPolicy(trusted_asset_ids=frozenset({raw["asset_id"]}))

        trusted = normalize_content_block(raw, policy=policy)
        untrusted = normalize_content_block(raw)

        self.assertEqual(
            trusted,
            {
                "schema_version": 1,
                "type": "image",
                "asset_id": "asset:sha256.abc-123",
                "label": "  Architecture diagram  ",
                "alt": "  boxes and arrows  ",
                "mime_type": "image/png",
            },
        )
        self.assertNotIn("url", trusted)
        self.assertNotIn("path", trusted)
        self.assertEqual(untrusted["type"], "unknown")

    def test_files_and_editor_references_are_metadata_not_capabilities(self) -> None:
        file_block = normalize_content_block({
            "type": "file",
            "name": " evidence.txt ",
            "mime_type": "text/plain",
            "size": 12,
            "url": "javascript:alert(1)",
            "path": "/private/evidence.txt",
            "action": "open",
        })
        editor_block = normalize_content_block({
            "type": "editor_reference",
            "label": " inspect source ",
            "path": " src/example.py ",
            "line": 7,
            "column": 3,
            "url": "file:///private/src/example.py",
            "action": "open",
        })

        self.assertEqual(file_block["presentation"], "inert-metadata")
        self.assertEqual(file_block["name"], " evidence.txt ")
        self.assertEqual(file_block["size"], 12)
        self.assertNotIn("url", file_block)
        self.assertNotIn("path", file_block)
        self.assertNotIn("action", file_block)
        self.assertEqual(editor_block["presentation"], "inert-reference")
        self.assertEqual(editor_block["label"], " inspect source ")
        self.assertEqual(editor_block["path"], " src/example.py ")
        self.assertNotIn("url", editor_block)
        self.assertNotIn("action", editor_block)

    def test_invalid_boundary_and_policy_values_fail_closed(self) -> None:
        with self.assertRaises(ContentNormalizationError):
            normalize_content_block("not an object")  # type: ignore[arg-type]
        for asset_id in ("", "../escape", "contains space", "x" * 257):
            with self.subTest(asset_id=asset_id):
                with self.assertRaises(ValueError):
                    ContentPolicy(trusted_asset_ids=frozenset({asset_id}))
        with self.assertRaises(ValueError):
            ContentPolicy(allow_http_citations=1)  # type: ignore[arg-type]

    def test_domain_keeps_legacy_markdown_serialization_byte_compatible(self) -> None:
        authored = "  Cafe\N{COMBINING ACUTE ACCENT} and ﬁ  \n"

        block = StructuredContentBlock.markdown(authored)

        self.assertIs(type(block), StructuredContentBlock)
        self.assertEqual(block.text, authored)
        self.assertEqual(
            asdict(block),
            {
                "type": "markdown",
                "text": authored,
                "code": None,
                "diff": None,
                "language": None,
                "title": None,
                "summary": None,
                "status": None,
                "label": None,
                "url": None,
            },
        )

    def test_domain_extended_blocks_are_normalized_and_unknown_is_inert(self) -> None:
        policy = ContentPolicy(
            trusted_asset_ids=frozenset({"asset:sha256.safe-1"})
        )
        mapped = (
            {"type": "math", "text": " x^2 ", "display": False},
            {
                "type": "diagram",
                "source": "graph TD\nA-->B\n",
                "language": "mermaid",
            },
            {"type": "file", "name": "report.txt", "size": 42},
            {
                "type": "image",
                "label": "Diagram",
                "asset_id": "asset:sha256.safe-1",
                "url": "https://attacker.test/must-not-cross.png",
            },
            {
                "type": "editor_reference",
                "label": "Source",
                "path": "src/main.py",
                "line": 8,
            },
        )
        declared = tuple(str(item["type"]) for item in mapped)

        blocks = tuple(
            StructuredContentBlock.from_mapped(
                item,
                declared_types=declared,
                policy=policy,
            )
            for item in mapped
        )
        unknown = StructuredContentBlock.from_mapped(
            {
                "type": "future-canvas",
                "html": "<script>globalThis.executed = true</script>",
                "raw": {"owner_only_secret": "NEVER COPY"},
            },
            declared_types=(*declared, "future-canvas"),
        )

        self.assertTrue(
            all(isinstance(block, ExtendedStructuredContentBlock) for block in blocks)
        )
        extended = tuple(
            cast(ExtendedStructuredContentBlock, block) for block in blocks
        )
        self.assertEqual([block.type for block in blocks], [
            "math",
            "diagram",
            "file",
            "image",
            "editor_reference",
        ])
        self.assertFalse(extended[0].display)
        self.assertEqual(extended[1].source, "graph TD\nA-->B\n")
        self.assertEqual(extended[2].name, "report.txt")
        self.assertEqual(extended[3].asset_id, "asset:sha256.safe-1")
        self.assertIsNone(extended[3].url)
        self.assertIsNone(extended[3].path)
        self.assertEqual(extended[4].line, 8)
        unknown_extended = cast(ExtendedStructuredContentBlock, unknown)
        self.assertEqual(unknown.type, "unknown")
        self.assertEqual(
            unknown.text,
            "<script>globalThis.executed = true</script>",
        )
        self.assertEqual(unknown_extended.presentation, "inert-text")
        self.assertNotIn("owner_only_secret", repr(asdict(unknown)))

    def test_turn_text_is_the_canonical_projection_of_every_ordered_block(self) -> None:
        blocks = (
            StructuredContentBlock.markdown("  authored prose  \n"),
            StructuredContentBlock.from_mapped(
                {
                    "type": "code",
                    "title": " Example ",
                    "language": "python",
                    "code": "print('visible')\n",
                },
                declared_types=("code",),
            ),
        )
        canonical = content_blocks_text(asdict(block) for block in blocks)
        profile = ModelProfile(
            requested=ModelSelection(model_id="fixture-model")
        ).resolved(
            ModelSelection(model_id="fixture-model"),
            "fixture runtime echo",
        )

        result = TurnResult(
            text=canonical,
            blocks=blocks,
            model_profile=profile,
            account_route="fixture:subscription",
        )

        self.assertEqual(result.text, canonical)
        self.assertIn("print('visible')\n", result.text)
        with self.assertRaisesRegex(ValueError, "ordered content blocks"):
            TurnResult(
                text="context-only text",
                blocks=blocks,
                model_profile=profile,
                account_route="fixture:subscription",
            )
        with self.assertRaisesRegex(ValueError, "ordered content blocks"):
            TurnRecord(
                round_number=1,
                turn_number=1,
                role=Role.EXECUTOR,
                participant_id="executor-seat",
                adapter_id="fixture-adapter",
                status=TurnStatus.COMPLETED,
                input_text="fixture input",
                text="context-only text",
                blocks=blocks,
                model_profile=profile,
                account_route="fixture:subscription",
            )

    def test_provider_reply_assembly_never_strips_authored_edges(self) -> None:
        parts = [
            "  leading Cafe\N{COMBINING ACUTE ACCENT}\n",
            "trailing Straße and ﬁ  \n\n",
        ]
        expected = parts[0] + "\n\n" + parts[1]

        self.assertEqual(_render_codex_reply(parts), expected)
        self.assertEqual(_render_claude_reply(parts), expected)
        wrapped = "\t\n\n" + expected + "\n\n  "
        self.assertEqual(_render_codex_reply(["\t", *parts, "  "]), wrapped)
        self.assertEqual(_render_claude_reply(["\t", *parts, "  "]), wrapped)
        self.assertEqual(
            _render_claude_reply([], " fallback with final newline\n"),
            " fallback with final newline\n",
        )


class ContentTransportInvariants(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_fixture_crosses_assemblers_topic_and_jsonl_exactly(
        self,
    ) -> None:
        self.assertEqual(
            _render_codex_reply([UTF8_CONFORMANCE_FIXTURE]),
            UTF8_CONFORMANCE_FIXTURE,
        )
        self.assertEqual(
            _render_claude_reply([UTF8_CONFORMANCE_FIXTURE]),
            UTF8_CONFORMANCE_FIXTURE,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output: list[str] = []
            run_store = RunStore(root / "runs")
            sidecar = JsonlSidecar(
                store=run_store,
                adapters={},
                write_line=output.append,
            )
            participant_config = {
                "rounds": 1,
                "participants": [
                    {
                        "participant_id": "executor-seat",
                        "role": "executor",
                        "order": 0,
                        "runtime_id": "codex",
                        "requested": {
                            "model": "fixture-model",
                            "effort": "high",
                            "service_tier": "native-default",
                        },
                    }
                ],
            }
            sidecar.topic_store.create(
                topic_id="content-fixture",
                title="Content fixture",
                participant_config=participant_config,
            )
            block = StructuredContentBlock.markdown(UTF8_CONFORMANCE_FIXTURE)
            with self.assertRaisesRegex(ValueError, "ordered content blocks"):
                sidecar.topic_store.append_cycle(
                    "content-fixture",
                    live_prompt="Reject divergent context.",
                    run_id="fixture-divergent",
                    run_status="completed",
                    status="completed",
                    participant_config=participant_config,
                    messages=[
                        {
                            "role": "executor",
                            "stage": "synthesis",
                            "text": "different canonical context",
                            "blocks": [asdict(block)],
                        }
                    ],
                )
            sidecar.topic_store.append_cycle(
                "content-fixture",
                live_prompt="Preserve the canonical response fixture.",
                run_id="fixture-run",
                run_status="completed",
                status="completed",
                participant_config=participant_config,
                messages=[
                    {
                        "id": "fixture-run:synthesis",
                        "participant_id": "executor-seat",
                        "role": "executor",
                        "runtime_id": "codex",
                        "stage": "synthesis",
                        "text": UTF8_CONFORMANCE_FIXTURE,
                        "blocks": [asdict(block)],
                    }
                ],
            )

            reopened = TopicStore(root)
            stored_message = reopened.read("content-fixture")["cycles"][0][
                "messages"
            ][0]
            self.assertEqual(
                stored_message["text"].encode("utf-8"),
                UTF8_CONFORMANCE_FIXTURE_BYTES,
            )
            self.assertEqual(
                stored_message["blocks"][0]["text"].encode("utf-8"),
                UTF8_CONFORMANCE_FIXTURE_BYTES,
            )

            await sidecar.handle_line(
                json.dumps(
                    {
                        "protocol": PROTOCOL_NAME,
                        "id": "read-content-fixture",
                        "command": "topic.read",
                        "payload": {"topic_id": "content-fixture"},
                    },
                    ensure_ascii=False,
                )
            )
            loaded = next(
                json.loads(line)
                for line in output
                if json.loads(line).get("event") == "topic.loaded"
            )
            wire_message = loaded["payload"]["topic"]["messages"][0]
            self.assertEqual(
                wire_message["text"].encode("utf-8"),
                UTF8_CONFORMANCE_FIXTURE_BYTES,
            )
            self.assertEqual(
                wire_message["blocks"][0]["text"].encode("utf-8"),
                UTF8_CONFORMANCE_FIXTURE_BYTES,
            )
            await sidecar.input_closed()


if __name__ == "__main__":
    unittest.main()
