"""Trusted, inert provider descriptors and static adapter registrations.

Importing this package never imports or discovers provider runtime code.  The
release-approved adapter factories live behind the explicit function in
``dialektike.providers.approved``.
"""

from dialektike.providers.contract import (
    Availability,
    ConnectMetadata,
    ControlDefinition,
    ControlOption,
    DefaultSelection,
    DescriptorError,
    EvidenceDeclaration,
    ExecutionProfileDefinition,
    PermissionField,
    PermissionPresentation,
    ProviderDescriptor,
    ProviderDisplay,
    RuntimeFacility,
    descriptor_from_mapping,
    descriptor_to_mapping,
    load_descriptor,
)
from dialektike.providers.registry import (
    ProviderRegistration,
    ProviderRegistry,
    ProviderRegistryError,
)

__all__ = (
    "Availability",
    "ConnectMetadata",
    "ControlDefinition",
    "ControlOption",
    "DefaultSelection",
    "DescriptorError",
    "EvidenceDeclaration",
    "ExecutionProfileDefinition",
    "PermissionField",
    "PermissionPresentation",
    "ProviderDescriptor",
    "ProviderDisplay",
    "ProviderRegistration",
    "ProviderRegistry",
    "ProviderRegistryError",
    "RuntimeFacility",
    "descriptor_from_mapping",
    "descriptor_to_mapping",
    "load_descriptor",
)
