"""Claude Code Agent SDK adapter foundations for M2."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast, get_args

import claude_agent_sdk
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionMode,
    RateLimitEvent,
    ResultMessage,
    ServerToolUseBlock,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TextBlock,
    ToolUseBlock,
)

from core.broker import ChainedLog, canonical, sha256_text
from core.relay import (
    NormalizedRequest,
    PermissionRelay,
    Presenter,
    path_annotations,
)
from dialektike import gates
from dialektike.adapters.base import AdapterError, PlanUsageWarning, TurnInterrupted
from dialektike.adapters.capabilities import (
    CapabilityError,
    RuntimeGateError,
    claude_capabilities_from_server_info,
    validate_selection,
)
from dialektike.claude_leg import classify_rate_limit
from dialektike.domain import (
    AdapterCapabilities,
    CancellationSignal,
    ModelSelection,
    StructuredContentBlock,
    TurnRequest,
    TurnResult,
)
from dialektike.presenters.activity import RuntimeActivityBridge
from dialektike.workspaces import validate_project_workspace


CLAUDE_EPHEMERAL_ARGS: dict[str, str | None] = {
    "no-session-persistence": None,
}

_CLAUDE_POST_TOOL_HOOK_EVENTS = ("PostToolUse", "PostToolUseFailure")
_CLAUDE_PRE_COMPACT_HOOK_EVENT = "PreCompact"
CLAUDE_SDK_OPTION_AUTHORITY = (
    f"claude-agent-sdk {claude_agent_sdk.__version__} typed options"
)

# Modes whose installed-runtime semantics can resolve an execution decision
# before ``can_use_tool``.  Keep this coupled to the SDK's typed surface: the
# invariant suite fails when a pinned SDK adds or removes a mode rather than
# allowing the prose matrix to drift independently.
CLAUDE_TYPED_PERMISSION_MODES = frozenset(get_args(PermissionMode))
CLAUDE_CALLBACK_SHORT_CIRCUIT_PERMISSION_MODES = {
    "acceptEdits": "permission-mode.accept-edits",
    "auto": "permission-mode.auto",
    "bypassPermissions": "permission-mode.bypass-permissions",
    "dontAsk": "permission-mode.dont-ask",
}


@dataclass(frozen=True, slots=True)
class ClaudePermissionMechanism:
    """One installed-SDK path that can prevent ``can_use_tool`` from running.

    ``requested_observable`` describes whether Dialektikḗ can see the input
    that enables the mechanism.  It never implies that the runtime reported
    which rule actually matched.  The installed runtime exposes no complete
    effective permission-rule inventory, so every matrix row is deliberately
    ``effective_observable=False``.
    """

    mechanism_id: str
    sdk_surface: str
    callback_effect: str
    adapter_state: str
    requested_observable: bool
    effective_observable: bool
    sdk_warning_detects: bool


# Re-captured from the installed, project-pinned claude-agent-sdk 0.2.116
# contract (ClaudeAgentOptions, CanUseTool, PreToolUseHookSpecificOutput, and
# SandboxSettings).  This is intentionally broader than the SDK's advisory
# CanUseToolShadowedWarning, which does not inspect external settings/hooks or
# every permission mode.
CLAUDE_PERMISSION_MECHANISM_MATRIX = (
    ClaudePermissionMechanism(
        "permission-mode.accept-edits",
        "permission_mode=acceptEdits",
        "supported edit operations may auto-permit before can_use_tool",
        "selectable only through the reviewed edit-automatically profile",
        True,
        False,
        False,
    ),
    ClaudePermissionMechanism(
        "permission-mode.auto",
        "permission_mode=auto",
        "the native classifier may auto-permit or auto-deny before can_use_tool",
        "selectable only through the reviewed auto profile",
        True,
        False,
        False,
    ),
    ClaudePermissionMechanism(
        "permission-mode.dont-ask",
        "permission_mode=dontAsk",
        "calls not pre-approved by allow rules auto-deny before can_use_tool",
        "selectable only through the reviewed dont-ask profile",
        True,
        False,
        False,
    ),
    ClaudePermissionMechanism(
        "permission-mode.bypass-permissions",
        "permission_mode=bypassPermissions",
        "all calls except explicit denies bypass the callback",
        "unavailable without a separate ruling from Live",
        True,
        False,
        True,
    ),
    ClaudePermissionMechanism(
        "allowed-tools.whole-tool",
        "allowed_tools contains a whole-tool entry",
        "matching calls auto-permit before can_use_tool",
        "adapter SDK input is the empty list",
        True,
        False,
        True,
    ),
    ClaudePermissionMechanism(
        "skills.derived-whole-tool",
        "skills=all derives the whole-tool Skill allow",
        "Skill calls auto-permit before can_use_tool",
        "adapter SDK input is None; native skill discovery may still apply",
        True,
        False,
        True,
    ),
    ClaudePermissionMechanism(
        "settings.permissions-default-mode",
        "permissions.defaultMode in inherited settings",
        "the inherited mode may auto-permit or auto-deny before can_use_tool",
        "setting_sources=None inherits native sources",
        False,
        False,
        False,
    ),
    ClaudePermissionMechanism(
        "settings.permissions-allow",
        "permissions.allow in inherited settings",
        "matching calls auto-permit before can_use_tool",
        "setting_sources=None inherits native sources",
        False,
        False,
        False,
    ),
    ClaudePermissionMechanism(
        "settings.permissions-deny",
        "permissions.deny in inherited settings",
        "matching calls auto-deny before can_use_tool",
        "setting_sources=None inherits native sources",
        False,
        False,
        False,
    ),
    ClaudePermissionMechanism(
        "hooks.pre-tool-use-decision",
        "PreToolUse returns permissionDecision=allow or deny",
        "matching calls are resolved before can_use_tool",
        "adapter installs no PreToolUse hook; inherited hooks are not enumerable",
        False,
        False,
        False,
    ),
    ClaudePermissionMechanism(
        "sandbox.auto-allow-bash",
        "sandbox.autoAllowBashIfSandboxed=true",
        "sandboxed Bash calls may auto-permit",
        "adapter SDK input is None; inherited sandbox settings may still apply",
        False,
        False,
        False,
    ),
)


def _control_map(values) -> dict[str, object]:
    return {item.control_id: item.value for item in values}


def _claude_requested_options(request: TurnRequest) -> dict[str, Any]:
    """Translate only descriptor-validated controls into SDK options.

    The registered-provider facade validates the profile before this adapter
    runs. Keeping the mapping here ensures provider wire semantics never leak
    into shared orchestration or the frontend.
    """

    turn_controls = _control_map(
        request.participant.model_profile.requested.controls
    )
    profile = request.participant.execution_profile
    execution = _control_map(profile.values)
    thinking_value = turn_controls.get("thinking")
    thinking: dict[str, object] | None
    if thinking_value == "adaptive":
        thinking = {"type": "adaptive"}
    elif thinking_value == "disabled":
        thinking = {"type": "disabled"}
    elif thinking_value is None:
        thinking = None
    else:
        raise AdapterError(f"unsupported Claude thinking control {thinking_value!r}")

    permission_mode = execution.get("permission-mode")
    if permission_mode is not None and permission_mode not in {
        "default",
        "acceptEdits",
        "plan",
        "auto",
        "dontAsk",
    }:
        raise AdapterError(
            f"unsupported governed Claude permission mode {permission_mode!r}"
        )
    setting_sources = execution.get("setting-sources")
    if setting_sources not in {None, "native-default"}:
        raise AdapterError(
            "isolated Claude settings require a separate Live ruling"
        )
    return {
        "thinking": thinking,
        "permission_mode": permission_mode,
        # Explicitly retain governance 0003's inherit-native default. The SDK
        # cannot enumerate which external rules ultimately matched.
        "setting_sources": None,
        "execution_profile": profile.profile_id,
    }


def _claude_sdk_options(
    *,
    workspace: Path,
    cli_path: Path,
    requested: ModelSelection,
    requested_options: Mapping[str, Any],
    can_use_tool: Any,
    hooks: dict[str, list[HookMatcher]],
) -> ClaudeAgentOptions:
    """Construct the one schema-pinned SDK options object used for a turn."""

    return ClaudeAgentOptions(
        cwd=str(workspace),
        cli_path=str(cli_path),
        model=requested.model_id,
        effort=requested.effort,
        thinking=requested_options["thinking"],
        permission_mode=requested_options["permission_mode"],
        setting_sources=requested_options["setting_sources"],
        # Keep the SDK inputs explicit so the safety attestation can record the
        # exact adapter override.  Empty/None does not claim that inherited
        # native settings lack allow rules, skills, or sandbox configuration.
        allowed_tools=[],
        skills=None,
        sandbox=None,
        # Dialektikḗ owns the durable topic history. A provider-native
        # transcript would create a second, divergent source of truth.
        extra_args=dict(CLAUDE_EPHEMERAL_ARGS),
        can_use_tool=can_use_tool,
        hooks=hooks,
    )


def _claude_sdk_option_snapshot(options: ClaudeAgentOptions) -> dict[str, Any]:
    """Return JSON-safe turn/permission SDK inputs without inferring native state."""

    hook_events = tuple(sorted((options.hooks or {}).keys()))
    return {
        "snapshot_scope": "turn-and-permission-options",
        "model": options.model,
        "effort": options.effort,
        "thinking": options.thinking,
        "permission_mode": options.permission_mode,
        "setting_sources": options.setting_sources,
        "allowed_tools": list(options.allowed_tools),
        "skills": options.skills,
        "sandbox": options.sandbox,
        "can_use_tool_installed": options.can_use_tool is not None,
        "pre_tool_use_hooks": [
            event for event in hook_events if event == "PreToolUse"
        ],
        "pre_compact_hooks": [
            event
            for event in hook_events
            if event == _CLAUDE_PRE_COMPACT_HOOK_EVENT
        ],
        "post_tool_use_hooks": [
            event for event in hook_events if event in _CLAUDE_POST_TOOL_HOOK_EVENTS
        ],
    }


def _render_claude_reply(
    text_parts: list[str], result_text: object = ""
) -> str:
    """Preserve provider TextBlock boundaries as Markdown block boundaries."""

    return "\n\n".join(text_parts) if text_parts else str(result_text or "")


def _append_redacted_capture(path: Path, record: dict) -> None:
    """Append one credential-free SDK observation at owner-only mode 0600."""

    encoded = (
        json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        + "\n"
    ).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    path.chmod(0o600)


def _redacted_rate_capture(info_item) -> dict:
    """Keep rate-limit semantics while replacing opaque native data by hash."""

    return {
        "type": "rate_limit",
        "status": info_item.status,
        "rate_limit_type": info_item.rate_limit_type,
        "utilization": info_item.utilization,
        "resets_at": info_item.resets_at,
        "overage_status": info_item.overage_status,
        "raw_sha256": sha256_text(
            json.dumps(info_item.raw, sort_keys=True, default=str)
        ),
    }


def claude_cli_version(path: Path) -> str:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CapabilityError(f"Claude Code version probe failed: {exc}") from exc
    if result.returncode != 0:
        raise CapabilityError(
            f"Claude Code version probe exited {result.returncode}"
        )
    version = result.stdout.strip().split()[0] if result.stdout.strip() else ""
    if not version:
        raise CapabilityError("Claude Code version probe returned no version")
    return version


def gated_claude_runtime() -> tuple[Path, dict, str]:
    """Resolve and gate the exact executable used by every SDK operation.

    Do not execute the PyInstaller-extracted copy of the SDK bundle: macOS
    Keychain authentication is tied to the installed Claude Code runtime.
    Finder-safe resolution locates that installed binary without relying on
    the GUI process's minimal PATH; ``cli_path`` then binds the SDK to the
    very same path whose auth evidence was accepted.
    """

    auth = gates.assert_claude_subscription()
    path = Path(str(auth["executable"])).resolve(strict=True)
    return path, auth, claude_cli_version(path)


async def discover_claude_capabilities() -> AdapterCapabilities:
    """Discover the live SDK catalog without submitting a prompt."""

    try:
        cli_path, auth, runtime_version = await asyncio.to_thread(
            gated_claude_runtime
        )
    except SystemExit as exc:
        raise RuntimeGateError(str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="dialektike-claude-discovery-") as temp:
        options = ClaudeAgentOptions(cwd=temp, cli_path=str(cli_path))
        async with ClaudeSDKClient(options=options) as client:
            info = await client.get_server_info()
    if not isinstance(info, dict):
        raise CapabilityError("Claude Agent SDK returned no server initialization info")
    subscription = str(auth.get("subscription_type") or "unknown").casefold()
    route = (
        f"claude.ai:{auth.get('api_provider') or 'unknown'}:"
        f"{subscription}"
    )
    return claude_capabilities_from_server_info(
        info,
        runtime_version=(
            f"claude-agent-sdk {claude_agent_sdk.__version__} / "
            f"claude-code {runtime_version}"
        ),
        account_route=route,
    )


class ClaudeCodeRuntimeAdapter:
    """Live Claude Agent SDK adapter with one fresh client per role-bound turn."""

    adapter_id = "claude-code"
    relay_provider_id = "claude"

    def __init__(
        self,
        presenter: Presenter,
        activity_bridge: RuntimeActivityBridge | None = None,
    ):
        self.presenter = presenter
        self.activity_bridge = activity_bridge
        self._active_client: ClaudeSDKClient | None = None
        self._interrupt_lock = asyncio.Lock()
        self._interrupt_sent = False

    async def discover_capabilities(self) -> AdapterCapabilities:
        return await discover_claude_capabilities()

    async def _interrupt_once(self) -> None:
        async with self._interrupt_lock:
            client = self._active_client
            if client is None or self._interrupt_sent:
                return
            self._interrupt_sent = True
            try:
                await client.interrupt()
            except BaseException:
                # A failed interrupt must not leave a subscription turn
                # consuming in the background. Disconnect is the native
                # transport-close fallback; preserve the original fault.
                try:
                    await client.disconnect()
                except BaseException:
                    pass
                raise

    async def run_turn(
        self, request: TurnRequest, cancellation: CancellationSignal
    ) -> TurnResult:
        try:
            cli_path, auth, runtime_version = await asyncio.to_thread(
                gated_claude_runtime
            )
        except SystemExit as exc:
            raise RuntimeGateError(str(exc)) from exc
        except CapabilityError as exc:
            raise AdapterError(str(exc)) from exc

        if cancellation.cancelled:
            raise TurnInterrupted(
                cancellation.reason or "Claude turn stopped before provider entry"
            )

        workspace = Path(request.paths.workspace_dir)
        raw_dir = Path(request.paths.raw_dir)
        if request.paths.workspace_source == "project":
            workspace = validate_project_workspace(
                workspace,
                expected_identity=request.paths.workspace_identity,
            )
        else:
            workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        capture_path = raw_dir / "claude_events.redacted.jsonl"
        log = ChainedLog(Path(request.paths.decisions_path))
        relay = PermissionRelay(log=log, presenter=self.presenter, raw_dir=raw_dir)
        requested = request.participant.model_profile.requested
        requested_options = _claude_requested_options(request)
        model_label = (
            f"claude-code ({requested.model_id or 'native default'}"
            f"/{requested.effort or 'native effort'})"
        )

        def normalized(
            tool_name: str,
            tool_input: dict,
            kind: str,
            tool_use_id: str,
            *,
            payload_extra: dict | None = None,
            annotations: dict | None = None,
        ) -> NormalizedRequest:
            if not tool_use_id:
                raise AdapterError(
                    f"{kind}: Claude supplied no tool_use_id; cannot relay exactly once"
                )
            return NormalizedRequest(
                provider=self.relay_provider_id,
                case=request.run_id,
                phase=f"round-{request.round_number}-turn-{request.turn_number}",
                model=model_label,
                role=request.role.value,
                kind=kind,
                payload={
                    "tool": tool_name,
                    "input": dict(tool_input),
                    **(payload_extra or {}),
                },
                correlation_id=sha256_text(tool_use_id),
                annotations={
                    **path_annotations(dict(tool_input), workspace),
                    "tool": tool_name,
                    **(annotations or {}),
                },
            )

        loop = asyncio.get_running_loop()
        relayed_tool_decisions: dict[str, str] = {}
        native_compaction_events: list[dict[str, Any]] = []

        def tool_decision_provenance(correlation_id: str) -> str:
            decision = relayed_tool_decisions.get(correlation_id)
            if decision == "allow":
                return "relayed_approval"
            if decision == "deny":
                return "relayed_denial"
            return "native_auto"

        async def can_use_tool(tool_name, tool_input, context):
            native_context = {
                "title": context.title,
                "display_name": context.display_name,
                "description": context.description,
                "blocked_path": context.blocked_path,
                "decision_reason": context.decision_reason,
                "suggestions": [
                    suggestion.to_dict()
                    for suggestion in (context.suggestions or [])
                ],
                "tool_use_id": context.tool_use_id,
                "agent_id": context.agent_id,
            }
            native = normalized(
                tool_name,
                dict(tool_input),
                "can_use_tool",
                context.tool_use_id or "",
                payload_extra={"native_context": native_context},
                annotations=(
                    {"agent_id_sha256": sha256_text(context.agent_id)}
                    if context.agent_id
                    else None
                ),
            )
            decision, reason = await loop.run_in_executor(None, relay.relay, native)
            relayed_tool_decisions[native.correlation_id] = decision
            if decision == "allow":
                return PermissionResultAllow()
            return PermissionResultDeny(
                message=f"Denied by Dialektikḗ relay: {reason}"
            )

        async def post_tool_use(input_data, tool_use_id, context):
            response = input_data.get("tool_response")
            correlation_id = sha256_text(tool_use_id or "")
            relayed_decision = relayed_tool_decisions.get(correlation_id)
            relay.audit(
                normalized(
                    input_data.get("tool_name", ""),
                    dict(input_data.get("tool_input") or {}),
                    "hook:PostToolUse",
                    tool_use_id or "",
                    annotations={
                        "response_sha256": sha256_text(
                            json.dumps(response, sort_keys=True, default=str)
                        ),
                        "decision_provenance": tool_decision_provenance(
                            correlation_id
                        ),
                    },
                ),
                kind=(
                    "tool_completed"
                    if relayed_decision is not None
                    else "native_auto_permitted"
                ),
            )
            return {}

        async def post_tool_use_failure(input_data, tool_use_id, context):
            error_text = str(input_data.get("error", ""))
            correlation_id = sha256_text(tool_use_id or "")
            relay.audit(
                normalized(
                    input_data.get("tool_name", ""),
                    dict(input_data.get("tool_input") or {}),
                    "hook:PostToolUseFailure",
                    tool_use_id or "",
                    payload_extra={"error": error_text},
                    annotations={
                        "error_sha256": sha256_text(error_text),
                        "decision_provenance": tool_decision_provenance(
                            correlation_id
                        ),
                    },
                ),
                kind="tool_failed",
            )
            return {}

        async def pre_compact(input_data, tool_use_id, context):
            """Observe native Claude compaction without changing topic context.

            ``PreCompact`` exposes provider-session activity only. Dialektikḗ's
            durable, review-gated topic checkpoints remain a separate authority.
            Opaque SDK identifiers and authored compact instructions are retained
            only as hashes in the owner-only redacted capture.
            """

            raw_trigger = input_data.get("trigger")
            trigger = raw_trigger if raw_trigger in {"auto", "manual"} else "unknown"
            custom_instructions = input_data.get("custom_instructions")
            event = {
                "type": "native_compaction_observed",
                "hook_event": _CLAUDE_PRE_COMPACT_HOOK_EVENT,
                "trigger": trigger,
                "session_id_sha256": sha256_text(
                    str(input_data.get("session_id") or "")
                ),
                "transcript_path_sha256": sha256_text(
                    str(input_data.get("transcript_path") or "")
                ),
                "cwd_sha256": sha256_text(str(input_data.get("cwd") or "")),
                "custom_instructions_present": custom_instructions is not None,
                "custom_instructions_sha256": (
                    sha256_text(str(custom_instructions))
                    if custom_instructions is not None
                    else None
                ),
                "topic_checkpoint_mutated": False,
            }
            native_compaction_events.append(event)
            _append_redacted_capture(capture_path, event)
            return {}

        options = _claude_sdk_options(
            workspace=workspace,
            cli_path=cli_path,
            requested=requested,
            requested_options=requested_options,
            can_use_tool=can_use_tool,
            hooks={
                _CLAUDE_PRE_COMPACT_HOOK_EVENT: [
                    HookMatcher(hooks=[pre_compact])
                ],
                "PostToolUse": [HookMatcher(hooks=[post_tool_use])],
                "PostToolUseFailure": [
                    HookMatcher(hooks=[post_tool_use_failure])
                ],
            },
        )
        sdk_option_snapshot = _claude_sdk_option_snapshot(options)
        _append_redacted_capture(
            capture_path,
            {
                "type": "capture_started",
                "runtime_id": self.adapter_id,
                "requested_model": requested.model_id,
                "requested_effort": requested.effort,
                "service_tier": requested.service_tier,
                "execution_profile": requested_options["execution_profile"],
                # Retained for readers of the original capture shape; these
                # are requested values, never effective-runtime claims.
                "thinking": requested_options["thinking"],
                "permission_mode": requested_options["permission_mode"],
                "setting_sources": "native-default (None)",
                "sdk_options_requested": sdk_option_snapshot,
                "sdk_options_authority": CLAUDE_SDK_OPTION_AUTHORITY,
                "effort_effective_observable": False,
                "thinking_effective_observable": False,
                "permission_mode_effective_observable": False,
                "execution_profile_effective_observable": False,
                # These describe effective native state, not the explicit SDK
                # inputs above. The runtime exposes no complete inventory.
                "external_allow_rules_observable": False,
                "external_pre_tool_use_hooks_observable": False,
                "external_sandbox_rules_observable": False,
            },
        )

        text_parts: list[str] = []
        tool_names: list[str] = []
        rate_events: list[dict] = []
        rate_stop: str | None = None
        result_message: dict = {}
        effective_model: str | None = None
        interrupt_error: str | None = None
        stream_failure: Exception | None = None
        self._interrupt_sent = False

        async def captured_response(messages):
            """Retain provider text when the response iterator later fails."""

            nonlocal stream_failure
            try:
                async for message in messages:
                    yield message
            except Exception as exc:
                stream_failure = exc

        async def watch_cancellation() -> None:
            nonlocal interrupt_error
            await cancellation.wait()
            try:
                # Use the public fail-closed path so a provider callback
                # waiting on Live's permission card is released before the
                # native interrupt is attempted.
                await self.interrupt()
            except Exception as exc:
                interrupt_error = f"{type(exc).__name__}: {exc}"

        watcher: asyncio.Task | None = None
        capabilities: AdapterCapabilities | None = None
        async with ClaudeSDKClient(options=options) as client:
            self._active_client = client
            watcher = asyncio.create_task(watch_cancellation())
            try:
                info = await client.get_server_info()
                if not isinstance(info, dict):
                    raise AdapterError(
                        "Claude SDK returned no initialization capability catalog"
                    )
                subscription = str(
                    auth.get("subscription_type") or "unknown"
                ).casefold()
                account_route = (
                    f"claude.ai:{auth.get('api_provider') or 'unknown'}:"
                    f"{subscription}"
                )
                capabilities = claude_capabilities_from_server_info(
                    info,
                    runtime_version=(
                        f"claude-agent-sdk {claude_agent_sdk.__version__} / "
                        f"claude-code {runtime_version}"
                    ),
                    account_route=account_route,
                )
                _append_redacted_capture(
                    capture_path,
                    {
                        "type": "runtime_initialized",
                        "account_route": account_route,
                        "runtime_version": capabilities.runtime_version,
                    },
                )
                capability = validate_selection(capabilities, requested)
                # ``query`` is Claude's model-turn boundary. Cancellation can
                # arrive while the runtime/auth/catalog gates are running, so
                # check again at the last possible point before submission.
                if cancellation.cancelled:
                    raise TurnInterrupted(
                        cancellation.reason
                        or "Claude turn stopped before query submission"
                    )
                await client.query(request.input_text)
                async for message in captured_response(
                    client.receive_response()
                ):
                    if isinstance(message, AssistantMessage):
                        if (
                            effective_model is not None
                            and message.model != effective_model
                        ):
                            raise AdapterError(
                                "Claude changed effective model within one turn: "
                                f"{effective_model!r} -> {message.model!r}"
                            )
                        effective_model = effective_model or message.model
                        message_text: list[str] = []
                        message_tools: list[str] = []
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                text_parts.append(block.text)
                                message_text.append(block.text)
                            elif isinstance(block, ToolUseBlock):
                                tool_names.append(block.name)
                                message_tools.append(block.name)
                                if self.activity_bridge is not None:
                                    self.activity_bridge.publish(
                                        request,
                                        f"Using {block.name}",
                                        activity="tool-started",
                                    )
                            elif isinstance(block, ServerToolUseBlock):
                                tool_names.append(block.name)
                                message_tools.append(block.name)
                                if self.activity_bridge is not None:
                                    self.activity_bridge.publish(
                                        request,
                                        f"Using {block.name}",
                                        activity="tool-started",
                                    )
                        _append_redacted_capture(
                            capture_path,
                            {
                                "type": "assistant",
                                "model": message.model,
                                "text_blocks": message_text,
                                "tool_names": message_tools,
                            },
                        )
                        if (
                            self.activity_bridge is not None
                            and message_tools
                            and message_text
                        ):
                            # Text accompanying a native tool call is the
                            # provider-visible preamble/progress narration,
                            # not a hidden ThinkingBlock.
                            self.activity_bridge.publish(
                                request,
                                "\n\n".join(message_text),
                                activity="assistant-commentary",
                            )
                    elif isinstance(message, RateLimitEvent):
                        info_item = message.rate_limit_info
                        rate_events.append(
                            {
                                "status": info_item.status,
                                "rate_limit_type": info_item.rate_limit_type,
                                "utilization": info_item.utilization,
                                "resets_at": info_item.resets_at,
                                "overage_status": info_item.overage_status,
                                "raw": info_item.raw,
                            }
                        )
                        _append_redacted_capture(
                            capture_path,
                            _redacted_rate_capture(info_item),
                        )
                        rate_stop = rate_stop or classify_rate_limit(info_item)
                        if rate_stop:
                            try:
                                await self.interrupt()
                            except Exception as exc:
                                interrupt_error = f"{type(exc).__name__}: {exc}"
                                break
                    elif isinstance(message, TaskStartedMessage):
                        if self.activity_bridge is not None:
                            self.activity_bridge.publish(
                                request,
                                message.description,
                                activity="task-started",
                            )
                    elif isinstance(message, TaskProgressMessage):
                        if self.activity_bridge is not None:
                            self.activity_bridge.publish(
                                request,
                                message.description,
                                activity="task-progress",
                            )
                    elif isinstance(message, TaskNotificationMessage):
                        if self.activity_bridge is not None:
                            self.activity_bridge.publish(
                                request,
                                message.summary or message.status,
                                activity="task-finished",
                                state=(
                                    "completed"
                                    if message.status == "completed"
                                    else "failed"
                                ),
                            )
                    elif isinstance(message, ResultMessage):
                        result_message = {
                            "session_id": message.session_id,
                            "subtype": message.subtype,
                            "is_error": bool(message.is_error),
                            "errors": message.errors,
                            "num_turns": message.num_turns,
                            "result": message.result,
                        }
                        _append_redacted_capture(
                            capture_path,
                            {
                                "type": "result",
                                "session_id_sha256": sha256_text(
                                    str(message.session_id or "")
                                ),
                                "subtype": message.subtype,
                                "is_error": bool(message.is_error),
                                "error_count": len(message.errors or ()),
                                "errors_sha256": sha256_text(
                                    json.dumps(
                                        message.errors,
                                        sort_keys=True,
                                        default=str,
                                    )
                                ),
                                "num_turns": message.num_turns,
                                "result_text": str(message.result or ""),
                            },
                        )
            finally:
                if watcher is not None:
                    watcher.cancel()
                    try:
                        await watcher
                    except asyncio.CancelledError:
                        pass
                self._active_client = None

        # TextBlock boundaries are semantic Markdown boundaries.  Concatenating
        # them without whitespace can collapse a heading/list/code fence into
        # the preceding block, so preserve them as separate paragraphs just as
        # the provider application does.
        reply = _render_claude_reply(
            text_parts,
            result_message.get("result"),
        )
        capability = (
            validate_selection(capabilities, requested)
            if capabilities is not None
            else None
        )
        if effective_model is not None and capability is not None \
                and capability.resolved_model_id is not None \
                and effective_model != capability.resolved_model_id:
            raise AdapterError(
                f"Claude AssistantMessage echoed model {effective_model!r}, "
                f"catalog resolved {capability.resolved_model_id!r}"
            )
        profile = None
        if effective_model is not None:
            profile = request.participant.model_profile.resolved(
                ModelSelection(
                    model_id=effective_model,
                    # Claude's AssistantMessage certifies the model only. The
                    # SDK accepts effort/thinking inputs but the runtime does
                    # not echo their effective values, so never promote the
                    # request into the effective profile.
                    effort=None,
                    service_tier=None,
                    features=(),
                    controls=(),
                ),
                (
                    "model: Claude AssistantMessage echo; "
                    "effort, thinking, and service tier: not observable"
                ),
            )
        turn_result = None
        if reply and profile is not None and capabilities is not None:
            blocks = (StructuredContentBlock.markdown(reply),)
            turn_result = TurnResult(
                text=reply,
                blocks=blocks,
                model_profile=profile,
                account_route=capabilities.account_route or "",
                runtime_version=capabilities.runtime_version,
                evidence=(
                    (
                        "session_id_sha256",
                        sha256_text(str(result_message.get("session_id") or "")),
                    ),
                    ("tool_use_count", str(len(tool_names))),
                    ("rate_limit_event_count", str(len(rate_events))),
                    (
                        "native_compaction_event_count",
                        str(len(native_compaction_events)),
                    ),
                    (
                        "native_compaction_triggers",
                        canonical(
                            [event["trigger"] for event in native_compaction_events]
                        ),
                    ),
                    (
                        "native_compaction_authority",
                        f"{CLAUDE_SDK_OPTION_AUTHORITY} PreCompact hook; observation only",
                    ),
                    (
                        "effort_authority",
                        "requested via catalog-validated SDK option; effective value not observable",
                    ),
                    (
                        "effort_requested",
                        str(requested.effort or "native-default"),
                    ),
                    (
                        "effort_effective_observable",
                        "false",
                    ),
                    (
                        "thinking_requested",
                        canonical(requested_options["thinking"]),
                    ),
                    (
                        "thinking_effective_observable",
                        "false",
                    ),
                    (
                        "execution_profile_requested",
                        str(requested_options["execution_profile"]),
                    ),
                    (
                        "execution_profile_effective_observable",
                        "false",
                    ),
                    (
                        "permission_mode_requested",
                        str(requested_options["permission_mode"] or "native-default"),
                    ),
                    (
                        "permission_mode_effective_observable",
                        "false",
                    ),
                    (
                        "setting_sources_requested",
                        "native default (None)",
                    ),
                    (
                        "sdk_options_requested",
                        canonical(sdk_option_snapshot),
                    ),
                    (
                        "sdk_options_authority",
                        CLAUDE_SDK_OPTION_AUTHORITY,
                    ),
                    (
                        "external_allow_rules_observable",
                        "false",
                    ),
                    (
                        "external_pre_tool_use_hooks_observable",
                        "false",
                    ),
                    (
                        "external_sandbox_rules_observable",
                        "false",
                    ),
                ),
            )
        if rate_stop is not None:
            detail = rate_stop
            if interrupt_error:
                detail += f"; interrupt failed: {interrupt_error}"
            raise PlanUsageWarning(detail, partial_result=turn_result)
        if cancellation.cancelled:
            reason = cancellation.reason or "Claude turn interrupted"
            if interrupt_error:
                reason += f"; interrupt failed and transport closed: {interrupt_error}"
            raise TurnInterrupted(
                reason,
                partial_result=turn_result,
            )
        if not result_message and stream_failure is None:
            raise AdapterError(
                "Claude response stream ended without a terminal ResultMessage",
                partial_result=turn_result,
            )
        if result_message.get("is_error"):
            raise AdapterError(
                "Claude turn failed "
                f"(subtype={result_message.get('subtype')!r}, "
                f"errors={result_message.get('errors')!r})",
                partial_result=turn_result,
            )
        if stream_failure is not None:
            detail = f"{type(stream_failure).__name__}: {stream_failure}"
            raise AdapterError(detail, partial_result=turn_result) from stream_failure
        if turn_result is None:
            raise AdapterError(
                "Claude turn produced no text with authoritative model evidence"
            )
        return turn_result

    async def interrupt(self) -> None:
        fail_pending = getattr(self.presenter, "fail_pending", None)
        if callable(fail_pending):
            fail_pending("run stopped while permission card was open")
        await self._interrupt_once()

    async def close(self) -> None:
        if self._active_client is not None:
            await self.interrupt()
