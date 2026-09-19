"""Proof that one core serves two clients (audit R4 / Codex's Tauri-risk pull-forward).

The Broker takes a Presenter — a function receiving (request, rendered card) and
returning Live's decision. The CLI presenter reads the terminal; the GUI presenter
will push the same card over a local event channel to the Tauri webview and await
the click. Neither changes a line of core code. This stub demonstrates the contract
with a queue-based presenter standing in for the GUI event loop.

Static demonstration only — runs no LLM and is not executed until the manifest
is approved (it needs no model, but the pause is the pause).
"""

from __future__ import annotations

import queue
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core.broker import ActionRequest, Broker, ChainedLog, Decision  # noqa: E402


def gui_presenter_factory(inbox: "queue.Queue[tuple[ActionRequest, str]]",
                          outbox: "queue.Queue[Decision]"):
    """The future Tauri client: cards go OUT to the webview, decisions come BACK.
    The core neither knows nor cares that a browser is on the other side."""
    def present(req: ActionRequest, card: str) -> Decision:
        inbox.put((req, card))          # → rendered as a permission card in the GUI
        return outbox.get(timeout=30)   # ← Live clicks Allow once / Deny
    return present


def demo() -> bool:
    staging = REPO / "spike" / "v2" / "staging"
    log = ChainedLog(REPO / "evidence" / "clients-stub" / "decisions.jsonl")
    inbox: "queue.Queue" = queue.Queue()
    outbox: "queue.Queue" = queue.Queue()

    broker = Broker(mode="ask", log=log, staging_root=staging,
                    presenter=gui_presenter_factory(inbox, outbox))

    req = ActionRequest(case="stub", phase="demo", model="none", role="executor",
                        tool="mcp__dialektike__propose_write",
                        tool_input={"path": "hello.txt", "content": "via gui presenter"})
    outbox.put("deny")  # simulate Live clicking Deny in the GUI
    decision, reason = broker.decide(req)
    assert decision == "deny" and not inbox.empty()
    return True


if __name__ == "__main__":
    print("clients stub OK" if demo() else "clients stub FAIL")
