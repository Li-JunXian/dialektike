"""Strict data-only provider descriptor contract.

Descriptors are presentation and capability metadata, never executable plugin
entry points.  The parser rejects unknown keys and constrains every token so a
signed application may consume reviewed descriptors without rendering HTML,
evaluating expressions, or loading code named by descriptor data.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from dialektike.domain import (
    ControlScalar,
    ControlValue,
    ExecutionProfile,
    ModelSelection,
    opaque_id,
)


_SCHEMA_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]*$")
_JSON_POINTER = re.compile(r"^(?:/(?:[^~/]|~[01])*)+$")
_MODULE_NAME = re.compile(r"^[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+$")
_MAX_TEXT_LENGTH = 800
_MAX_INTEGER = 1_000_000_000


class DescriptorError(ValueError):
    """A provider descriptor is malformed or exceeds the inert contract."""


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DescriptorError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DescriptorError(f"{label} must be a JSON array")
    return value


def _keys(
    value: Mapping[str, Any],
    label: str,
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> None:
    expected = set(required) | set(optional)
    missing = set(required) - set(value)
    unknown = set(value) - expected
    if missing:
        raise DescriptorError(f"{label} is missing keys {sorted(missing)!r}")
    if unknown:
        raise DescriptorError(f"{label} has unknown keys {sorted(unknown)!r}")


def _plain_text(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
    max_length: int = _MAX_TEXT_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise DescriptorError(f"{label} must be text")
    if (not allow_empty and not value.strip()) or len(value) > max_length:
        raise DescriptorError(f"{label} must be non-empty and at most {max_length} chars")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise DescriptorError(f"{label} contains control characters")
    lowered = value.casefold()
    if "<" in value or ">" in value or "javascript:" in lowered:
        raise DescriptorError(f"{label} contains executable or HTML-like content")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _plain_text(value, label)


def _token(value: object, label: str) -> str:
    text = _plain_text(value, label, max_length=128)
    if _SCHEMA_TOKEN.fullmatch(text) is None:
        raise DescriptorError(f"{label} must be a constrained schema token")
    return text


def _scalar(value: object, label: str) -> ControlScalar:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and -_MAX_INTEGER <= value <= _MAX_INTEGER:
        return value
    if isinstance(value, str):
        return _plain_text(value, label, max_length=200)
    raise DescriptorError(f"{label} must be a bounded string, boolean, or integer")


def _optional_scalar(value: object, label: str) -> ControlScalar | None:
    return None if value is None else _scalar(value, label)


def _opaque(value: object, label: str) -> str:
    try:
        return opaque_id(value, label)
    except ValueError as exc:
        raise DescriptorError(str(exc)) from exc


def _unique(values: tuple[str, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise DescriptorError(f"{label} must be unique")


def _same_scalar(left: ControlScalar, right: ControlScalar) -> bool:
    return type(left) is type(right) and left == right


@dataclass(frozen=True, slots=True)
class Availability:
    available: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.available, bool):
            raise DescriptorError("availability.available must be a boolean")
        if self.available and self.reason is not None:
            raise DescriptorError("available values cannot declare an unavailable reason")
        if not self.available:
            _plain_text(self.reason, "availability reason")


@dataclass(frozen=True, slots=True)
class ProviderDisplay:
    name: str
    short_name: str
    mark: str
    icon_token: str
    accent_token: str

    def __post_init__(self) -> None:
        _plain_text(self.name, "provider display name", max_length=80)
        _plain_text(self.short_name, "provider short name", max_length=40)
        _plain_text(self.mark, "provider mark", max_length=3)
        _opaque(self.icon_token, "provider icon token")
        _opaque(self.accent_token, "provider accent token")


@dataclass(frozen=True, slots=True)
class EvidenceDeclaration:
    label: str
    authority: str
    not_observable_label: str

    def __post_init__(self) -> None:
        _plain_text(self.label, "evidence label", max_length=80)
        _opaque(self.authority, "evidence authority")
        _plain_text(
            self.not_observable_label,
            "not-observable label",
            max_length=120,
        )


@dataclass(frozen=True, slots=True)
class DefaultSelection:
    model: str | None
    effort: str | None
    service_tier: str | None
    execution_profile: str

    def __post_init__(self) -> None:
        _optional_text(self.model, "default model")
        _optional_text(self.effort, "default effort")
        _optional_text(self.service_tier, "default service tier")
        _opaque(self.execution_profile, "default execution profile")


@dataclass(frozen=True, slots=True)
class ControlOption:
    value: ControlScalar
    label: str
    availability: Availability

    def __post_init__(self) -> None:
        _scalar(self.value, "control option value")
        _plain_text(self.label, "control option label", max_length=80)


@dataclass(frozen=True, slots=True)
class ControlDefinition:
    control_id: str
    label: str
    group: str
    kind: str
    description: str
    authority: str
    default: ControlScalar | None = None
    options: tuple[ControlOption, ...] = ()
    min_value: int | None = None
    max_value: int | None = None

    def __post_init__(self) -> None:
        _opaque(self.control_id, "control id")
        _plain_text(self.label, "control label", max_length=80)
        _plain_text(self.description, "control description")
        _opaque(self.authority, "control authority")
        if not isinstance(self.group, str) or self.group not in {
            "model",
            "turn",
            "execution",
            "runtime",
        }:
            raise DescriptorError(f"unsupported control group {self.group!r}")
        if not isinstance(self.kind, str) or self.kind not in {
            "select",
            "boolean",
            "integer",
            "status",
        }:
            raise DescriptorError(f"unsupported control kind {self.kind!r}")
        if self.default is not None:
            _scalar(self.default, "control default")
        if self.kind == "select":
            if not self.options:
                raise DescriptorError("select controls require options")
            option_values = tuple(repr(item.value) for item in self.options)
            _unique(option_values, f"options for control {self.control_id!r}")
            if self.default is not None:
                default_option = next(
                    (
                        item
                        for item in self.options
                        if _same_scalar(self.default, item.value)
                    ),
                    None,
                )
                if default_option is None:
                    raise DescriptorError("select control default must name one option")
                if not default_option.availability.available:
                    raise DescriptorError("select control default must be available")
            if self.min_value is not None or self.max_value is not None:
                raise DescriptorError("select controls cannot declare integer bounds")
        elif self.kind == "boolean":
            if self.options or self.min_value is not None or self.max_value is not None:
                raise DescriptorError("boolean controls cannot declare options or bounds")
            if self.default is not None and not isinstance(self.default, bool):
                raise DescriptorError("boolean control defaults must be boolean")
        elif self.kind == "integer":
            if self.options:
                raise DescriptorError("integer controls cannot declare options")
            if self.min_value is None or self.max_value is None:
                raise DescriptorError("integer controls require min_value and max_value")
            if (
                isinstance(self.min_value, bool)
                or isinstance(self.max_value, bool)
                or not isinstance(self.min_value, int)
                or not isinstance(self.max_value, int)
                or self.min_value > self.max_value
                or abs(self.min_value) > _MAX_INTEGER
                or abs(self.max_value) > _MAX_INTEGER
            ):
                raise DescriptorError("integer control bounds are invalid")
            if self.default is not None and (
                isinstance(self.default, bool)
                or not isinstance(self.default, int)
                or not self.min_value <= self.default <= self.max_value
            ):
                raise DescriptorError("integer control default is outside its bounds")
        elif (
            self.options
            or self.default is not None
            or self.min_value is not None
            or self.max_value is not None
        ):
            raise DescriptorError("status controls are read-only and cannot declare values")

    def validate_value(self, value: ControlScalar, label: str = "control value") -> None:
        """Validate one inert selection against this constrained schema."""

        scalar = _scalar(value, label)
        if self.kind == "select":
            option = next(
                (
                    item
                    for item in self.options
                    if _same_scalar(scalar, item.value)
                ),
                None,
            )
            if option is None:
                raise DescriptorError(
                    f"{label} is not declared for control {self.control_id!r}"
                )
            if not option.availability.available:
                raise DescriptorError(
                    option.availability.reason
                    or f"control option for {self.control_id!r} is unavailable"
                )
            return
        if self.kind == "boolean":
            if not isinstance(scalar, bool):
                raise DescriptorError(f"{label} must be boolean")
            return
        if self.kind == "integer":
            if isinstance(scalar, bool) or not isinstance(scalar, int):
                raise DescriptorError(f"{label} must be an integer")
            if self.min_value is None or self.max_value is None:
                raise DescriptorError("integer control schema has no bounds")
            if not self.min_value <= scalar <= self.max_value:
                raise DescriptorError(f"{label} is outside its declared bounds")
            return
        raise DescriptorError(f"status control {self.control_id!r} is not selectable")


@dataclass(frozen=True, slots=True)
class ExecutionProfileDefinition:
    profile_id: str
    label: str
    description: str
    availability: Availability
    values: tuple[ControlValue, ...] = ()

    def __post_init__(self) -> None:
        _opaque(self.profile_id, "execution profile id")
        _plain_text(self.label, "execution profile label", max_length=80)
        _plain_text(self.description, "execution profile description")
        ids = tuple(item.control_id for item in self.values)
        _unique(ids, f"values for execution profile {self.profile_id!r}")


@dataclass(frozen=True, slots=True)
class RuntimeFacility:
    facility_id: str
    label: str
    description: str
    observability: str
    management: str

    def __post_init__(self) -> None:
        _opaque(self.facility_id, "runtime facility id")
        _plain_text(self.label, "runtime facility label", max_length=80)
        _plain_text(self.description, "runtime facility description")
        if not isinstance(self.observability, str) or self.observability not in {
            "observable",
            "not-observable",
        }:
            raise DescriptorError(
                f"unsupported facility observability {self.observability!r}"
            )
        if not isinstance(self.management, str) or self.management not in {
            "dialektike",
            "runtime-native",
        }:
            raise DescriptorError(f"unsupported facility management {self.management!r}")


@dataclass(frozen=True, slots=True)
class PermissionField:
    field_id: str
    label: str
    pointer: str
    format: str

    def __post_init__(self) -> None:
        _opaque(self.field_id, "permission field id")
        _plain_text(self.label, "permission field label", max_length=80)
        if not isinstance(self.pointer, str) or _JSON_POINTER.fullmatch(self.pointer) is None:
            raise DescriptorError("permission field pointer must be a JSON Pointer")
        if len(self.pointer) > 240:
            raise DescriptorError("permission field pointer is too long")
        if not isinstance(self.format, str) or self.format not in {
            "text",
            "code",
            "path",
            "json",
        }:
            raise DescriptorError(f"unsupported permission field format {self.format!r}")


@dataclass(frozen=True, slots=True)
class PermissionPresentation:
    request_kind: str
    title: str
    layout: str
    fields: tuple[PermissionField, ...]

    def __post_init__(self) -> None:
        _token(self.request_kind, "permission request kind")
        _plain_text(self.title, "permission title", max_length=100)
        if not isinstance(self.layout, str) or self.layout not in {
            "command",
            "file-change",
            "tool",
            "generic",
        }:
            raise DescriptorError(f"unsupported permission layout {self.layout!r}")
        ids = tuple(item.field_id for item in self.fields)
        _unique(ids, f"fields for permission kind {self.request_kind!r}")


@dataclass(frozen=True, slots=True)
class ConnectMetadata:
    label: str
    help_text: str
    action: str

    def __post_init__(self) -> None:
        _plain_text(self.label, "connect label", max_length=80)
        _plain_text(self.help_text, "connect help text")
        if not isinstance(self.action, str) or self.action not in {
            "refresh-capabilities",
            "native-runtime",
        }:
            raise DescriptorError(f"unsupported connect action {self.action!r}")


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    schema_version: int
    descriptor_version: int
    runtime_id: str
    vendor_id: str
    agent_system_id: str
    relay_provider_id: str
    display: ProviderDisplay
    authentication: EvidenceDeclaration
    version_evidence: EvidenceDeclaration
    default_selection: DefaultSelection
    control_schema: tuple[ControlDefinition, ...]
    supported_content_types: tuple[str, ...]
    execution_profiles: tuple[ExecutionProfileDefinition, ...]
    runtime_facilities: tuple[RuntimeFacility, ...]
    permission_presentations: tuple[PermissionPresentation, ...]
    connect: ConnectMetadata

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise DescriptorError(
                f"unsupported provider descriptor schema {self.schema_version!r}"
            )
        if (
            isinstance(self.descriptor_version, bool)
            or not isinstance(self.descriptor_version, int)
            or self.descriptor_version < 1
        ):
            raise DescriptorError("descriptor_version must be a positive integer")
        _opaque(self.runtime_id, "runtime id")
        _opaque(self.vendor_id, "vendor id")
        _opaque(self.agent_system_id, "agent-system id")
        _opaque(self.relay_provider_id, "relay provider id")
        control_ids = tuple(item.control_id for item in self.control_schema)
        content_types = tuple(
            _opaque(item, "supported content type")
            for item in self.supported_content_types
        )
        profile_ids = tuple(item.profile_id for item in self.execution_profiles)
        facility_ids = tuple(item.facility_id for item in self.runtime_facilities)
        permission_kinds = tuple(
            item.request_kind for item in self.permission_presentations
        )
        _unique(control_ids, "provider control ids")
        _unique(content_types, "supported content types")
        _unique(profile_ids, "execution profile ids")
        _unique(facility_ids, "runtime facility ids")
        _unique(permission_kinds, "permission request kinds")
        if not content_types:
            raise DescriptorError("a provider must declare supported content types")
        if not self.execution_profiles:
            raise DescriptorError("a provider must declare an execution profile")
        if self.default_selection.execution_profile not in set(profile_ids):
            raise DescriptorError("default selection names an unknown execution profile")
        controls_by_id = {item.control_id: item for item in self.control_schema}
        for profile in self.execution_profiles:
            for value in profile.values:
                control = controls_by_id.get(value.control_id)
                if control is None:
                    raise DescriptorError(
                        f"execution profile {profile.profile_id!r} names unknown "
                        f"control {value.control_id!r}"
                    )
                if control.group != "execution":
                    raise DescriptorError(
                        f"execution profile value {value.control_id!r} is not an "
                        "execution control"
                    )
                control.validate_value(
                    value.value,
                    f"execution profile {profile.profile_id!r} value "
                    f"{value.control_id!r}",
                )

    def _validate_controls(
        self,
        values: tuple[ControlValue, ...],
        *,
        allowed_groups: frozenset[str],
        label: str,
    ) -> None:
        controls = {item.control_id: item for item in self.control_schema}
        for value in values:
            control = controls.get(value.control_id)
            if control is None:
                raise DescriptorError(
                    f"{label} names unknown control {value.control_id!r}"
                )
            if control.group not in allowed_groups:
                raise DescriptorError(
                    f"{label} cannot select {control.group!r} control "
                    f"{value.control_id!r}"
                )
            control.validate_value(value.value, f"{label} {value.control_id!r}")

    def validate_model_selection(self, selection: ModelSelection) -> None:
        """Fail closed when a turn/model control is absent or unavailable."""

        self._validate_controls(
            selection.controls,
            allowed_groups=frozenset({"model", "turn"}),
            label="model selection",
        )

    def validate_execution_profile(self, profile: ExecutionProfile) -> None:
        """Fail closed when a permission-affecting profile/control is invalid."""

        definition = next(
            (
                item
                for item in self.execution_profiles
                if item.profile_id == profile.profile_id
            ),
            None,
        )
        if definition is None:
            raise DescriptorError(
                f"unknown execution profile {profile.profile_id!r}"
            )
        if not definition.availability.available:
            raise DescriptorError(
                definition.availability.reason
                or f"execution profile {profile.profile_id!r} is unavailable"
            )
        expected_values = {
            item.control_id: (type(item.value), item.value)
            for item in definition.values
        }
        selected_values = {
            item.control_id: (type(item.value), item.value)
            for item in profile.values
        }
        if selected_values != expected_values:
            raise DescriptorError(
                f"execution profile {profile.profile_id!r} values must exactly "
                "match its reviewed descriptor"
            )
        self._validate_controls(
            profile.values,
            allowed_groups=frozenset({"execution"}),
            label="execution profile",
        )


def _availability(value: object, label: str) -> Availability:
    item = _object(value, label)
    _keys(item, label, required=("available", "reason"))
    return Availability(available=item["available"], reason=item["reason"])


def _display(value: object) -> ProviderDisplay:
    item = _object(value, "display")
    fields = ("name", "short_name", "mark", "icon_token", "accent_token")
    _keys(item, "display", required=fields)
    return ProviderDisplay(**{field: item[field] for field in fields})


def _evidence(value: object, label: str) -> EvidenceDeclaration:
    item = _object(value, label)
    fields = ("label", "authority", "not_observable_label")
    _keys(item, label, required=fields)
    return EvidenceDeclaration(**{field: item[field] for field in fields})


def _default_selection(value: object) -> DefaultSelection:
    item = _object(value, "default_selection")
    fields = ("model", "effort", "service_tier", "execution_profile")
    _keys(item, "default_selection", required=fields)
    return DefaultSelection(**{field: item[field] for field in fields})


def _control_option(value: object, label: str) -> ControlOption:
    item = _object(value, label)
    _keys(item, label, required=("value", "label", "availability"))
    return ControlOption(
        value=_scalar(item["value"], f"{label}.value"),
        label=item["label"],
        availability=_availability(item["availability"], f"{label}.availability"),
    )


def _control(value: object, index: int) -> ControlDefinition:
    label = f"control_schema[{index}]"
    item = _object(value, label)
    fields = (
        "control_id",
        "label",
        "group",
        "kind",
        "description",
        "authority",
        "default",
        "options",
        "min_value",
        "max_value",
    )
    _keys(item, label, required=fields)
    return ControlDefinition(
        control_id=item["control_id"],
        label=item["label"],
        group=item["group"],
        kind=item["kind"],
        description=item["description"],
        authority=item["authority"],
        default=_optional_scalar(item["default"], f"{label}.default"),
        options=tuple(
            _control_option(option, f"{label}.options[{option_index}]")
            for option_index, option in enumerate(_array(item["options"], f"{label}.options"))
        ),
        min_value=item["min_value"],
        max_value=item["max_value"],
    )


def _profile(value: object, index: int) -> ExecutionProfileDefinition:
    label = f"execution_profiles[{index}]"
    item = _object(value, label)
    fields = ("profile_id", "label", "description", "availability", "values")
    _keys(item, label, required=fields)
    values = _object(item["values"], f"{label}.values")
    return ExecutionProfileDefinition(
        profile_id=item["profile_id"],
        label=item["label"],
        description=item["description"],
        availability=_availability(item["availability"], f"{label}.availability"),
        values=tuple(
            ControlValue(
                _opaque(control_id, f"{label}.values control id"),
                _scalar(control_value, f"{label}.values[{control_id!r}]"),
            )
            for control_id, control_value in values.items()
        ),
    )


def _facility(value: object, index: int) -> RuntimeFacility:
    label = f"runtime_facilities[{index}]"
    item = _object(value, label)
    fields = ("facility_id", "label", "description", "observability", "management")
    _keys(item, label, required=fields)
    return RuntimeFacility(**{field: item[field] for field in fields})


def _permission_field(value: object, label: str) -> PermissionField:
    item = _object(value, label)
    fields = ("field_id", "label", "pointer", "format")
    _keys(item, label, required=fields)
    return PermissionField(**{field: item[field] for field in fields})


def _permission(value: object, index: int) -> PermissionPresentation:
    label = f"permission_presentations[{index}]"
    item = _object(value, label)
    fields = ("request_kind", "title", "layout", "fields")
    _keys(item, label, required=fields)
    return PermissionPresentation(
        request_kind=item["request_kind"],
        title=item["title"],
        layout=item["layout"],
        fields=tuple(
            _permission_field(field, f"{label}.fields[{field_index}]")
            for field_index, field in enumerate(_array(item["fields"], f"{label}.fields"))
        ),
    )


def _connect(value: object) -> ConnectMetadata:
    item = _object(value, "connect")
    fields = ("label", "help_text", "action")
    _keys(item, "connect", required=fields)
    return ConnectMetadata(**{field: item[field] for field in fields})


def descriptor_from_mapping(value: object) -> ProviderDescriptor:
    """Parse one strict JSON-shaped descriptor without executing any content."""

    item = _object(value, "provider descriptor")
    fields = (
        "schema_version",
        "descriptor_version",
        "runtime_id",
        "vendor_id",
        "agent_system_id",
        "relay_provider_id",
        "display",
        "authentication",
        "version_evidence",
        "default_selection",
        "control_schema",
        "supported_content_types",
        "execution_profiles",
        "runtime_facilities",
        "permission_presentations",
        "connect",
    )
    _keys(item, "provider descriptor", required=fields)
    content_types = _array(item["supported_content_types"], "supported_content_types")
    return ProviderDescriptor(
        schema_version=item["schema_version"],
        descriptor_version=item["descriptor_version"],
        runtime_id=item["runtime_id"],
        vendor_id=item["vendor_id"],
        agent_system_id=item["agent_system_id"],
        relay_provider_id=item["relay_provider_id"],
        display=_display(item["display"]),
        authentication=_evidence(item["authentication"], "authentication"),
        version_evidence=_evidence(item["version_evidence"], "version_evidence"),
        default_selection=_default_selection(item["default_selection"]),
        control_schema=tuple(
            _control(control, index)
            for index, control in enumerate(_array(item["control_schema"], "control_schema"))
        ),
        supported_content_types=tuple(
            _opaque(content_type, "supported content type")
            for content_type in content_types
        ),
        execution_profiles=tuple(
            _profile(profile, index)
            for index, profile in enumerate(
                _array(item["execution_profiles"], "execution_profiles")
            )
        ),
        runtime_facilities=tuple(
            _facility(facility, index)
            for index, facility in enumerate(
                _array(item["runtime_facilities"], "runtime_facilities")
            )
        ),
        permission_presentations=tuple(
            _permission(permission, index)
            for index, permission in enumerate(
                _array(item["permission_presentations"], "permission_presentations")
            )
        ),
        connect=_connect(item["connect"]),
    )


def _availability_mapping(value: Availability) -> dict[str, object]:
    return {"available": value.available, "reason": value.reason}


def descriptor_to_mapping(descriptor: ProviderDescriptor) -> dict[str, object]:
    """Return the canonical wire primitives for a validated descriptor."""

    def evidence(value: EvidenceDeclaration) -> dict[str, object]:
        return {
            "label": value.label,
            "authority": value.authority,
            "not_observable_label": value.not_observable_label,
        }

    return {
        "schema_version": descriptor.schema_version,
        "descriptor_version": descriptor.descriptor_version,
        "runtime_id": descriptor.runtime_id,
        "vendor_id": descriptor.vendor_id,
        "agent_system_id": descriptor.agent_system_id,
        "relay_provider_id": descriptor.relay_provider_id,
        "display": {
            "name": descriptor.display.name,
            "short_name": descriptor.display.short_name,
            "mark": descriptor.display.mark,
            "icon_token": descriptor.display.icon_token,
            "accent_token": descriptor.display.accent_token,
        },
        "authentication": evidence(descriptor.authentication),
        "version_evidence": evidence(descriptor.version_evidence),
        "default_selection": {
            "model": descriptor.default_selection.model,
            "effort": descriptor.default_selection.effort,
            "service_tier": descriptor.default_selection.service_tier,
            "execution_profile": descriptor.default_selection.execution_profile,
        },
        "control_schema": [
            {
                "control_id": control.control_id,
                "label": control.label,
                "group": control.group,
                "kind": control.kind,
                "description": control.description,
                "authority": control.authority,
                "default": control.default,
                "options": [
                    {
                        "value": option.value,
                        "label": option.label,
                        "availability": _availability_mapping(option.availability),
                    }
                    for option in control.options
                ],
                "min_value": control.min_value,
                "max_value": control.max_value,
            }
            for control in descriptor.control_schema
        ],
        "supported_content_types": list(descriptor.supported_content_types),
        "execution_profiles": [
            {
                "profile_id": profile.profile_id,
                "label": profile.label,
                "description": profile.description,
                "availability": _availability_mapping(profile.availability),
                "values": {
                    item.control_id: item.value for item in profile.values
                },
            }
            for profile in descriptor.execution_profiles
        ],
        "runtime_facilities": [
            {
                "facility_id": facility.facility_id,
                "label": facility.label,
                "description": facility.description,
                "observability": facility.observability,
                "management": facility.management,
            }
            for facility in descriptor.runtime_facilities
        ],
        "permission_presentations": [
            {
                "request_kind": presentation.request_kind,
                "title": presentation.title,
                "layout": presentation.layout,
                "fields": [
                    {
                        "field_id": field.field_id,
                        "label": field.label,
                        "pointer": field.pointer,
                        "format": field.format,
                    }
                    for field in presentation.fields
                ],
            }
            for presentation in descriptor.permission_presentations
        ],
        "connect": {
            "label": descriptor.connect.label,
            "help_text": descriptor.connect.help_text,
            "action": descriptor.connect.action,
        },
    }


def load_descriptor(path: Path) -> ProviderDescriptor:
    """Read one descriptor JSON file as inert data and validate it strictly."""

    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DescriptorError(f"cannot read provider descriptor {path.name!r}: {exc}") from exc
    return descriptor_from_mapping(value)


def validate_frozen_module(value: object) -> str:
    """Validate a reviewed module name without importing it."""

    text = _plain_text(value, "frozen module", max_length=200)
    if _MODULE_NAME.fullmatch(text) is None:
        raise DescriptorError("frozen module is not a Python module name")
    return text
