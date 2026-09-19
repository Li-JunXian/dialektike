"""Dialektikḗ feasibility spike — Claude adapter leg.

Proves, on subscription auth (no API key):
  1. one structured, schema-shaped turn (claim audit → strict JSON verdict)
  2. session resume across separate client instances
  3. the permission broker: a staged Write both APPROVED and DENIED by our code

Run:  BROKER_MODE=auto ./venv/bin/python spike/claude_spike.py   (scripted broker)
      BROKER_MODE=ask  ./venv/bin/python spike/claude_spike.py   (you approve/deny live)
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
)

STAGING = Path(__file__).parent / "out" / "claude-staging"
MODEL = "haiku"  # cheapest against the shared plan quota; the mechanism, not the mind, is under test

VERDICT_KEYS = {"claim_id", "verdict", "argument"}
AUDIT_PROMPT = (
    "You are the Auditor in a dialectic protocol. Audit this claim:\n"
    '  C1: "A shared filesystem directory is an acceptable blindness boundary between two models."\n'
    "Reply with ONLY a JSON object, no markdown fences, no prose, exactly these keys:\n"
    '  {"claim_id": "C1", "verdict": "AGREE" | "CHALLENGE" | "INSUFFICIENT EVIDENCE", "argument": "<one sentence>"}'
)


def card(tool: str, tool_input: dict) -> str:
    preview = json.dumps(tool_input, ensure_ascii=False)
    if len(preview) > 200:
        preview = preview[:200] + "…"
    return (
        "\n┌─ PERMISSION CARD ────────────────────────────\n"
        f"│ model:  claude ({MODEL})   role: executor (spike)\n"
        f"│ action: {tool}\n"
        f"│ target: {preview}\n"
        f"│ cwd:    {STAGING}\n"
        "└──────────────────────────────────────────────"
    )


def make_broker(decision_when_auto: str):
    async def can_use_tool(tool_name, tool_input, context):
        print(card(tool_name, tool_input))
        mode = os.environ.get("BROKER_MODE", "auto")
        if mode == "ask":
            choice = input("broker> allow once / deny [a/d]: ").strip().lower()
            decision = "allow" if choice.startswith("a") else "deny"
        else:
            decision = decision_when_auto
            print(f"broker> scripted decision: {decision.upper()}")
        if decision == "allow":
            return PermissionResultAllow()
        return PermissionResultDeny(message="Denied by Dialektikḗ broker (spike test)")

    return can_use_tool


async def collect(client) -> tuple[str, str | None]:
    """Drain one response; return (assistant text, session_id)."""
    text, session_id = [], None
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text.append(block.text)
        elif isinstance(msg, ResultMessage):
            session_id = msg.session_id
    return "".join(text).strip(), session_id


async def part1_structured_turn() -> str:
    opts = ClaudeAgentOptions(cwd=str(STAGING), model=MODEL, max_turns=1)
    async with ClaudeSDKClient(options=opts) as client:
        await client.query(AUDIT_PROMPT)
        text, session_id = await collect(client)
    raw = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    verdict = json.loads(raw)
    assert VERDICT_KEYS <= set(verdict), f"missing keys: {VERDICT_KEYS - set(verdict)}"
    assert verdict["verdict"] in {"AGREE", "CHALLENGE", "INSUFFICIENT EVIDENCE"}
    print(f"PART 1 PASS — schema-valid verdict: {verdict['verdict']} on {verdict['claim_id']}")
    print(f"          argument: {verdict['argument']}")
    assert session_id, "no session_id captured"
    return session_id


async def part2_resume(session_id: str):
    opts = ClaudeAgentOptions(cwd=str(STAGING), model=MODEL, max_turns=1, resume=session_id)
    async with ClaudeSDKClient(options=opts) as client:
        await client.query("Which claim_id did you audit in this session? Reply with the ID only.")
        text, _ = await collect(client)
    assert "C1" in text, f"resume failed — model replied: {text!r}"
    print(f"PART 2 PASS — session {session_id[:8]}… resumed; model recalled: {text}")


async def part3_broker():
    # Leg A: broker APPROVES a staged write
    opts = ClaudeAgentOptions(
        cwd=str(STAGING), model=MODEL, max_turns=3,
        permission_mode="default", can_use_tool=make_broker("allow"),
    )
    async with ClaudeSDKClient(options=opts) as client:
        await client.query(
            "Use the Write tool to create a file named approved.txt in the current "
            "directory containing exactly: dialektike spike"
        )
        await collect(client)
    approved = STAGING / "approved.txt"
    assert approved.exists() and "dialektike spike" in approved.read_text()
    print("PART 3a PASS — broker ALLOWED; approved.txt exists in staging")

    # Leg B: broker DENIES the same class of action
    opts = ClaudeAgentOptions(
        cwd=str(STAGING), model=MODEL, max_turns=3,
        permission_mode="default", can_use_tool=make_broker("deny"),
    )
    async with ClaudeSDKClient(options=opts) as client:
        await client.query(
            "Use the Write tool to create a file named denied.txt in the current "
            "directory containing exactly: this must never exist. If you are denied "
            "permission, stop and say DENIED-OK."
        )
        text, _ = await collect(client)
    assert not (STAGING / "denied.txt").exists(), "denied.txt exists — broker deny FAILED"
    print(f"PART 3b PASS — broker DENIED; denied.txt absent; model said: {text[:80]}")


async def main():
    shutil.rmtree(STAGING, ignore_errors=True)
    STAGING.mkdir(parents=True)
    session_id = await part1_structured_turn()
    await part2_resume(session_id)
    await part3_broker()
    print("\nALL CLAUDE SPIKE CHECKS PASSED — adapter path is viable on subscription auth.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print(f"SPIKE FAIL: {e}")
        sys.exit(1)
