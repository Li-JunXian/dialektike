"""Thread-safe bridge for genuine, user-visible runtime activity.

The provider adapters may observe activity on either the asyncio SDK loop or
the Codex app-server reader thread.  This bridge publishes only compact,
display-safe status facts onto the sidecar event loop.  It is deliberately
separate from the permission bridge: activity can never answer or influence a
permission request.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable

from core.relay import sanitize_terminal
from dialektike.domain import TurnRequest

ActivityEmitter = Callable[[str, dict], Awaitable[None]]


class RuntimeActivityBridge:
    """Publish native activity from any provider thread without blocking it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._emit: ActivityEmitter | None = None

    def bind(
        self,
        loop: asyncio.AbstractEventLoop,
        emit: ActivityEmitter,
    ) -> None:
        with self._lock:
            if self._loop is not None:
                raise RuntimeError("runtime activity bridge is already bound")
            self._loop = loop
            self._emit = emit

    def publish(
        self,
        request: TurnRequest,
        message: str,
        *,
        activity: str,
        state: str = "running",
    ) -> None:
        """Publish one genuine provider observation.

        ``message`` is provider-authored user-visible status or a factual tool
        lifecycle label derived from the native event type. Hidden thinking
        content is never passed to this method.
        """

        clean = sanitize_terminal(str(message)).strip()
        if not clean:
            return
        with self._lock:
            loop, emit = self._loop, self._emit
        if loop is None or emit is None or loop.is_closed():
            return
        payload = {
            "run_id": request.run_id,
            "participant_id": request.participant.participant_id,
            "runtime_id": request.participant.adapter_id,
            "role": request.role.value,
            "round": request.round_number,
            "turn": request.turn_number,
            "stage": request.stage.value,
            "activity": activity,
            "status": state,
            "native_summary": clean,
            "source": "native-runtime",
            "trusted": True,
        }
        asyncio.run_coroutine_threadsafe(
            emit("participant.activity", payload),
            loop,
        )
