"""Provider adapters for Dialektikḗ M2.

Adapters own native runtime discovery and wire translation. Roles,
orchestration, persistence, permission policy, and presentation stay outside
this package.
"""

from dialektike.adapters.capabilities import (
    CapabilityError,
    RuntimeGateError,
    claude_capabilities_from_server_info,
    codex_capabilities_from_model_list,
    validate_selection,
)

__all__ = [
    "CapabilityError",
    "RuntimeGateError",
    "claude_capabilities_from_server_info",
    "codex_capabilities_from_model_list",
    "validate_selection",
]
