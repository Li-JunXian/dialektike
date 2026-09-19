"""Shared adapter outcomes that cross the provider boundary."""

from __future__ import annotations

from dialektike.domain import TurnResult


class AdapterError(RuntimeError):
    """A provider runtime cannot certify a requested operation.

    Provider transports can fail after emitting authoritative assistant text.
    ``partial_result`` keeps that text coupled to its runtime-authenticated
    model/account evidence while the turn itself remains failed.
    """

    def __init__(
        self,
        reason: str,
        *,
        partial_result: TurnResult | None = None,
    ) -> None:
        clean = reason.strip()
        if not clean:
            raise ValueError("adapter failure reason must not be empty")
        super().__init__(clean)
        self.reason = clean
        self.partial_result = partial_result


class TurnInterrupted(AdapterError):
    """Live stopped a turn; any authoritative partial result is preserved."""

    def __init__(
        self,
        reason: str,
        *,
        partial_result: TurnResult | None = None,
    ) -> None:
        clean = reason.strip()
        if not clean:
            raise ValueError("interruption reason must not be empty")
        super().__init__(clean, partial_result=partial_result)


class TurnTimedOut(AdapterError):
    """A provider turn crossed an authored, non-secret safety boundary."""

    _PUBLIC_MESSAGES = {
        "idle": (
            "Codex was stopped safely after 10 minutes without new activity. "
            "Any partial response was saved."
        ),
        "hard": (
            "Codex was stopped safely after reaching the 60-minute turn "
            "safety limit. Any partial response was saved."
        ),
    }

    def __init__(
        self,
        kind: str,
        *,
        reason: str | None = None,
        partial_result: TurnResult | None = None,
    ) -> None:
        if kind not in self._PUBLIC_MESSAGES:
            raise ValueError("turn timeout kind must be 'idle' or 'hard'")
        self.kind = kind
        self.public_message = self._PUBLIC_MESSAGES[kind]
        private_reason = reason or (
            "codex parent turn exceeded the inactivity boundary"
            if kind == "idle"
            else "codex parent turn exceeded the active-runtime hard boundary"
        )
        super().__init__(private_reason, partial_result=partial_result)


class PlanUsageWarning(AdapterError):
    """The runtime signalled a plan boundary; no later turn may start."""

    def __init__(
        self,
        reason: str,
        *,
        partial_result: TurnResult | None = None,
    ) -> None:
        clean = reason.strip()
        if not clean:
            raise ValueError("plan warning reason must not be empty")
        super().__init__(clean, partial_result=partial_result)
