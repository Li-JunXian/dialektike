"""Static provider registrations separated from inert descriptor data."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
import re
from typing import Protocol

from dialektike.domain import (
    AdapterCapabilities,
    CancellationSignal,
    ProviderAdapter,
    StructuredContentBlock,
    TurnRequest,
    TurnResult,
    opaque_id,
)
from dialektike.content import content_blocks_text
from dialektike.providers.contract import ProviderDescriptor, validate_frozen_module


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProviderRegistryError(RuntimeError):
    """A static registration cannot be proven to match its descriptor."""


class AdapterFactory(Protocol):
    def __call__(
        self,
        presenter: object,
        activity_bridge: object | None = None,
    ) -> ProviderAdapter:
        ...


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    """One Live-approved callable coupled to one reviewed descriptor digest."""

    descriptor: ProviderDescriptor
    factory: AdapterFactory
    descriptor_sha256: str
    approval_reference: str
    frozen_modules: tuple[str, ...]

    def __post_init__(self) -> None:
        if not callable(self.factory):
            raise ProviderRegistryError("provider adapter factory must be callable")
        if _SHA256.fullmatch(self.descriptor_sha256) is None:
            raise ProviderRegistryError("descriptor_sha256 must be lowercase SHA-256")
        if (
            not isinstance(self.approval_reference, str)
            or not self.approval_reference.strip()
            or len(self.approval_reference) > 300
            or "<" in self.approval_reference
            or ">" in self.approval_reference
        ):
            raise ProviderRegistryError("approval_reference must be constrained text")
        if not self.frozen_modules:
            raise ProviderRegistryError("a registration requires frozen module evidence")
        try:
            modules = tuple(validate_frozen_module(item) for item in self.frozen_modules)
        except ValueError as exc:
            raise ProviderRegistryError(str(exc)) from exc
        if len(set(modules)) != len(modules):
            raise ProviderRegistryError("frozen module names must be unique")
        factory_module = getattr(self.factory, "__module__", None)
        if factory_module not in modules:
            raise ProviderRegistryError(
                "provider factory must be defined by a declared frozen module"
            )


class _RegisteredProviderAdapter:
    """Identity-checking facade around an explicitly constructed adapter."""

    def __init__(
        self,
        registration: ProviderRegistration,
        adapter: ProviderAdapter,
    ) -> None:
        self.descriptor = registration.descriptor
        self.registration = registration
        self._adapter = adapter
        self.adapter_id = self.descriptor.runtime_id
        self.relay_provider_id = self.descriptor.relay_provider_id
        if opaque_id(getattr(adapter, "adapter_id", None), "adapter id") != self.adapter_id:
            raise ProviderRegistryError(
                f"registered runtime {self.adapter_id!r} constructed adapter "
                f"{getattr(adapter, 'adapter_id', None)!r}"
            )
        try:
            relay_provider_id = opaque_id(
                getattr(adapter, "relay_provider_id", None),
                "adapter relay provider id",
            )
        except ValueError as exc:
            raise ProviderRegistryError(str(exc)) from exc
        if relay_provider_id != self.descriptor.relay_provider_id:
            raise ProviderRegistryError(
                f"registered runtime {self.adapter_id!r} constructed adapter "
                f"for relay identity {relay_provider_id!r}, expected "
                f"{self.descriptor.relay_provider_id!r}"
            )

    async def discover_capabilities(self) -> AdapterCapabilities:
        catalog = await self._adapter.discover_capabilities()
        if catalog.runtime_id != self.descriptor.runtime_id:
            raise ProviderRegistryError(
                f"runtime {self.adapter_id!r} returned catalog for "
                f"{catalog.runtime_id!r}"
            )
        if catalog.vendor_id != self.descriptor.vendor_id:
            raise ProviderRegistryError(
                f"runtime {self.adapter_id!r} returned vendor "
                f"{catalog.vendor_id!r}, expected {self.descriptor.vendor_id!r}"
            )
        if catalog.agent_system_id != self.descriptor.agent_system_id:
            raise ProviderRegistryError(
                f"runtime {self.adapter_id!r} returned agent system "
                f"{catalog.agent_system_id!r}, expected "
                f"{self.descriptor.agent_system_id!r}"
            )
        return catalog

    async def run_turn(
        self,
        request: TurnRequest,
        cancellation: CancellationSignal,
    ) -> TurnResult:
        participant = request.participant
        expected_identity = (
            self.descriptor.runtime_id,
            self.descriptor.vendor_id,
            self.descriptor.agent_system_id,
        )
        actual_identity = (
            participant.runtime_id,
            participant.vendor_id,
            participant.agent_system_id,
        )
        if actual_identity != expected_identity:
            raise ProviderRegistryError(
                f"turn participant identity does not match runtime "
                f"{self.descriptor.runtime_id!r}"
            )
        try:
            self.descriptor.validate_model_selection(
                participant.model_profile.requested
            )
            self.descriptor.validate_execution_profile(
                participant.execution_profile
            )
        except ValueError as exc:
            raise ProviderRegistryError(
                f"runtime {self.descriptor.runtime_id!r} rejected provider "
                f"controls: {exc}"
            ) from exc
        result = await self._adapter.run_turn(request, cancellation)
        declared = frozenset(self.descriptor.supported_content_types)
        normalized_blocks: list[StructuredContentBlock] = []
        changed = False
        for block in result.blocks:
            if block.type == "unknown" or block.type in declared:
                normalized_blocks.append(block)
                continue
            # An approved adapter is privileged, but its inert descriptor is
            # still authoritative for what shared code may render. Preserve one
            # direct readable string and discard executable/action fields.
            normalized_blocks.append(
                StructuredContentBlock.from_mapped(
                    asdict(block),
                    declared_types=self.descriptor.supported_content_types,
                )
            )
            changed = True
        if not changed:
            return result
        blocks = tuple(normalized_blocks)
        return replace(
            result,
            text=content_blocks_text(asdict(block) for block in blocks),
            blocks=blocks,
        )

    async def interrupt(self) -> None:
        await self._adapter.interrupt()

    async def close(self) -> None:
        await self._adapter.close()


class ProviderRegistry:
    """Immutable static registrations for the governed application bundle.

    This registry accepts callables already imported by trusted application
    code.  It never resolves module names, entry points, directories, URLs, or
    any other executable reference found in provider data.
    """

    def __init__(self, registrations: Iterable[ProviderRegistration]):
        ordered = tuple(registrations)
        if not ordered:
            raise ProviderRegistryError("provider registry must not be empty")
        by_runtime: dict[str, ProviderRegistration] = {}
        relay_runtime_ids: dict[str, str] = {}
        for registration in ordered:
            descriptor = registration.descriptor
            if descriptor.runtime_id in by_runtime:
                raise ProviderRegistryError(
                    f"duplicate runtime registration {descriptor.runtime_id!r}"
                )
            if descriptor.relay_provider_id in relay_runtime_ids:
                raise ProviderRegistryError(
                    "relay provider identities must map to exactly one runtime"
                )
            by_runtime[descriptor.runtime_id] = registration
            relay_runtime_ids[descriptor.relay_provider_id] = descriptor.runtime_id
        self._ordered = ordered
        self._by_runtime = by_runtime
        self._relay_runtime_ids = relay_runtime_ids

    @property
    def registrations(self) -> tuple[ProviderRegistration, ...]:
        return self._ordered

    @property
    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(item.descriptor for item in self._ordered)

    @property
    def relay_runtime_ids(self) -> Mapping[str, str]:
        return dict(self._relay_runtime_ids)

    def registration(self, runtime_id: str) -> ProviderRegistration:
        identity = opaque_id(runtime_id, "runtime id")
        try:
            return self._by_runtime[identity]
        except KeyError as exc:
            raise ProviderRegistryError(f"runtime {identity!r} is not registered") from exc

    def descriptor(self, runtime_id: str) -> ProviderDescriptor:
        return self.registration(runtime_id).descriptor

    def build_adapters(
        self,
        presenter: object,
        activity_bridge: object | None = None,
    ) -> dict[str, ProviderAdapter]:
        """Construct only the statically supplied and descriptor-bound factories."""

        adapters: dict[str, ProviderAdapter] = {}
        for registration in self._ordered:
            adapter = registration.factory(presenter, activity_bridge)
            wrapped = _RegisteredProviderAdapter(registration, adapter)
            adapters[wrapped.adapter_id] = wrapped
        return adapters
