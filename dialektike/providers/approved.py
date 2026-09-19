"""Release-approved provider descriptor bundle and adapter composition.

The JSON manifest is integrity evidence and contains no executable entry point.
Factories are referenced directly in this reviewed source module so descriptor
data can never select a module or callable to import.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from dialektike.providers.contract import (
    DescriptorError,
    ProviderDescriptor,
    descriptor_from_mapping,
    descriptor_to_mapping,
    validate_frozen_module,
)
from dialektike.providers.registry import (
    AdapterFactory,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRegistryError,
)


_ROOT = Path(__file__).resolve().parent
_MANIFEST = _ROOT / "approved-providers.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ApprovedDescriptorRecord:
    descriptor: ProviderDescriptor
    descriptor_sha256: str
    approval_reference: str
    frozen_modules: tuple[str, ...]


def _strict_keys(
    value: dict,
    label: str,
    expected: tuple[str, ...],
) -> None:
    missing = set(expected) - set(value)
    unknown = set(value) - set(expected)
    if missing:
        raise ProviderRegistryError(f"{label} is missing keys {sorted(missing)!r}")
    if unknown:
        raise ProviderRegistryError(f"{label} has unknown keys {sorted(unknown)!r}")


def _plain_text(value: object, label: str, *, max_length: int = 300) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
        or "<" in value
        or ">" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise ProviderRegistryError(f"{label} must be constrained plain text")
    return value


def _descriptor_path(value: object) -> Path:
    relative_text = _plain_text(value, "descriptor path", max_length=180)
    relative = Path(relative_text)
    if (
        relative.is_absolute()
        or relative.suffix != ".json"
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ProviderRegistryError("descriptor path must be a relative JSON path")
    candidate = _ROOT / relative
    current = _ROOT
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ProviderRegistryError(
                "approved descriptor path must not traverse a symlink"
            )
    resolved = candidate.resolve()
    try:
        resolved.relative_to(_ROOT)
    except ValueError as exc:
        raise ProviderRegistryError("descriptor path escapes the approved bundle") from exc
    if not resolved.is_file():
        raise ProviderRegistryError("approved descriptor must be a regular bundled file")
    return resolved


def approved_descriptor_records() -> tuple[ApprovedDescriptorRecord, ...]:
    """Verify and parse every sealed manifest entry, failing closed on drift."""

    try:
        manifest_raw = _MANIFEST.read_bytes()
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderRegistryError(f"cannot read approved provider manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ProviderRegistryError("approved provider manifest must be an object")
    _strict_keys(manifest, "approved provider manifest", ("schema_version", "providers"))
    if (
        isinstance(manifest["schema_version"], bool)
        or manifest["schema_version"] != 1
    ):
        raise ProviderRegistryError("unsupported approved provider manifest schema")
    providers = manifest["providers"]
    if not isinstance(providers, list) or not providers:
        raise ProviderRegistryError("approved provider manifest must list providers")

    records: list[ApprovedDescriptorRecord] = []
    runtime_ids: set[str] = set()
    descriptor_paths: set[Path] = set()
    for index, value in enumerate(providers):
        label = f"approved provider manifest entry {index}"
        if not isinstance(value, dict):
            raise ProviderRegistryError(f"{label} must be an object")
        fields = (
            "runtime_id",
            "descriptor",
            "descriptor_sha256",
            "approval_reference",
            "frozen_modules",
        )
        _strict_keys(value, label, fields)
        path = _descriptor_path(value["descriptor"])
        if path in descriptor_paths:
            raise ProviderRegistryError("approved descriptor paths must be unique")
        expected_digest = value["descriptor_sha256"]
        if not isinstance(expected_digest, str) or _SHA256.fullmatch(expected_digest) is None:
            raise ProviderRegistryError("descriptor digest must be lowercase SHA-256")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ProviderRegistryError(f"cannot read approved descriptor: {exc}") from exc
        actual_digest = hashlib.sha256(raw).hexdigest()
        if actual_digest != expected_digest:
            raise ProviderRegistryError(
                f"approved descriptor {path.name!r} does not match its reviewed digest"
            )
        try:
            descriptor = descriptor_from_mapping(json.loads(raw.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError, DescriptorError) as exc:
            raise ProviderRegistryError(
                f"approved descriptor {path.name!r} is invalid: {exc}"
            ) from exc
        runtime_id = _plain_text(value["runtime_id"], "approved runtime id", max_length=96)
        if descriptor.runtime_id != runtime_id:
            raise ProviderRegistryError(
                f"manifest runtime {runtime_id!r} does not match descriptor identity"
            )
        if runtime_id in runtime_ids:
            raise ProviderRegistryError(f"duplicate approved runtime {runtime_id!r}")
        modules_value = value["frozen_modules"]
        if not isinstance(modules_value, list) or not modules_value:
            raise ProviderRegistryError("approved runtime requires frozen module evidence")
        try:
            frozen_modules = tuple(
                validate_frozen_module(module) for module in modules_value
            )
        except DescriptorError as exc:
            raise ProviderRegistryError(str(exc)) from exc
        if len(set(frozen_modules)) != len(frozen_modules):
            raise ProviderRegistryError("frozen module names must be unique")
        records.append(
            ApprovedDescriptorRecord(
                descriptor=descriptor,
                descriptor_sha256=actual_digest,
                approval_reference=_plain_text(
                    value["approval_reference"], "approval reference"
                ),
                frozen_modules=frozen_modules,
            )
        )
        runtime_ids.add(runtime_id)
        descriptor_paths.add(path)
    return tuple(records)


def approved_descriptors() -> tuple[ProviderDescriptor, ...]:
    return tuple(record.descriptor for record in approved_descriptor_records())


def approved_descriptor_payloads() -> tuple[dict[str, object], ...]:
    """Return strictly primitive payloads suitable for the trusted sidecar wire."""

    return tuple(
        descriptor_to_mapping(record.descriptor)
        for record in approved_descriptor_records()
    )


def approved_relay_runtime_ids() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for descriptor in approved_descriptors():
        if descriptor.relay_provider_id in mapping:
            raise ProviderRegistryError(
                "approved relay provider identities must map to one runtime"
            )
        mapping[descriptor.relay_provider_id] = descriptor.runtime_id
    return mapping


def approved_registry() -> ProviderRegistry:
    """Build the explicitly reviewed production registry.

    Direct imports here are deliberate.  The reviewed source, frozen-module
    manifest, and descriptor digest must all agree; no JSON value is imported.
    """

    from dialektike.adapters.claude import ClaudeCodeRuntimeAdapter
    from dialektike.adapters.codex import CodexRuntimeAdapter

    factories: dict[str, AdapterFactory] = {
        "claude-code": ClaudeCodeRuntimeAdapter,
        "codex": CodexRuntimeAdapter,
    }
    records = approved_descriptor_records()
    record_ids = {record.descriptor.runtime_id for record in records}
    if set(factories) != record_ids:
        raise ProviderRegistryError(
            "reviewed provider factories and approved descriptors do not match"
        )
    return ProviderRegistry(
        ProviderRegistration(
            descriptor=record.descriptor,
            factory=factories[record.descriptor.runtime_id],
            descriptor_sha256=record.descriptor_sha256,
            approval_reference=record.approval_reference,
            frozen_modules=record.frozen_modules,
        )
        for record in records
    )
