"""Deterministic M2 capability and billing-policy invariants.

Run: ``./venv/bin/python tests/m2_adapter_invariants.py``.
No runtime is contacted and no subscription turn is consumed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dialektike.adapters.capabilities import (  # noqa: E402
    CapabilityError,
    claude_capabilities_from_server_info,
    codex_capabilities_from_model_list,
    validate_selection,
)
from dialektike.adapters.base import AdapterError  # noqa: E402
from dialektike.adapters.codex import _subscription_rate_limits  # noqa: E402
from dialektike.adapters.codex import (  # noqa: E402
    CODEX_COMPACTION_AUTHORITY,
    _M2AppServerClient,
    _codex_compaction_evidence,
    _start_selected_thread,
)
from dialektike.adapters.claude import (  # noqa: E402
    CLAUDE_EPHEMERAL_ARGS,
    _render_claude_reply,
)
from dialektike.domain import ModelSelection  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("OK    " if condition else "FAIL  ") + name)
    if not condition:
        FAILS.append(name)


def rejects(name: str, function) -> None:
    try:
        function()
    except CapabilityError:
        check(name, True)
    else:
        check(name, False)


codex = codex_capabilities_from_model_list(
    [
        {
            "id": "gpt-5.6-sol",
            "model": "gpt-5.6-sol",
            "displayName": "GPT-5.6-Sol",
            "hidden": False,
            "isDefault": True,
            "supportedReasoningEfforts": [
                {"reasoningEffort": "low"},
                {"reasoningEffort": "ultra"},
            ],
            "serviceTiers": [
                {
                    "id": "priority",
                    "name": "Fast",
                    "description": "1.5x speed, increased usage",
                }
            ],
        },
        {
            "id": "codex-auto-review",
            "displayName": "Codex Auto Review",
            "hidden": True,
            "supportedReasoningEfforts": [{"reasoningEffort": "medium"}],
        },
    ],
    runtime_version="0.145.0",
    account_route="chatgpt:plus",
)

sol = validate_selection(
    codex, ModelSelection(model_id="gpt-5.6-sol", effort="ultra")
)
check("Codex Sol+Ultra accepted when live catalog advertises both",
      sol.model_id == "gpt-5.6-sol" and sol.available)
check("Codex Fast retained but policy-disabled",
      sol.service_tiers[0].tier_id == "priority"
      and sol.service_tiers[0].available is False
      and "axiom 1" in (sol.service_tiers[0].unavailable_reason or ""))
rejects(
    "Codex Fast cannot pass subscription-only validation",
    lambda: validate_selection(
        codex,
        ModelSelection(
            model_id="gpt-5.6-sol", effort="ultra", service_tier="priority"
        ),
    ),
)


class _ThreadClient:
    def __init__(self):
        self.params = None
        self.model_label = "codex"

    def request(self, method, params):
        check("Codex creates a native thread through thread/start", method == "thread/start")
        self.params = params
        return 1

    def response_for(self, request_id):
        return {
            "result": {
                "thread": {"id": "opaque-thread", "ephemeral": True},
                "modelProvider": "openai",
                "model": "gpt-5.6-sol",
                "serviceTier": "standard",
            }
        }


thread_client = _ThreadClient()
_start_selected_thread(
    thread_client,
    SimpleNamespace(paths=SimpleNamespace(workspace_dir="/tmp/workspace")),
    "gpt-5.6-sol",
    "standard",
)
check(
    "Codex provider session is explicitly ephemeral",
    thread_client.params is not None
    and thread_client.params.get("ephemeral") is True,
)


class _NonEphemeralThreadClient(_ThreadClient):
    def response_for(self, request_id):
        response = super().response_for(request_id)
        response["result"]["thread"]["ephemeral"] = False
        return response


try:
    _start_selected_thread(
        _NonEphemeralThreadClient(),
        SimpleNamespace(paths=SimpleNamespace(workspace_dir="/tmp/workspace")),
        "gpt-5.6-sol",
        "standard",
    )
except AdapterError:
    check("Codex rejects a non-ephemeral thread/start echo", True)
else:
    check("Codex rejects a non-ephemeral thread/start echo", False)


class _ActivityBridge:
    def __init__(self):
        self.states = []

    def publish(self, request, message, *, activity, state):
        self.states.append(state)


activity_bridge = _ActivityBridge()
activity_client = object.__new__(_M2AppServerClient)
activity_client._m2_request = object()
activity_client._m2_activity_bridge = activity_bridge
activity_client._publish_activity("Running a command", activity="item-started")
check(
    "Codex native activity uses the frontend running-state vocabulary",
    activity_bridge.states == ["running"],
)
compaction_evidence = dict(
    _codex_compaction_evidence(
        SimpleNamespace(
            item_events=[
                {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {"id": "compact-1", "type": "contextCompaction"},
                },
                {
                    "threadId": "other-thread",
                    "turnId": "turn-1",
                    "item": {"id": "compact-2", "type": "contextCompaction"},
                },
            ]
        ),
        "thread-1",
        "turn-1",
    )
)
check(
    "Codex observes current contextCompaction items as turn-only evidence",
    compaction_evidence == {
        "native_compaction_event_count": "1",
        "native_compaction_authority": CODEX_COMPACTION_AUTHORITY,
        "native_compaction_topic_checkpoint_mutated": "false",
    },
)
check(
    "Claude Code provider session uses the native no-persistence flag",
    CLAUDE_EPHEMERAL_ARGS == {"no-session-persistence": None},
)
check(
    "Claude TextBlock boundaries remain Markdown block boundaries",
    _render_claude_reply(["# Heading", "- one\n- two"])
    == "# Heading\n\n- one\n- two",
)

codex_without_credit_spend = codex_capabilities_from_model_list(
    [
        {
            "id": "gpt-5.6-sol",
            "displayName": "GPT-5.6-Sol",
            "isDefault": True,
            "supportedReasoningEfforts": [
                {"reasoningEffort": "ultra"},
            ],
            "serviceTiers": [
                {
                    "id": "priority",
                    "name": "Fast",
                    "description": "1.5x speed, increased usage",
                }
            ],
        }
    ],
    runtime_version="0.145.0",
    account_route="chatgpt:plus",
    priority_within_subscription=True,
)
check(
    "Codex Fast is selectable when no purchased-credit spend can occur",
    validate_selection(
        codex_without_credit_spend,
        ModelSelection(
            model_id="gpt-5.6-sol",
            effort="ultra",
            service_tier="priority",
        ),
    ).service_tiers[0].available,
)


class _RateLimitClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def request(self, method, params):
        check(
            "Codex billing guard uses account/rateLimits/read before a turn",
            method == "account/rateLimits/read" and params == {},
        )
        return 1

    def response_for(self, request_id):
        return {"result": {"rateLimits": self.snapshot}}


snapshot, credit_spend, reached = _subscription_rate_limits(
    _RateLimitClient(
        {
            "planType": "plus",
            "credits": {
                "hasCredits": False,
                "unlimited": False,
                "balance": "0",
            },
            "rateLimitReachedType": None,
        }
    ),
    expected_plan_type="plus",
)
check(
    "Codex no-credit snapshot certifies included-plan Fast",
    snapshot["planType"] == "plus"
    and credit_spend is False
    and reached is None,
)

_, credit_spend, _ = _subscription_rate_limits(
    _RateLimitClient(
        {
            "planType": "plus",
            "credits": {
                "hasCredits": True,
                "unlimited": False,
                "balance": "10",
            },
            "rateLimitReachedType": None,
        }
    ),
    expected_plan_type="plus",
)
check(
    "Codex purchased-credit availability is detected for Fast policy",
    credit_spend is True,
)
rejects(
    "hidden Codex internal model cannot be a participant",
    lambda: validate_selection(
        codex, ModelSelection(model_id="codex-auto-review", effort="medium")
    ),
)
rejects(
    "unsupported Codex effort fails before a turn",
    lambda: validate_selection(
        codex, ModelSelection(model_id="gpt-5.6-sol", effort="imaginary")
    ),
)


claude = claude_capabilities_from_server_info(
    {
        "models": [
            {
                "value": "default",
                "displayName": "Default",
                "resolvedModel": "claude-sonnet-5",
                "supportedEffortLevels": ["low", "xhigh", "max"],
                "supportsFastMode": True,
            },
            {
                "value": "opus",
                "displayName": "Opus",
                "resolvedModel": "claude-opus-5",
                "supportedEffortLevels": ["low", "xhigh", "max"],
                "supportsFastMode": True,
            },
            {
                "value": "claude-fable-5[1m]",
                "displayName": "Fable",
                "resolvedModel": "claude-fable-5",
                "description": "Fable 5 · Requires usage credits",
                "supportedEffortLevels": ["low", "xhigh", "max"],
            },
            {
                "value": "credit-wording-variant",
                "displayName": "Credit wording variant",
                "resolvedModel": "claude-credit-variant",
                "description": "Uses extra usage from the first token",
                "supportedEffortLevels": ["low"],
            },
            {
                "value": "haiku",
                "displayName": "Haiku",
                "resolvedModel": "claude-haiku-4-5-20251001",
            },
        ]
    },
    runtime_version="sdk 0.2.116 / claude-code 2.1.220",
    account_route="claude.ai:firstParty:pro",
)

opus = validate_selection(
    claude, ModelSelection(model_id="opus", effort="xhigh")
)
check("Claude Opus selector retains the catalog-resolved identity",
      opus.model_id == "opus" and opus.resolved_model_id == "claude-opus-5")
check("Claude native default comes from catalog, not hard coding",
      validate_selection(claude, ModelSelection()).model_id == "default")
check(
    "Claude moving default alias is not an explicit desktop model version",
    claude.models[0].model_id == "default"
    and claude.models[0].explicit_selectable is False
    and next(model for model in claude.models if model.model_id == "opus").explicit_selectable is True,
)
rejects(
    "Claude Fast cannot pass subscription-only validation",
    lambda: validate_selection(
        claude,
        ModelSelection(model_id="opus", effort="xhigh", service_tier="fast"),
    ),
)
rejects(
    "Claude credit-required model is disabled",
    lambda: validate_selection(
        claude, ModelSelection(model_id="claude-fable-5[1m]", effort="xhigh")
    ),
)
rejects(
    "Claude external-usage wording variants fail closed",
    lambda: validate_selection(
        claude,
        ModelSelection(model_id="credit-wording-variant", effort="low"),
    ),
)
rejects(
    "effort cannot be invented for a model that advertises none",
    lambda: validate_selection(
        claude, ModelSelection(model_id="haiku", effort="xhigh")
    ),
)
rejects(
    "Ultracode/workflows label cannot masquerade as a wire feature",
    lambda: validate_selection(
        claude,
        ModelSelection(model_id="opus", effort="xhigh", features=("workflows",)),
    ),
)


if FAILS:
    print(f"\nM2 ADAPTER INVARIANTS — {len(FAILS)} failure(s): {FAILS}")
    raise SystemExit(1)
print("\nM2 ADAPTER INVARIANTS — all hold")
