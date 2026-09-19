"""Participant registry and cross-object validation for M2."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from dialektike.domain import Participant, ProviderAdapter, RunConfig


class RegistryError(ValueError):
    """A run refers to an invalid or unavailable participant configuration."""


class ParticipantRegistry:
    """An immutable, insertion-ordered participant lookup.

    Participants own identity and configuration; protocol roles remain in
    ``RunConfig.assignments``.  One run has one stable Executor and an ordered
    set of independent Auditors.
    """

    def __init__(self, participants: Iterable[Participant]):
        ordered = tuple(participants)
        if not ordered:
            raise RegistryError("participant registry requires at least one participant")
        by_id: dict[str, Participant] = {}
        for participant in ordered:
            if participant.participant_id in by_id:
                raise RegistryError(
                    f"duplicate participant id {participant.participant_id!r}"
                )
            by_id[participant.participant_id] = participant
        self._ordered = ordered
        self._by_id = by_id

    @property
    def participants(self) -> tuple[Participant, ...]:
        return self._ordered

    def __len__(self) -> int:
        return len(self._ordered)

    def __iter__(self):
        return iter(self._ordered)

    def get(self, participant_id: str) -> Participant:
        try:
            return self._by_id[participant_id]
        except KeyError as exc:
            raise RegistryError(f"unknown participant {participant_id!r}") from exc

    def validate_run(
        self,
        config: RunConfig,
        adapters: Mapping[str, ProviderAdapter],
    ) -> None:
        config_ids = tuple(item.participant_id for item in config.participants)
        registry_ids = tuple(item.participant_id for item in self._ordered)
        if config_ids != registry_ids:
            raise RegistryError(
                "run participant list must exactly match the registry, in registry order"
            )

        for participant in self._ordered:
            adapter = adapters.get(participant.adapter_id)
            if adapter is None:
                raise RegistryError(
                    f"participant {participant.participant_id!r} uses unavailable "
                    f"adapter {participant.adapter_id!r}"
                )
            if adapter.adapter_id != participant.adapter_id:
                raise RegistryError(
                    f"adapter map key {participant.adapter_id!r} does not match "
                    f"adapter identity {adapter.adapter_id!r}"
                )
            descriptor = getattr(adapter, "descriptor", None)
            if descriptor is not None:
                expected = (
                    participant.runtime_id,
                    participant.vendor_id,
                    participant.agent_system_id,
                )
                actual = (
                    getattr(descriptor, "runtime_id", None),
                    getattr(descriptor, "vendor_id", None),
                    getattr(descriptor, "agent_system_id", None),
                )
                if actual != expected:
                    raise RegistryError(
                        f"participant {participant.participant_id!r} identity "
                        "does not match its trusted provider descriptor"
                    )
                validate_model_selection = getattr(
                    descriptor, "validate_model_selection", None
                )
                validate_execution_profile = getattr(
                    descriptor, "validate_execution_profile", None
                )
                if not callable(validate_model_selection) or not callable(
                    validate_execution_profile
                ):
                    raise RegistryError(
                        f"participant {participant.participant_id!r} has an "
                        "invalid trusted provider descriptor"
                    )
                try:
                    validate_model_selection(
                        participant.model_profile.requested
                    )
                    validate_execution_profile(participant.execution_profile)
                except ValueError as exc:
                    raise RegistryError(
                        f"participant {participant.participant_id!r} selects an "
                        f"invalid provider control: {exc}"
                    ) from exc

        if config.mode == "chat":
            self.get(config.speaker_id)
            return

        active_ids: set[str] = set()
        for assignment in config.assignments:
            self.get(assignment.executor_id)
            active_ids.add(assignment.executor_id)
            for auditor_id in assignment.auditor_ids:
                self.get(auditor_id)
                active_ids.add(auditor_id)

        configured_ids = {item.participant_id for item in self._ordered}
        if active_ids != configured_ids:
            raise RegistryError(
                "run participants must be exactly the active Executor and Auditors"
            )

        active = tuple(
            item for item in self._ordered if item.participant_id in active_ids
        )
        vendors = [item.vendor_id for item in active]
        if len(set(vendors)) != len(vendors):
            raise RegistryError(
                "every active participant must use a distinct vendor"
            )

    def participants_for_adapter(self, adapter_id: str) -> tuple[Participant, ...]:
        return tuple(
            item for item in self._ordered if item.adapter_id == adapter_id
        )
