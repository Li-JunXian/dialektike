"""Runtime-truthful capability normalization and selection validation.

The native catalogs are the source of truth. This module contains no process
or network code, which keeps entitlement filtering and compatibility checks
deterministic and directly testable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from dialektike.domain import (
    AdapterCapabilities,
    AgentSystem,
    ModelCapability,
    ModelSelection,
    ServiceTier,
    Vendor,
)


class CapabilityError(ValueError):
    """A native catalog is malformed or a requested choice is unsupported."""


class RuntimeGateError(CapabilityError):
    """An authored pre-turn governance verdict that may be shown to Live.

    This type is deliberately narrower than ``CapabilityError``. Catalog
    parsing failures and provider diagnostics remain owner-only; only
    deterministic auth, version, and subscription gate aborts are promoted
    to this subtype by the live adapters.
    """

    def __init__(self, message: object):
        clean = str(message).strip()
        if not clean:
            raise ValueError("runtime gate verdict must not be empty")
        super().__init__(clean)


CODEX_FAST_DISABLED = (
    "Fast cannot be certified as subscription-only because the authenticated "
    "Codex credit state is unavailable or permits purchased-credit spending; "
    "axiom 1 forbids pay-as-you-go usage"
)
CLAUDE_FAST_DISABLED = (
    "Claude Fast is billed to extra usage from the first token; axiom 1 "
    "forbids pay-per-token usage"
)
CLAUDE_CREDITS_DISABLED = (
    "The Claude runtime marks this model as paid, credit-backed, or extra "
    "usage; axiom 1 permits the Claude Pro subscription only"
)
HIDDEN_MODEL_DISABLED = "Hidden runtime-internal model; not a participant choice"

_CLAUDE_EXTERNAL_USAGE_MARKERS = (
    "usage credit",
    "extra usage",
    "pay-as-you-go",
    "pay as you go",
    "additional paid usage",
    "billed separately",
    "outside your plan",
    "outside the plan",
    "not included in your plan",
    "not included with your plan",
)
_CLAUDE_EXTERNAL_USAGE_TRUE_FIELDS = (
    "requiresUsageCredits",
    "requiresCredits",
    "usesExtraUsage",
    "isPaid",
)
_CLAUDE_INCLUDED_FIELDS = ("includedInPlan", "isIncludedInPlan")


def _nonempty(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CapabilityError(f"runtime catalog entry has no {label}")
    return text


def _claude_external_usage(row: Mapping[str, Any], description: str) -> bool:
    """Conservatively identify Claude catalog entries outside the plan.

    The SDK currently communicates this mainly in human-readable model
    descriptions. Honor any structured entitlement fields as they appear,
    and recognize billing concepts rather than one exact marketing sentence.
    Unknown ordinary model descriptions remain usable; any positive external
    usage signal fails closed.
    """

    if any(row.get(field) is True for field in _CLAUDE_EXTERNAL_USAGE_TRUE_FIELDS):
        return True
    if any(row.get(field) is False for field in _CLAUDE_INCLUDED_FIELDS):
        return True
    billing_text = " ".join(
        str(value)
        for key, value in row.items()
        if key in {"billing", "billingType", "entitlement", "usageType"}
        and value is not None
    )
    searchable = f"{description} {billing_text}".casefold()
    return any(marker in searchable for marker in _CLAUDE_EXTERNAL_USAGE_MARKERS)


def codex_capabilities_from_model_list(
    rows: Iterable[Mapping[str, Any]],
    *,
    runtime_version: str,
    account_route: str,
    priority_within_subscription: bool = False,
) -> AdapterCapabilities:
    """Normalize complete, paginated Codex ``model/list`` data.

    Technical Fast tiers are selectable only when ``account/rateLimits/read``
    positively proves there is no purchased-credit or unlimited spend
    facility. Fast may consume the included plan allowance more quickly; that
    is still subscription usage. Hidden models remain visible to diagnostics
    but cannot be selected as dialectic participants.
    """

    models: list[ModelCapability] = []
    for row in rows:
        model_id = _nonempty(row.get("model") or row.get("id"), "model id")
        display_name = _nonempty(row.get("displayName") or model_id, "display name")
        efforts = tuple(
            _nonempty(item.get("reasoningEffort"), "reasoning effort")
            for item in (row.get("supportedReasoningEfforts") or ())
        )
        tiers = tuple(
            ServiceTier(
                tier_id=_nonempty(item.get("id"), "service tier id"),
                display_name=_nonempty(
                    item.get("name") or item.get("id"), "service tier name"
                ),
                description=str(item.get("description") or ""),
                available=priority_within_subscription,
                unavailable_reason=(
                    None
                    if priority_within_subscription
                    else CODEX_FAST_DISABLED
                ),
            )
            for item in (row.get("serviceTiers") or ())
        )
        hidden = bool(row.get("hidden"))
        models.append(
            ModelCapability(
                model_id=model_id,
                display_name=display_name,
                resolved_model_id=model_id,
                efforts=efforts,
                service_tiers=tiers,
                is_default=bool(row.get("isDefault")),
                authority="codex app-server model/list",
                available=not hidden,
                unavailable_reason=HIDDEN_MODEL_DISABLED if hidden else None,
            )
        )
    if not models:
        raise CapabilityError("codex model/list returned no models")
    return AdapterCapabilities(
        adapter_id=AgentSystem.CODEX.value,
        vendor=Vendor.OPENAI,
        agent_system=AgentSystem.CODEX,
        models=tuple(models),
        runtime_version=_nonempty(runtime_version, "runtime version"),
        account_route=_nonempty(account_route, "account route"),
    )


def claude_capabilities_from_server_info(
    info: Mapping[str, Any],
    *,
    runtime_version: str,
    account_route: str,
) -> AdapterCapabilities:
    """Normalize the Claude Agent SDK initialization model catalog."""

    models: list[ModelCapability] = []
    for row in info.get("models") or ():
        selector = _nonempty(row.get("value"), "Claude model selector")
        display_name = _nonempty(
            row.get("displayName") or selector, "Claude model display name"
        )
        description = str(row.get("description") or "")
        requires_credits = _claude_external_usage(row, description)
        tiers: tuple[ServiceTier, ...] = ()
        if row.get("supportsFastMode") is True:
            tiers = (
                ServiceTier(
                    tier_id="fast",
                    display_name="Fast",
                    description="Native Claude Code Fast mode",
                    available=False,
                    unavailable_reason=CLAUDE_FAST_DISABLED,
                ),
            )
        models.append(
            ModelCapability(
                model_id=selector,
                display_name=display_name,
                resolved_model_id=(
                    str(row.get("resolvedModel")).strip()
                    if row.get("resolvedModel")
                    else None
                ),
                efforts=tuple(
                    _nonempty(item, "Claude effort")
                    for item in (row.get("supportedEffortLevels") or ())
                ),
                service_tiers=tiers,
                is_default=selector == "default",
                # Claude's `default` selector is a moving runtime alias, not a
                # model version Live can explicitly pin for a topic.
                explicit_selectable=selector != "default",
                authority="Claude Agent SDK get_server_info().models",
                available=not requires_credits,
                unavailable_reason=(
                    CLAUDE_CREDITS_DISABLED if requires_credits else None
                ),
            )
        )
    if not models:
        raise CapabilityError("Claude SDK server info returned no models")
    return AdapterCapabilities(
        adapter_id=AgentSystem.CLAUDE_CODE.value,
        vendor=Vendor.ANTHROPIC,
        agent_system=AgentSystem.CLAUDE_CODE,
        models=tuple(models),
        runtime_version=_nonempty(runtime_version, "runtime version"),
        account_route=_nonempty(account_route, "account route"),
    )


def validate_selection(
    capabilities: AdapterCapabilities,
    selection: ModelSelection,
) -> ModelCapability:
    """Return the selected capability or fail before a substantive turn.

    ``None`` model means the catalog's declared default. Every explicit model,
    effort and service tier must be present and policy-available. Features are
    rejected until the runtime advertises a separately verifiable feature
    catalog; this prevents labels such as ``workflows`` becoming invented wire
    options.
    """

    if selection.model_id is None:
        capability = next(
            (model for model in capabilities.models if model.is_default), None
        )
        if capability is None:
            raise CapabilityError(
                f"{capabilities.adapter_id} catalog declares no default model"
            )
    else:
        capability = next(
            (
                model
                for model in capabilities.models
                if model.model_id == selection.model_id
            ),
            None,
        )
        if capability is None:
            raise CapabilityError(
                f"{capabilities.adapter_id} does not advertise model "
                f"{selection.model_id!r}"
            )
    if not capability.available:
        raise CapabilityError(
            f"model {capability.model_id!r} is unavailable: "
            f"{capability.unavailable_reason}"
        )
    if selection.effort is not None and selection.effort not in capability.efforts:
        raise CapabilityError(
            f"model {capability.model_id!r} does not advertise effort "
            f"{selection.effort!r}; supported={list(capability.efforts)!r}"
        )
    if selection.service_tier is not None:
        tier = next(
            (
                item
                for item in capability.service_tiers
                if item.tier_id == selection.service_tier
            ),
            None,
        )
        if tier is None:
            raise CapabilityError(
                f"model {capability.model_id!r} does not advertise service tier "
                f"{selection.service_tier!r}"
            )
        if not tier.available:
            raise CapabilityError(
                f"service tier {tier.tier_id!r} is unavailable: "
                f"{tier.unavailable_reason}"
            )
    if selection.features:
        raise CapabilityError(
            "runtime exposes no selectable orchestration-feature catalog; "
            f"cannot verify {list(selection.features)!r}"
        )
    return capability
