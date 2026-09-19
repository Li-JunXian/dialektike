"""Dialektikḗ M1 — Claude leg: one Agent SDK query under native settings.

Native parity (governance 0002/0003): the SDK runs with the CLI's native
defaults (setting_sources=None → all settings sources, default toolset,
default permission mode). Whatever the native runtime asks permission for
reaches Live exactly once through the shared PermissionRelay; whatever it
auto-permits (including in-cwd reads, which bypass can_use_tool) is
audit-logged via PostToolUse(+Failure) hooks and never re-prompted.

Verified wire facts honored here: the SDK merges os.environ into its child
(gates.scrub_environment runs first, in-process); cwd must exist.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from core.broker import sha256_text
from core.relay import NormalizedRequest, PermissionRelay, path_annotations

CASE = "m1-dialogue"
ROLE = "first-voice"
MODEL_LABEL = "claude (native default)"


def classify_rate_limit(info) -> str | None:
    """Standing authorization: stop on a genuine plan warning/limit — or when
    the account is ACTUALLY CONSUMING pay-as-you-go overage (axiom 1: no
    pay-per-token). Returns the stop reason, or None for healthy bookkeeping.

    `overage_status` describes the overage FACILITY, not consumption:
      - "rejected"  → overage unavailable (2026-07-16 evidence:
                      overageDisabledReason=out_of_credits on a healthy acct);
      - "allowed"   → overage merely AVAILABLE — NOT a violation on its own
                      (2026-07-24 evidence: status=allowed, overageStatus=
                      allowed, isUsingOverage=false = within subscription).
    The authoritative "billing pay-per-token right now" signal is
    `isUsingOverage`. The pre-emptive protection is `status` reaching
    allowed_warning/rejected BEFORE the window spills to overage."""
    if info.status in ("allowed_warning", "rejected"):
        return (f"plan usage {info.status} (type={info.rate_limit_type}, "
                f"utilization={info.utilization})")
    if (info.raw or {}).get("isUsingOverage"):
        return ("account is drawing pay-as-you-go overage "
                "(isUsingOverage) — axiom 1 forbids pay-per-token")
    return None


def _normalized(tool_name: str, tool_input: dict, kind: str, tool_use_id: str,
                workspace: Path, payload_extra: dict | None = None,
                annotations: dict | None = None) -> NormalizedRequest:
    """Runtime identifiers are hashed at this boundary; a missing tool_use_id
    is rejected BEFORE hashing (sha256("") would masquerade as a valid key)."""
    if not tool_use_id:
        raise ValueError(f"{kind}: runtime supplied no tool_use_id — cannot form "
                         "an exactly-once correlation key (fail closed)")
    return NormalizedRequest(
        provider="claude", case=CASE, phase="claude", model=MODEL_LABEL, role=ROLE,
        kind=kind,
        payload={"tool": tool_name, "input": dict(tool_input), **(payload_extra or {})},
        correlation_id=sha256_text(tool_use_id),
        annotations={**path_annotations(dict(tool_input), workspace),
                     "tool": tool_name, **(annotations or {})},
    )


async def respond(
    prompt: str,
    relay: PermissionRelay,
    workspace: Path,
    *,
    cli_path: str | Path,
) -> dict:
    """One user prompt in, Claude's response out, as a transcript entry.

    ``cli_path`` is required so the Agent SDK executes the exact binary whose
    authentication was gated.  Letting the SDK choose its bundled runtime
    would break that evidence binding.
    """
    workspace.mkdir(parents=True, exist_ok=True)  # the SDK requires cwd to exist
    loop = asyncio.get_running_loop()

    async def can_use_tool(tool_name, tool_input, context):
        # Governance 0002 "once, verbatim" (M1 audit finding 1): the native
        # request is MORE than tool name + input — the SDK delivers the
        # native UI fields (title, description, blocked path, decision
        # reason, suggestions). All of it goes onto the card and into the
        # raw stash; runtime identifiers are hashed for tracked records.
        native_context = {
            "title": context.title,
            "display_name": context.display_name,
            "description": context.description,
            "blocked_path": context.blocked_path,
            "decision_reason": context.decision_reason,
            "suggestions": [s.to_dict() for s in (context.suggestions or [])],
            # raw runtime identifiers belong in the verbatim payload (card +
            # git-ignored raw store); tracked records carry only hashes
            "tool_use_id": context.tool_use_id,
            "agent_id": context.agent_id,
        }
        req = _normalized(tool_name, dict(tool_input), kind="can_use_tool",
                          tool_use_id=context.tool_use_id or "", workspace=workspace,
                          payload_extra={"native_context": native_context},
                          annotations={"agent_id_sha256": sha256_text(context.agent_id)}
                          if context.agent_id else None)
        # The presenter blocks on Live's terminal input; run it off-loop so
        # the SDK's message pump stays alive while the card is up. Relay
        # integrity errors propagate and fail the turn — the wire must not
        # be answered as if decided.
        decision, reason = await loop.run_in_executor(None, relay.relay, req)
        if decision == "allow":
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"Denied by Dialektikḗ relay: {reason}")

    async def post_tool_use(input_data, tool_use_id, context):
        resp = input_data.get("tool_response")
        relay.audit(_normalized(
            input_data.get("tool_name", ""), dict(input_data.get("tool_input") or {}),
            kind="hook:PostToolUse", tool_use_id=tool_use_id or "", workspace=workspace,
            annotations={"response_sha256": sha256_text(
                json.dumps(resp, sort_keys=True, default=str))},
        ), kind="tool_completed")
        return {}

    async def post_tool_use_failure(input_data, tool_use_id, context):
        error_text = str(input_data.get("error", ""))
        relay.audit(_normalized(
            input_data.get("tool_name", ""), dict(input_data.get("tool_input") or {}),
            kind="hook:PostToolUseFailure", tool_use_id=tool_use_id or "",
            workspace=workspace, payload_extra={"error": error_text},
            annotations={"error_sha256": sha256_text(error_text)},
        ), kind="tool_failed")
        return {}

    opts = ClaudeAgentOptions(
        cwd=str(workspace),
        cli_path=str(cli_path),
        can_use_tool=can_use_tool,
        hooks={"PostToolUse": [HookMatcher(hooks=[post_tool_use])],
               "PostToolUseFailure": [HookMatcher(hooks=[post_tool_use_failure])]},
    )

    text: list[str] = []
    tool_names: list[str] = []
    rate_events: list[dict] = []
    rate_limit_stop = None
    interrupt_attempted = False
    interrupt_succeeded = False
    interrupt_error = None
    model = None
    result: dict = {}
    async with ClaudeSDKClient(options=opts) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                model = model or msg.model
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_names.append(block.name)
            elif isinstance(msg, RateLimitEvent):
                info = msg.rate_limit_info
                rate_events.append({"status": info.status,
                                    "rate_limit_type": info.rate_limit_type,
                                    "utilization": info.utilization,
                                    "resets_at": info.resets_at,
                                    "overage_status": info.overage_status,
                                    "raw": info.raw})
                rate_limit_stop = rate_limit_stop or classify_rate_limit(info)
                if rate_limit_stop and not interrupt_attempted:
                    # Standing authorization: STOP — interrupt the turn now
                    # rather than letting it keep spending (audit R2 f.2).
                    interrupt_attempted = True
                    try:
                        await client.interrupt()
                    except Exception as exc:
                        # A failed interrupt must NOT leave us consuming an
                        # agentic turn (audit R3 f.1): break out of the
                        # stream — __aexit__ then closes the client.
                        interrupt_error = f"{type(exc).__name__}: {exc}"
                        break
                    else:
                        interrupt_succeeded = True
            elif isinstance(msg, ResultMessage):
                result = {"session_id": msg.session_id, "subtype": msg.subtype,
                          "is_error": bool(msg.is_error), "errors": msg.errors,
                          "num_turns": msg.num_turns, "result": msg.result}
    reply = "".join(text).strip() or (result.get("result") or "").strip()
    entry = {"provider": "claude", "text": reply, "model": model,
             "session_id_sha256": sha256_text(result.get("session_id") or ""),
             "num_turns": result.get("num_turns"),
             "tool_uses": tool_names,
             "rate_limit_events": rate_events,
             "rate_limit_stop": rate_limit_stop,
             # "interrupted" stays truthful (did the stop actually take?)
             "interrupted": interrupt_succeeded,
             "interrupt_attempted": interrupt_attempted,
             "interrupt_error": interrupt_error}
    # A plan-limit stop takes precedence over generic error handling: the
    # warning evidence must reach the transcript (audit R2 f.2) — an
    # interrupted or limit-rejected turn often reports is_error too.
    if rate_limit_stop:
        return entry
    if result.get("is_error"):
        raise RuntimeError(f"Claude turn failed (subtype={result.get('subtype')!r}, "
                           f"errors={result.get('errors')!r})")
    if not reply:
        raise RuntimeError("Claude turn produced no text response")
    return entry
