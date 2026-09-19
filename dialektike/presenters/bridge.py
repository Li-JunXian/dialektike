"""Trusted GUI bridge for the synchronous provider-neutral PermissionRelay.

Native provider callbacks may arrive on an SDK worker or app-server reader
thread. The presenter publishes one trusted sidecar event onto the asyncio
control loop and blocks that provider thread until Live answers through the
separate ``permission.respond`` command.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import secrets
import threading
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from core.relay import Decision, NormalizedRequest
from dialektike.domain import opaque_id

PermissionEmitter = Callable[[str, dict], Awaitable[None]]


class BridgePermissionError(RuntimeError):
    """The trusted GUI permission channel cannot certify a human decision."""


def _runtime_id_mapping(
    values: Mapping[str, str],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
        for relay_provider_id, runtime_id in values.items():
            relay = opaque_id(relay_provider_id, "relay provider id")
            runtime = opaque_id(runtime_id, "runtime id")
            if relay in mapping:
                raise BridgePermissionError(
                    f"duplicate relay provider identity {relay!r}"
                )
            mapping[relay] = runtime
    except ValueError as exc:
        raise BridgePermissionError(str(exc)) from exc
    if len(set(mapping.values())) != len(mapping):
        raise BridgePermissionError(
            "trusted relay provider identities must map to distinct runtimes"
        )
    return mapping


def _desktop_runtime_id(
    provider: str,
    runtime_ids_by_relay_provider: Mapping[str, str] | None = None,
) -> str:
    """Map relay identity through the reviewed provider descriptors.

    ``NormalizedRequest.provider`` remains unchanged because it participates
    in M1 relay fingerprints. Only the trusted GUI envelope uses the M2
    agent-system identifier.
    """

    if runtime_ids_by_relay_provider is None:
        from dialektike.providers.approved import approved_relay_runtime_ids

        runtime_ids_by_relay_provider = approved_relay_runtime_ids()
    mapping = _runtime_id_mapping(runtime_ids_by_relay_provider)
    try:
        relay_provider_id = opaque_id(provider, "relay provider id")
    except ValueError as exc:
        raise BridgePermissionError(str(exc)) from exc
    try:
        return mapping[relay_provider_id]
    except KeyError as exc:
        raise BridgePermissionError(
            f"provider {provider!r} has no trusted desktop runtime identity"
        ) from exc


@dataclass
class _Pending:
    request: NormalizedRequest
    ready: threading.Event = field(default_factory=threading.Event)
    decision: Decision | None = None
    error: str | None = None
    answered: bool = False


class BridgePresenter:
    """Exactly one opaque GUI response for each currently pending card."""

    def __init__(
        self,
        runtime_ids_by_relay_provider: Mapping[str, str] | None = None,
    ) -> None:
        if runtime_ids_by_relay_provider is None:
            from dialektike.providers.approved import approved_relay_runtime_ids

            runtime_ids_by_relay_provider = approved_relay_runtime_ids()
        self._runtime_ids_by_relay_provider = _runtime_id_mapping(
            runtime_ids_by_relay_provider
        )
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._emit: PermissionEmitter | None = None
        self._closed_reason: str | None = None

    def bind(
        self,
        loop: asyncio.AbstractEventLoop,
        emit: PermissionEmitter,
    ) -> None:
        """Bind once to the sidecar's trusted event loop."""

        with self._lock:
            if self._loop is not None:
                raise BridgePermissionError("permission presenter is already bound")
            if self._closed_reason is not None:
                raise BridgePermissionError(
                    f"permission presenter is closed: {self._closed_reason}"
                )
            self._loop = loop
            self._emit = emit

    @property
    def pending_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._pending)

    def __call__(self, request: NormalizedRequest, card: str) -> Decision:
        """Publish the full card, then block this provider thread for Live."""

        runtime_id = _desktop_runtime_id(
            request.provider,
            self._runtime_ids_by_relay_provider,
        )
        permission_id = secrets.token_urlsafe(24)
        pending = _Pending(request=request)
        with self._lock:
            if self._closed_reason is not None:
                raise BridgePermissionError(
                    f"trusted permission channel closed: {self._closed_reason}"
                )
            loop, emit = self._loop, self._emit
            if loop is None or emit is None:
                raise BridgePermissionError("trusted permission presenter is not bound")
            self._pending[permission_id] = pending

        native_context = request.payload.get("native_context")
        title = None
        if isinstance(native_context, dict):
            title = native_context.get("title") or native_context.get("display_name")
        payload = {
            "permission_id": permission_id,
            "runtime_id": runtime_id,
            "title": str(title or f"Native {request.kind} permission"),
            "card": card,
            "native_payload": request.payload,
            "case": request.case,
            "phase": request.phase,
            "role": request.role,
            "model": request.model,
            "request_kind": request.kind,
            "payload_sha256": request.payload_sha256,
            "fingerprint": request.fingerprint,
            "annotations": request.annotations,
        }
        try:
            delivery = asyncio.run_coroutine_threadsafe(
                emit("permission.request", payload), loop
            )
            delivery.result(timeout=30)
            pending.ready.wait()
            if pending.error is not None:
                raise BridgePermissionError(pending.error)
            if pending.decision not in ("allow", "deny"):
                raise BridgePermissionError(
                    "trusted permission channel woke without a valid decision"
                )
            return pending.decision
        except BaseException:
            with self._lock:
                self._pending.pop(permission_id, None)
            raise

    def respond(self, permission_id: str, decision: str) -> bool:
        """Accept one Live response; return false for stale/duplicate ids."""

        if decision not in ("allow_once", "deny"):
            raise BridgePermissionError(
                f"invalid permission decision {decision!r}; "
                "expected allow_once or deny"
            )
        with self._lock:
            pending = self._pending.get(permission_id)
            if pending is None or pending.answered:
                return False
            pending.answered = True
            pending.decision = "allow" if decision == "allow_once" else "deny"
            pending.ready.set()
            return True

    def _take_pending(
        self, request: NormalizedRequest
    ) -> tuple[str, _Pending] | None:
        with self._lock:
            match = next(
                (
                    (permission_id, pending)
                    for permission_id, pending in self._pending.items()
                    if pending.request is request
                ),
                None,
            )
            if match is not None:
                self._pending.pop(match[0], None)
            return match

    def _emit_resolution(
        self,
        event: str,
        request: NormalizedRequest,
        decision: Decision,
    ) -> None:
        match = self._take_pending(request)
        if match is None:
            return
        permission_id, _ = match
        with self._lock:
            loop, emit = self._loop, self._emit
        if loop is None or emit is None:
            return
        delivery = asyncio.run_coroutine_threadsafe(
            emit(
                event,
                {
                    "permission_id": permission_id,
                    "decision": decision,
                    "message": (
                        "The permission decision is durably recorded."
                        if event == "permission.recorded"
                        else (
                            "The permission decision could not be certified; "
                            "the action was not authorized."
                        )
                    ),
                },
            ),
            loop,
        )
        delivery.result(timeout=30)

    def decision_recorded(
        self, request: NormalizedRequest, decision: Decision
    ) -> None:
        """Tell the GUI only after PermissionRelay durably appends the choice."""

        self._emit_resolution("permission.recorded", request, decision)

    def decision_record_failed(
        self, request: NormalizedRequest, decision: Decision
    ) -> None:
        """Fail the GUI card when the ledger append could not be certified."""

        self._emit_resolution("permission.record_failed", request, decision)

    def fail_pending(self, reason: str) -> None:
        """Fail closed every open card without disabling later runs."""

        clean = reason.strip()
        if not clean:
            raise ValueError("permission failure reason must not be empty")
        with self._lock:
            for pending in self._pending.values():
                if not pending.answered:
                    pending.answered = True
                    pending.error = clean
                    pending.ready.set()

    def fail_closed(self, reason: str) -> None:
        """PermissionController name for failing all currently open cards."""

        self.fail_pending(reason)

    def close(self, reason: str) -> None:
        """Permanently fail closed and wake all provider callbacks."""

        clean = reason.strip()
        if not clean:
            raise ValueError("permission close reason must not be empty")
        with self._lock:
            if self._closed_reason is None:
                self._closed_reason = clean
            for pending in self._pending.values():
                if not pending.answered:
                    pending.answered = True
                    pending.error = self._closed_reason
                    pending.ready.set()
