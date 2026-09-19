"""Codex app-server adapter foundations for M2.

Capability discovery is a no-turn operation. The live turn implementation is
kept separate so the GUI can refresh its selector catalog without creating a
model session or consuming plan capacity.
"""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from core.broker import ChainedLog, sha256_text
from core.relay import NormalizedRequest, Presenter
from dialektike import gates
from dialektike.adapters.base import (
    AdapterError,
    PlanUsageWarning,
    TurnInterrupted,
    TurnTimedOut,
)
from dialektike.adapters.capabilities import (
    CapabilityError,
    RuntimeGateError,
    codex_capabilities_from_model_list,
    validate_selection,
)
from dialektike.codex_leg import (
    ALLOWED_MODEL_PROVIDERS,
    DEFAULT_TURN_TIMEOUT_POLICY,
    AppServerError,
    AppServerTurnInterrupted,
    AppServerTurnTimeout,
    AppServerClient,
    TurnTimeoutPolicy,
    _assert_chatgpt_account,
    _audit_items,
    _bound_items,
    _hashed_id_annotations,
    _handshake,
    _wait_for_turn_terminal,
)
from dialektike.domain import (
    AdapterCapabilities,
    CancellationSignal,
    ModelProfile,
    ModelSelection,
    Role,
    StructuredContentBlock,
    TurnRequest,
    TurnResult,
)
from dialektike.presenters.activity import RuntimeActivityBridge
from dialektike.workspaces import validate_project_workspace


CODEX_ACCOUNT_GATE_ABORT = (
    "ABORT: Codex did not positively certify a ChatGPT subscription account "
    "(fail closed)"
)
CODEX_RATE_GATE_ABORT = (
    "ABORT: Codex rate-limit evidence did not positively certify "
    "subscription-only execution (fail closed)"
)
CODEX_PROVIDER_GATE_ABORT = (
    "ABORT: Codex did not echo first-party model-provider evidence "
    "(fail closed)"
)

CODEX_COMPACTION_AUTHORITY = (
    "codex app-server v2 item/completed contextCompaction item; observation only"
)

def _render_codex_reply(text_parts: list[str]) -> str:
    """Join native message blocks without trimming authored whitespace."""

    return "\n\n".join(text_parts)


def _codex_compaction_evidence(
    client: AppServerClient,
    thread_id: str | None,
    turn_id: str | None,
) -> tuple[tuple[str, str], ...]:
    """Project current schema compaction items into bounded turn evidence.

    The provider thread is intentionally ephemeral, and observing one of these
    items never creates or activates a Dialektikḗ topic checkpoint.  Raw item
    notifications remain in the owner-only app-server capture.
    """

    count = 0
    if thread_id is not None and turn_id is not None:
        count = sum(
            item.get("type") == "contextCompaction"
            for item in _bound_items(client, thread_id, turn_id)
        )
    return (
        ("native_compaction_event_count", str(count)),
        ("native_compaction_authority", CODEX_COMPACTION_AUTHORITY),
        ("native_compaction_topic_checkpoint_mutated", "false"),
    )


def _catalog_rows(client: AppServerClient) -> list[dict]:
    rows: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict = {"includeHidden": True}
        if cursor is not None:
            params["cursor"] = cursor
        request_id = client.request("model/list", params)
        response = client.response_for(request_id)
        if "error" in response:
            raise CapabilityError(f"codex model/list failed: {response['error']}")
        result = response.get("result") or {}
        page = result.get("data") or []
        if not isinstance(page, list):
            raise CapabilityError("codex model/list data is not an array")
        rows.extend(item for item in page if isinstance(item, dict))
        next_cursor = result.get("nextCursor")
        if not next_cursor:
            return rows
        cursor = str(next_cursor)


def _subscription_rate_limits(
    client: AppServerClient,
    *,
    expected_plan_type: str,
) -> tuple[dict, bool, str | None]:
    """Read the authoritative pre-turn billing snapshot.

    Returns ``(snapshot, credit_spend_available, reached_type)``. Missing or
    internally inconsistent credit evidence fails closed; a caller may expose
    Fast only when ``credit_spend_available`` is false.
    """

    request_id = client.request("account/rateLimits/read", {})
    response = client.response_for(request_id)
    if "error" in response:
        raise CapabilityError(
            f"codex account/rateLimits/read failed: {response['error']}"
        )
    result = response.get("result") or {}
    snapshot = result.get("rateLimits")
    if not isinstance(snapshot, dict):
        raise CapabilityError(
            "codex account/rateLimits/read returned no rate-limit snapshot"
        )
    plan_type = str(snapshot.get("planType") or "").casefold()
    if not plan_type or plan_type != expected_plan_type:
        raise CapabilityError(
            "codex rate-limit plan type did not match the authenticated account"
        )
    credits = snapshot.get("credits")
    if not isinstance(credits, dict):
        raise CapabilityError(
            "codex rate-limit snapshot did not expose credit-spend state"
        )
    has_credits = credits.get("hasCredits")
    unlimited = credits.get("unlimited")
    if not isinstance(has_credits, bool) or not isinstance(unlimited, bool):
        raise CapabilityError(
            "codex rate-limit credit-spend flags were not boolean"
        )
    balance = credits.get("balance")
    positive_balance = False
    if balance is not None:
        try:
            positive_balance = Decimal(str(balance)) > 0
        except (InvalidOperation, ValueError):
            raise CapabilityError(
                "codex rate-limit credit balance was not numeric"
            ) from None
    credit_spend_available = has_credits or unlimited or positive_balance
    reached = snapshot.get("rateLimitReachedType")
    if reached is not None and not isinstance(reached, str):
        raise CapabilityError(
            "codex rate-limit reached type was malformed"
        )
    return snapshot, credit_spend_available, reached


def _certify_subscription_route(
    client: AppServerClient,
) -> tuple[dict, str, bool, str | None]:
    """Return authenticated subscription evidence or one public gate verdict."""

    try:
        account = _assert_chatgpt_account(client)
    except AppServerError as exc:
        raise RuntimeGateError(CODEX_ACCOUNT_GATE_ABORT) from exc
    plan_type = str(account.get("planType") or "unknown").casefold()
    try:
        _, credit_spend_available, reached = _subscription_rate_limits(
            client,
            expected_plan_type=plan_type,
        )
    except CapabilityError as exc:
        raise RuntimeGateError(CODEX_RATE_GATE_ABORT) from exc
    return account, plan_type, credit_spend_available, reached


def _discover_codex_capabilities_sync() -> AdapterCapabilities:
    try:
        gate = gates.assert_codex_version()
        version = gate["codex_version"]
    except SystemExit as exc:
        raise RuntimeGateError(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="dialektike-codex-discovery-") as temp:
        root = Path(temp)
        raw_dir = root / "raw"
        raw_dir.mkdir(mode=0o700)
        client = AppServerClient(
            ChainedLog(root / "decisions.jsonl"),
            raw_dir,
            executable=gate["executable"],
        )
        try:
            _handshake(client)
            (
                _account,
                plan_type,
                credit_spend_available,
                reached,
            ) = _certify_subscription_route(client)
            rows = _catalog_rows(client)
        finally:
            client.close()
    return codex_capabilities_from_model_list(
        rows,
        runtime_version=version,
        account_route=f"chatgpt:{plan_type}",
        priority_within_subscription=(
            not credit_spend_available and reached is None
        ),
    )


async def discover_codex_capabilities() -> AdapterCapabilities:
    """Discover Codex capabilities without starting a model turn."""

    return await asyncio.to_thread(_discover_codex_capabilities_sync)


class _M2AppServerClient(AppServerClient):
    """M1 wire client with run-scoped identity and a GUI presenter."""

    def __init__(
        self,
        log: ChainedLog,
        raw_dir: Path,
        *,
        turn_request: TurnRequest,
        presenter: Presenter,
        activity_bridge: RuntimeActivityBridge | None,
        relay_provider_id: str,
        executable: str,
    ) -> None:
        self._m2_request = turn_request
        self._m2_presenter = presenter
        self._m2_activity_bridge = activity_bridge
        self._relay_provider_id = relay_provider_id
        super().__init__(log, raw_dir, executable=executable)

    def _publish_activity(
        self,
        message: str,
        *,
        activity: str,
        state: str = "running",
    ) -> None:
        if self._m2_activity_bridge is not None:
            self._m2_activity_bridge.publish(
                self._m2_request,
                message,
                activity=activity,
                state=state,
            )

    def _handle(self, msg: dict) -> None:
        """Retain M1 wire handling and surface only native-visible activity."""

        super()._handle(msg)
        method = msg.get("method", "")
        params = msg.get("params", {}) or {}
        if method == "turn/plan/updated":
            plan = params.get("plan") or []
            active = next(
                (
                    step
                    for step in plan
                    if isinstance(step, dict)
                    and step.get("status") == "inProgress"
                ),
                None,
            )
            if active and active.get("step"):
                self._publish_activity(
                    str(active["step"]),
                    activity="plan-step",
                )
        elif method == "item/started":
            item = params.get("item") or {}
            item_type = str(item.get("type") or "")
            labels = {
                "commandExecution": "Running a command",
                "fileChange": "Preparing file changes",
                "mcpToolCall": "Using an MCP tool",
                "dynamicToolCall": "Using a tool",
                "webSearch": "Searching the web",
                "imageView": "Inspecting an image",
            }
            label = labels.get(item_type)
            if label:
                self._publish_activity(label, activity="item-started")
        elif method == "item/completed":
            item = params.get("item") or {}
            item_type = str(item.get("type") or "")
            if item_type == "reasoning":
                summary = item.get("summary") or []
                if isinstance(summary, list):
                    visible = "\n".join(
                        str(part) for part in summary if str(part).strip()
                    )
                    if visible:
                        self._publish_activity(
                            visible,
                            activity="reasoning-summary",
                        )
            elif (
                item_type == "agentMessage"
                and item.get("phase") == "commentary"
                and item.get("text")
            ):
                self._publish_activity(
                    str(item["text"]),
                    activity="assistant-commentary",
                )

    def _present(self, request, card):
        self._begin_relay_pause()
        try:
            return self._m2_presenter(request, card)
        finally:
            self._end_relay_pause()

    def decision_recorded(self, request, decision) -> None:
        callback = getattr(self._m2_presenter, "decision_recorded", None)
        if callable(callback):
            callback(request, decision)

    def decision_record_failed(self, request, decision) -> None:
        callback = getattr(
            self._m2_presenter, "decision_record_failed", None
        )
        if callable(callback):
            callback(request, decision)

    def _normalized(
        self, method: str, params: dict, correlation: str
    ) -> NormalizedRequest:
        request = self._m2_request
        return NormalizedRequest(
            provider=self._relay_provider_id,
            case=request.run_id,
            phase=f"round-{request.round_number}-turn-{request.turn_number}",
            model=self.model_label,
            role=request.role.value,
            kind=method,
            payload=dict(params),
            correlation_id=correlation,
            annotations=_hashed_id_annotations(params),
        )


def _start_selected_thread(
    client: _M2AppServerClient,
    request: TurnRequest,
    selected_model: str,
    service_tier: str | None,
) -> tuple[str, dict]:
    params: dict[str, Any] = {
        "cwd": request.paths.workspace_dir,
        "model": selected_model,
        # Dialektikḗ is the canonical topic/session store.  The app-server
        # thread remains intentionally ephemeral so Dialektikḗ conversations
        # do not also appear as independently resumable Codex app tasks.
        "ephemeral": True,
        # M2 explicit selections must never fall back silently.
        "allowProviderModelFallback": False,
    }
    if service_tier is not None:
        params["serviceTier"] = service_tier
    request_id = client.request("thread/start", params)
    response = client.response_for(request_id)
    if "error" in response:
        raise AdapterError(f"codex thread/start failed: {response['error']}")
    result = response.get("result") or {}
    thread = result.get("thread") or {}
    thread_id = thread.get("id")
    if not thread_id:
        raise AdapterError("codex thread/start returned no thread id")
    if thread.get("ephemeral") is not True:
        raise AdapterError(
            "codex thread/start did not certify an ephemeral provider thread"
        )
    if result.get("modelProvider") not in ALLOWED_MODEL_PROVIDERS:
        raise RuntimeGateError(CODEX_PROVIDER_GATE_ABORT)
    if result.get("model") != selected_model:
        raise AdapterError(
            f"codex thread/start echoed model {result.get('model')!r}, "
            f"requested {selected_model!r}"
        )
    echoed_tier = result.get("serviceTier")
    if service_tier is not None and echoed_tier != service_tier:
        raise AdapterError(
            f"codex thread/start echoed service tier {echoed_tier!r}, "
            f"requested {service_tier!r}"
        )
    client.model_label = f"codex ({selected_model})"
    return str(thread_id), result


def _start_turn(
    client: _M2AppServerClient,
    *,
    thread_id: str,
    request: TurnRequest,
    effort: str | None,
    service_tier: str | None,
) -> str:
    params: dict[str, Any] = {
        "threadId": thread_id,
        "input": [{"type": "text", "text": request.input_text}],
    }
    if request.participant.model_profile.requested.model_id is not None:
        params["model"] = request.participant.model_profile.requested.model_id
    if effort is not None:
        params["effort"] = effort
    if service_tier is not None:
        params["serviceTier"] = service_tier
    request_id = client.request("turn/start", params)
    response = client.response_for(request_id)
    if "error" in response:
        raise AdapterError(f"codex turn/start failed: {response['error']}")
    turn_id = ((response.get("result") or {}).get("turn") or {}).get("id")
    if not turn_id:
        raise AdapterError("codex turn/start returned no turn id")
    return str(turn_id)


def _wait_for_turn(
    client: _M2AppServerClient,
    *,
    thread_id: str,
    turn_id: str,
    interrupt_requested: threading.Event,
    policy: TurnTimeoutPolicy = DEFAULT_TURN_TIMEOUT_POLICY,
    clock=time.monotonic,
) -> None:
    try:
        completed = _wait_for_turn_terminal(
            client,
            thread_id,
            turn_id,
            interrupt_requested=interrupt_requested,
            policy=policy,
            clock=clock,
        )
    except AppServerTurnTimeout as exc:
        raise TurnTimedOut(exc.kind, reason=str(exc)) from exc
    except AppServerTurnInterrupted as exc:
        raise TurnInterrupted(str(exc)) from exc
    except AppServerError as exc:
        raise AdapterError(str(exc)) from exc
    if completed.get("id") != turn_id:
        raise AdapterError(
            f"codex completed turn {completed.get('id')!r} != {turn_id!r}"
        )
    status = completed.get("status")
    if status != "completed":
        if interrupt_requested.is_set() and status == "interrupted":
            raise TurnInterrupted("codex turn interrupted by Live")
        raise AdapterError(f"codex turn status {status!r} is not completed")


def _start_and_wait_turn(
    client: _M2AppServerClient,
    *,
    thread_id: str,
    request: TurnRequest,
    effort: str | None,
    service_tier: str | None,
    interrupt_requested: threading.Event,
) -> str:
    """Compatibility wrapper; production retains the id before waiting."""

    turn_id = _start_turn(
        client,
        thread_id=thread_id,
        request=request,
        effort=effort,
        service_tier=service_tier,
    )
    _wait_for_turn(
        client,
        thread_id=thread_id,
        turn_id=turn_id,
        interrupt_requested=interrupt_requested,
    )
    return turn_id


class CodexRuntimeAdapter:
    """Live Codex provider adapter for one fresh app-server thread per turn."""

    adapter_id = "codex"
    relay_provider_id = "codex"

    def __init__(
        self,
        presenter: Presenter,
        activity_bridge: RuntimeActivityBridge | None = None,
    ):
        self.presenter = presenter
        self.activity_bridge = activity_bridge
        self._interrupt_requested = threading.Event()
        self._active_lock = threading.Lock()
        self._active_client: _M2AppServerClient | None = None

    async def discover_capabilities(self) -> AdapterCapabilities:
        return await discover_codex_capabilities()

    async def run_turn(
        self, request: TurnRequest, cancellation: CancellationSignal
    ) -> TurnResult:
        self._interrupt_requested.clear()

        if cancellation.cancelled:
            await self.interrupt()
            raise TurnInterrupted(
                cancellation.reason or "Codex turn stopped before provider entry"
            )

        async def watch_cancellation() -> None:
            await cancellation.wait()
            # Use the same fail-closed path as Live's Stop control. In
            # particular, wake a provider reader blocked on an open permission
            # card before requesting native interruption.
            await self.interrupt()

        watcher = asyncio.create_task(watch_cancellation())
        try:
            return await asyncio.to_thread(
                self._run_turn_sync,
                request,
                cancellation,
            )
        finally:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass

    def _run_turn_sync(
        self,
        request: TurnRequest,
        cancellation: CancellationSignal | None = None,
    ) -> TurnResult:
        try:
            gate = gates.assert_codex_version()
        except SystemExit as exc:
            raise RuntimeGateError(str(exc)) from exc
        raw_dir = Path(request.paths.raw_dir)
        workspace = Path(request.paths.workspace_dir)
        raw_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if request.paths.workspace_source == "project":
            workspace = validate_project_workspace(
                workspace,
                expected_identity=request.paths.workspace_identity,
            )
        else:
            workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        log = ChainedLog(Path(request.paths.decisions_path))
        client = _M2AppServerClient(
            log,
            raw_dir,
            turn_request=request,
            presenter=self.presenter,
            activity_bridge=self.activity_bridge,
            relay_provider_id=self.relay_provider_id,
            executable=gate["executable"],
        )
        with self._active_lock:
            self._active_client = client

        account: dict = {}
        thread: dict = {}
        thread_id: str | None = None
        turn_id: str | None = None
        text = ""
        text_parts: list[str] = []
        credit_spend_available: bool | None = None
        primary: BaseException | None = None
        try:
            _handshake(client)
            (
                account,
                plan_type,
                credit_spend_available,
                reached,
            ) = _certify_subscription_route(client)
            if reached is not None:
                raise PlanUsageWarning(
                    f"codex plan limit reached ({reached})"
                )
            rows = _catalog_rows(client)
            capabilities = codex_capabilities_from_model_list(
                rows,
                runtime_version=gates.REQUIRED_CODEX_VERSION,
                account_route=f"chatgpt:{plan_type}",
                # A positive balance is an optional post-limit facility on a
                # Plus account, not evidence that this pre-limit turn will use
                # it.  Keep ordinary/native turns available while preserving
                # the existing conservative policy that hides Fast whenever
                # purchased-credit spillover is possible.
                priority_within_subscription=(
                    not credit_spend_available and reached is None
                ),
            )
            requested = request.participant.model_profile.requested
            capability = validate_selection(capabilities, requested)
            if self._interrupt_requested.is_set() or (
                cancellation is not None and cancellation.cancelled
            ):
                raise TurnInterrupted(
                    (
                        cancellation.reason
                        if cancellation is not None
                        else None
                    )
                    or "Codex turn stopped before provider thread creation"
                )
            thread_id, thread = _start_selected_thread(
                client,
                request,
                capability.model_id,
                requested.service_tier,
            )
            # ``turn/start`` is the billable boundary. Recheck after every
            # preflight/catalog/thread operation so a concurrent stop or plan
            # warning cannot launch one last provider turn.
            if self._interrupt_requested.is_set() or (
                cancellation is not None and cancellation.cancelled
            ):
                raise TurnInterrupted(
                    (
                        cancellation.reason
                        if cancellation is not None
                        else None
                    )
                    or "Codex turn stopped before turn/start"
                )
            # Retain the authoritative turn id before entering the wait. Any
            # later timeout/failure can then bind drained parent commentary
            # into a partial result instead of discarding it.
            turn_id = _start_turn(
                client,
                thread_id=thread_id,
                request=request,
                effort=requested.effort,
                service_tier=requested.service_tier,
            )
            _wait_for_turn(
                client,
                thread_id=thread_id,
                turn_id=turn_id,
                interrupt_requested=self._interrupt_requested,
            )
            text_parts = [
                str(item.get("text") or "")
                for item in _bound_items(client, thread_id, turn_id)
                if item.get("type") == "agentMessage"
            ]
            text = _render_codex_reply(text_parts)
        except BaseException as exc:
            primary = exc
        finally:
            try:
                client.close()
            except BaseException as exc:
                if primary is None:
                    primary = exc
                else:
                    client.fatal.append(
                        f"close failed after primary exception: "
                        f"{type(exc).__name__}: {exc}"
                    )
            try:
                if thread_id is not None:
                    _audit_items(client, thread_id, turn_id)
            except Exception as exc:
                client.fatal.append(f"item audit failed: {exc}")
            with self._active_lock:
                self._active_client = None

        # Interrupted/failed turns can still have authoritative partial
        # agentMessage items drained during close; preserve them.
        if not text and thread_id is not None and turn_id is not None:
            text_parts = [
                str(item.get("text") or "")
                for item in _bound_items(client, thread_id, turn_id)
                if item.get("type") == "agentMessage"
            ]
            text = _render_codex_reply(text_parts)

        requested = request.participant.model_profile.requested
        echoed_model = thread.get("model")
        echoed_tier = thread.get("serviceTier")
        profile: ModelProfile | None = None
        if echoed_model:
            profile = request.participant.model_profile.resolved(
                ModelSelection(
                    model_id=str(echoed_model),
                    effort=requested.effort,
                    service_tier=(
                        str(echoed_tier) if echoed_tier is not None else None
                    ),
                    features=requested.features,
                ),
                (
                    "model/service tier: codex thread/start echo; "
                    "effort: catalog-validated turn/start acceptance"
                ),
            )
        result: TurnResult | None = None
        account_route = (
            f"chatgpt:{str(account.get('planType') or 'unknown').casefold()}"
        )
        if text and profile is not None:
            blocks = (StructuredContentBlock.markdown(text),)
            result = TurnResult(
                text=text,
                blocks=blocks,
                model_profile=profile,
                account_route=account_route,
                runtime_version=gates.REQUIRED_CODEX_VERSION,
                evidence=(
                    ("model_provider", str(thread.get("modelProvider") or "")),
                    (
                        "thread_id_sha256",
                        sha256_text(str(thread_id or "")),
                    ),
                    ("turn_id_sha256", sha256_text(str(turn_id or ""))),
                    (
                        "rate_limit_event_count",
                        str(len(client.rate_limit_events)),
                    ),
                    (
                        "purchased_credit_spend_available",
                        str(bool(credit_spend_available)).lower(),
                    ),
                    ("thread_ephemeral", "true"),
                    *_codex_compaction_evidence(client, thread_id, turn_id),
                ),
            )
        if client.rate_limit_stop:
            raise PlanUsageWarning(
                client.rate_limit_stop,
                partial_result=result,
            ) from primary
        if isinstance(primary, TurnInterrupted):
            raise TurnInterrupted(
                primary.reason,
                partial_result=result,
            ) from primary
        if isinstance(primary, TurnTimedOut):
            private_reason = primary.reason
            if client.fatal:
                private_reason += f" [secondary faults: {client.fatal}]"
            raise TurnTimedOut(
                primary.kind,
                reason=private_reason,
                partial_result=result or primary.partial_result,
            ) from primary
        if isinstance(primary, PlanUsageWarning):
            raise PlanUsageWarning(
                primary.reason,
                partial_result=result,
            ) from primary
        if isinstance(primary, RuntimeGateError):
            raise primary
        if primary is not None:
            detail = f"{type(primary).__name__}: {primary}"
            if client.fatal:
                detail += f" [secondary faults: {client.fatal}]"
            partial = (
                result
                or (
                    primary.partial_result
                    if isinstance(primary, AdapterError)
                    else None
                )
            )
            raise AdapterError(detail, partial_result=partial) from primary
        if client.fatal:
            raise AdapterError(
                f"codex client fatal events: {client.fatal}",
                partial_result=result,
            )
        if result is None:
            raise AdapterError("codex turn produced no authoritative text result")
        return result

    async def interrupt(self) -> None:
        fail_pending = getattr(self.presenter, "fail_pending", None)
        if callable(fail_pending):
            fail_pending("run stopped while permission card was open")
        self._interrupt_requested.set()

    async def close(self) -> None:
        self._interrupt_requested.set()
