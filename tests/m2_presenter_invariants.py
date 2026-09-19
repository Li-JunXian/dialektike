"""No-model invariants for the trusted GUI permission presenter."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.broker import ChainedLog  # noqa: E402
from core.relay import (  # noqa: E402
    NormalizedRequest,
    PermissionRelay,
)
from dialektike.presenters.bridge import (  # noqa: E402
    BridgePermissionError,
    BridgePresenter,
)


def request() -> NormalizedRequest:
    return NormalizedRequest(
        provider="claude",
        case="case",
        phase="turn-1",
        model="claude-opus-5",
        role="executor",
        kind="can_use_tool",
        payload={
            "tool": "Write",
            "input": {"file_path": "/tmp/example", "content": "full content"},
            "native_context": {"title": "Write a file"},
        },
        correlation_id="wire-correlation",
        annotations={"path_confined": False},
    ).enrich()


class BridgePresenterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.delivered = asyncio.Event()
        self.presenter = BridgePresenter()

        async def emit(event: str, payload: dict) -> None:
            self.events.append((event, payload))
            self.delivered.set()

        self.presenter.bind(asyncio.get_running_loop(), emit)

    async def test_full_native_payload_is_delivered_and_live_answer_wakes_once(self):
        native = request()
        with tempfile.TemporaryDirectory() as td:
            ledger = ChainedLog(Path(td) / "decisions.jsonl")
            relay = PermissionRelay(
                ledger,
                presenter=self.presenter,
                raw_dir=Path(td) / "raw",
            )
            task = asyncio.create_task(
                asyncio.to_thread(relay.relay, native)
            )
            await asyncio.wait_for(self.delivered.wait(), timeout=2)
            event, payload = self.events[0]
            self.assertEqual(event, "permission.request")
            self.assertEqual(payload["runtime_id"], "claude-code")
            self.assertIn("full content", payload["card"])
            self.assertEqual(
                payload["native_payload"]["input"]["content"], "full content"
            )
            self.assertEqual(payload["title"], "Write a file")
            permission_id = payload["permission_id"]
            self.assertTrue(self.presenter.respond(permission_id, "allow_once"))
            self.assertFalse(self.presenter.respond(permission_id, "deny"))
            decision, _ = await asyncio.wait_for(task, timeout=2)
            self.assertEqual(decision, "allow")
            self.assertEqual(self.presenter.pending_ids, ())
            self.assertEqual(self.events[-1][0], "permission.recorded")
            self.assertEqual(
                self.events[-1][1]["permission_id"], permission_id
            )
            records = ledger.verified_records()
            self.assertEqual(records[-1]["kind"], "permission_decision")
            self.assertEqual(records[-1]["decision"], "allow")

    async def test_control_loss_fails_open_card_closed(self):
        task = asyncio.create_task(
            asyncio.to_thread(self.presenter, request(), "FULL CARD")
        )
        await asyncio.wait_for(self.delivered.wait(), timeout=2)
        self.presenter.fail_pending("GUI control input closed")
        with self.assertRaisesRegex(
            BridgePermissionError, "GUI control input closed"
        ):
            await asyncio.wait_for(task, timeout=2)

    async def test_unknown_and_invalid_responses_are_rejected(self):
        self.assertFalse(self.presenter.respond("missing", "allow_once"))
        with self.assertRaises(BridgePermissionError):
            self.presenter.respond("missing", "sometimes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
