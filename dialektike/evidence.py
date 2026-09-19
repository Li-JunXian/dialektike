"""Read-only, non-secret evidence summaries for the M2 desktop.

The owner-only run directory remains the source of truth.  This module reads
that directory only after provider adapters have closed, verifies the decision
chain before deriving governance counts, and projects a deliberately narrow
summary for the WebView.  Raw payload contents and filesystem paths never
cross this boundary.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.broker import ChainVerificationError, ChainedLog
from dialektike.domain import AdapterCapabilities, RunConfig, RunOutcome


SUMMARY_SCHEMA_VERSION = 1
MAX_SAVED_SUMMARY_BYTES = 512 * 1024
MAX_SAVED_DECISION_CHAIN_BYTES = 64 * 1024 * 1024
_MAX_SAFE_INTEGER = (1 << 53) - 1
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_SAFE_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_PLAN_WARNING = (
    "The runtime reported a subscription-usage boundary; the run stopped "
    "safely and full details remain owner-only."
)
_RATE_EVIDENCE_KEYS = (
    "rate_limit_event_count",
    # Transitional M2 spelling. New adapters use the generic key above.
    "rate_limit_snapshot_count",
)


class EvidenceSummaryIntegrityError(ValueError):
    """A persisted WebView-safe summary could not be trusted for replay."""


def _exact_keys(
    value: Any,
    keys: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise EvidenceSummaryIntegrityError(f"{label} has an invalid shape")
    return value


def _text(value: Any, label: str, *, limit: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > limit
    ):
        raise EvidenceSummaryIntegrityError(f"{label} is invalid")
    return value


def _nullable_text(value: Any, label: str, *, limit: int = 1024) -> str | None:
    if value is None:
        return None
    return _text(value, label, limit=limit)


def _count(value: Any, label: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > _MAX_SAFE_INTEGER
    ):
        raise EvidenceSummaryIntegrityError(f"{label} is invalid")
    return value


def _count_map(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or len(value) > 256:
        raise EvidenceSummaryIntegrityError(f"{label} is invalid")
    result: dict[str, int] = {}
    for key, item in value.items():
        result[_text(key, f"{label} key", limit=96)] = _count(
            item, f"{label}.{key}"
        )
    return result


def _validated_saved_summary(value: Any, run_id: str) -> dict[str, Any]:
    """Validate the complete inert summary schema before replaying it.

    Exact key sets are intentional: a compromised or newer summary cannot
    smuggle a raw filename, path, payload, or future unreviewed field into the
    WebView through this backwards-looking command.
    """

    summary = _exact_keys(
        value,
        {
            "schema_version",
            "run_id",
            "run_status",
            "environment_gate",
            "runtime_gates",
            "rate_limits",
            "governance",
            "raw_capture",
            "decision_chain",
            "event_log_readable",
        },
        "evidence summary",
    )
    if summary["schema_version"] != SUMMARY_SCHEMA_VERSION:
        raise EvidenceSummaryIntegrityError("unsupported evidence summary schema")
    if _text(summary["run_id"], "run_id", limit=120) != run_id:
        raise EvidenceSummaryIntegrityError("evidence summary run binding failed")
    if summary["run_status"] not in {
        "created",
        "running",
        "paused",
        "cancelling",
        "cancelled",
        "completed",
        "failed",
    }:
        raise EvidenceSummaryIntegrityError("run_status is invalid")

    environment = _exact_keys(
        summary["environment_gate"],
        {"verified", "policy", "kept", "dropped_count"},
        "environment_gate",
    )
    if not isinstance(environment["verified"], bool):
        raise EvidenceSummaryIntegrityError("environment_gate.verified is invalid")
    policy = _nullable_text(environment["policy"], "environment_gate.policy")
    kept = environment["kept"]
    if (
        not isinstance(kept, list)
        or len(kept) > 128
        or any(
            not isinstance(item, str)
            or not item
            or len(item.encode("utf-8")) > 128
            for item in kept
        )
    ):
        raise EvidenceSummaryIntegrityError("environment_gate.kept is invalid")
    dropped = environment["dropped_count"]
    if dropped is not None:
        _count(dropped, "environment_gate.dropped_count")
    if environment["verified"] != (policy == "allowlist" and dropped is not None):
        raise EvidenceSummaryIntegrityError("environment gate claim is inconsistent")

    runtime_gates = summary["runtime_gates"]
    if not isinstance(runtime_gates, list) or len(runtime_gates) > 64:
        raise EvidenceSummaryIntegrityError("runtime_gates is invalid")
    runtime_ids: set[str] = set()
    for index, raw_gate in enumerate(runtime_gates):
        gate = _exact_keys(
            raw_gate,
            {
                "runtime_id",
                "catalog_verified",
                "account_route",
                "runtime_version",
                "turn_revalidated_count",
                "model_providers",
            },
            f"runtime_gates[{index}]",
        )
        runtime_id = _text(gate["runtime_id"], "runtime_id", limit=96)
        if runtime_id in runtime_ids:
            raise EvidenceSummaryIntegrityError("runtime gate ids are duplicated")
        runtime_ids.add(runtime_id)
        if not isinstance(gate["catalog_verified"], bool):
            raise EvidenceSummaryIntegrityError("catalog_verified is invalid")
        _text(gate["account_route"], "account_route", limit=512)
        _nullable_text(gate["runtime_version"], "runtime_version", limit=512)
        _count(gate["turn_revalidated_count"], "turn_revalidated_count")
        providers = gate["model_providers"]
        if (
            not isinstance(providers, list)
            or len(providers) > 64
            or any(
                not isinstance(item, str)
                or not item
                or len(item.encode("utf-8")) > 256
                for item in providers
            )
        ):
            raise EvidenceSummaryIntegrityError("model_providers is invalid")

    rates = _exact_keys(
        summary["rate_limits"],
        {
            "observed_event_count",
            "by_runtime",
            "warning_count",
            "warnings",
            "capture_parse_failures",
        },
        "rate_limits",
    )
    observed = _count(rates["observed_event_count"], "observed_event_count")
    by_runtime = _count_map(rates["by_runtime"], "by_runtime")
    if observed != sum(by_runtime.values()):
        raise EvidenceSummaryIntegrityError("rate-limit counts are inconsistent")
    warning_count = _count(rates["warning_count"], "warning_count")
    warnings = rates["warnings"]
    if not isinstance(warnings, list) or len(warnings) > 256:
        raise EvidenceSummaryIntegrityError("warnings is invalid")
    if warning_count != len(warnings):
        raise EvidenceSummaryIntegrityError("warning_count is inconsistent")
    for index, raw_warning in enumerate(warnings):
        warning = _exact_keys(
            raw_warning, {"runtime_id", "message"}, f"warnings[{index}]"
        )
        _text(warning["runtime_id"], "warning runtime_id", limit=96)
        _text(warning["message"], "warning message", limit=2048)
    _count(rates["capture_parse_failures"], "capture_parse_failures")

    decision = _exact_keys(
        summary["decision_chain"],
        {"verified", "record_count", "head_sha256", "error"},
        "decision_chain",
    )
    if not isinstance(decision["verified"], bool):
        raise EvidenceSummaryIntegrityError("decision_chain.verified is invalid")
    record_count = decision["record_count"]
    if record_count is not None:
        _count(record_count, "decision_chain.record_count")
    head = decision["head_sha256"]
    if head is not None and (
        not isinstance(head, str) or _SAFE_HEX_SHA256.fullmatch(head) is None
    ):
        raise EvidenceSummaryIntegrityError("decision chain head is invalid")
    error = _nullable_text(decision["error"], "decision_chain.error", limit=2048)
    if decision["verified"]:
        if record_count is None or error is not None:
            raise EvidenceSummaryIntegrityError("verified decision chain is inconsistent")
        if (record_count == 0) != (head is None):
            raise EvidenceSummaryIntegrityError("decision chain head is inconsistent")
    elif record_count is not None or head is not None or error is None:
        raise EvidenceSummaryIntegrityError("failed decision chain is inconsistent")

    governance = _exact_keys(
        summary["governance"],
        {
            "derived_from_verified_chain",
            "permission_decisions",
            "audit_counts",
        },
        "governance",
    )
    if governance["derived_from_verified_chain"] is not decision["verified"]:
        raise EvidenceSummaryIntegrityError("governance provenance is inconsistent")
    if decision["verified"]:
        permissions = _exact_keys(
            governance["permission_decisions"],
            {"allow", "deny", "total"},
            "permission_decisions",
        )
        allow = _count(permissions["allow"], "permission_decisions.allow")
        deny = _count(permissions["deny"], "permission_decisions.deny")
        if _count(permissions["total"], "permission_decisions.total") != allow + deny:
            raise EvidenceSummaryIntegrityError("permission counts are inconsistent")
        _count_map(governance["audit_counts"], "audit_counts")
    elif (
        governance["permission_decisions"] is not None
        or governance["audit_counts"] is not None
    ):
        raise EvidenceSummaryIntegrityError("unverified governance must be withheld")

    raw = _exact_keys(
        summary["raw_capture"],
        {
            "file_count",
            "total_bytes",
            "turns_with_capture",
            "by_category",
            "contents_exposed",
        },
        "raw_capture",
    )
    _count(raw["file_count"], "raw_capture.file_count")
    _count(raw["total_bytes"], "raw_capture.total_bytes")
    _count(raw["turns_with_capture"], "raw_capture.turns_with_capture")
    _count_map(raw["by_category"], "raw_capture.by_category")
    if raw["contents_exposed"] is not False:
        raise EvidenceSummaryIntegrityError("raw contents may not cross the boundary")
    if not isinstance(summary["event_log_readable"], bool):
        raise EvidenceSummaryIntegrityError("event_log_readable is invalid")
    return json.loads(json.dumps(summary, ensure_ascii=False, allow_nan=False))


def _reject_json_constant(value: str) -> None:
    raise EvidenceSummaryIntegrityError(f"invalid JSON constant {value!r}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceSummaryIntegrityError("duplicate JSON object key")
        result[key] = value
    return result


def load_saved_evidence_summary(runs_root: Path, run_id: str) -> dict[str, Any]:
    """Load one closed run's bounded summary without exposing its location."""

    if not isinstance(run_id, str) or _SAFE_RUN_ID.fullmatch(run_id) is None:
        raise EvidenceSummaryIntegrityError("unsafe evidence run identifier")
    runs_path = Path(runs_root)
    root_fd = -1
    run_fd = -1
    summary_fd = -1
    try:
        run_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            run_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            run_flags |= os.O_NOFOLLOW
        root_fd = os.open(runs_path, run_flags)
        root_stat = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or root_stat.st_uid != os.geteuid()
            or stat.S_IMODE(root_stat.st_mode) & 0o077
        ):
            raise EvidenceSummaryIntegrityError("unsafe evidence store directory")
        run_fd = os.open(run_id, run_flags, dir_fd=root_fd)
        run_stat = os.fstat(run_fd)
        if (
            not stat.S_ISDIR(run_stat.st_mode)
            or run_stat.st_uid != os.geteuid()
            or stat.S_IMODE(run_stat.st_mode) & 0o077
        ):
            raise EvidenceSummaryIntegrityError("unsafe evidence run directory")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        summary_fd = os.open("evidence_summary.json", flags, dir_fd=run_fd)
        file_stat = os.fstat(summary_fd)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_uid != os.geteuid()
            or stat.S_IMODE(file_stat.st_mode) & 0o077
        ):
            raise EvidenceSummaryIntegrityError("evidence summary is not owner-only")
        if file_stat.st_size < 2 or file_stat.st_size > MAX_SAVED_SUMMARY_BYTES:
            raise EvidenceSummaryIntegrityError("evidence summary size is invalid")
        chunks: list[bytes] = []
        remaining = file_stat.st_size
        while remaining:
            chunk = os.read(summary_fd, min(64 * 1024, remaining))
            if not chunk:
                raise EvidenceSummaryIntegrityError(
                    "evidence summary changed while reading"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(summary_fd, 1):
            raise EvidenceSummaryIntegrityError(
                "evidence summary changed while reading"
            )
        encoded = b"".join(chunks)
        revalidated_chain, revalidated_governance = (
            _read_verified_decision_projection(run_fd)
        )
    except EvidenceSummaryIntegrityError:
        raise
    except OSError as exc:
        raise EvidenceSummaryIntegrityError("evidence summary is unavailable") from exc
    finally:
        if summary_fd >= 0:
            os.close(summary_fd)
        if run_fd >= 0:
            os.close(run_fd)
        if root_fd >= 0:
            os.close(root_fd)
    try:
        value = json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except EvidenceSummaryIntegrityError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceSummaryIntegrityError("evidence summary is malformed") from exc
    summary = _validated_saved_summary(value, run_id)
    if (
        summary["decision_chain"] != revalidated_chain
        or summary["governance"] != revalidated_governance
    ):
        raise EvidenceSummaryIntegrityError(
            "saved governance does not match the verified decision chain"
        )
    return summary


def _read_events(path: Path) -> tuple[list[dict[str, Any]], bool]:
    try:
        return (
            [
                json.loads(line)
                for line in path.read_text().splitlines()
                if line.strip()
            ],
            True,
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [], False


def _regular_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for candidate in root.rglob("*"):
        try:
            mode = candidate.lstat().st_mode
        except OSError:
            continue
        if stat.S_ISREG(mode):
            files.append(candidate)
    return files


def _raw_category(path: Path) -> str:
    name = path.name
    if name.startswith("relay-") and path.suffix == ".json":
        return "permission-payload"
    if path.suffix in {".json", ".jsonl"}:
        return "runtime-events"
    if (
        name.endswith(".log")
        or "malformed" in name
        or "traceback" in name
    ):
        return "runtime-diagnostic"
    return "other"


def _raw_inventory(raw_dir: Path) -> tuple[dict[str, Any], list[Path]]:
    files = _regular_files(raw_dir)
    by_category: Counter[str] = Counter()
    total_bytes = 0
    turn_names: set[str] = set()
    for path in files:
        by_category[_raw_category(path)] += 1
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
        if path.parent.name.startswith("turn-"):
            turn_names.add(path.parent.name)
    return (
        {
            "file_count": len(files),
            "total_bytes": total_bytes,
            "turns_with_capture": len(turn_names),
            "by_category": dict(sorted(by_category.items())),
            # This is an inventory only. The WebView never receives names,
            # paths, hashes embedded in names, or file contents.
            "contents_exposed": False,
        },
        files,
    )


def _turn_number(path: Path) -> int | None:
    name = path.parent.name
    if not name.startswith("turn-"):
        return None
    try:
        return int(name.removeprefix("turn-"))
    except ValueError:
        return None


def _raw_rate_counts(
    files: list[Path],
    runtime_by_turn: Mapping[int, str],
) -> tuple[Counter[str], set[tuple[str, int]], int]:
    counts: Counter[str] = Counter()
    captured_turns: set[tuple[str, int]] = set()
    parse_failures = 0
    def observations(value: Any) -> int:
        if isinstance(value, list):
            return sum(observations(item) for item in value)
        if not isinstance(value, dict):
            return 0
        direct = int(value.get("type") == "rate_limit")
        direct += int(value.get("method") == "account/rateLimits/updated")
        result = value.get("result")
        direct += int(
            isinstance(result, dict)
            and isinstance(result.get("rateLimits"), dict)
        )
        return direct

    for path in files:
        turn_number = _turn_number(path)
        runtime_id = runtime_by_turn.get(turn_number) if turn_number is not None else None
        if runtime_id is None or path.suffix not in {".json", ".jsonl"}:
            continue
        try:
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("runtime capture exceeds evidence read limit")
            text = path.read_text()
            records = (
                [json.loads(line) for line in text.splitlines() if line.strip()]
                if path.suffix == ".jsonl"
                else json.loads(text)
            )
            counts[runtime_id] += observations(records)
            captured_turns.add((runtime_id, turn_number))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            parse_failures += 1
    return counts, captured_turns, parse_failures


def _event_rate_summary(
    events: list[dict[str, Any]],
    raw_counts: Counter[str],
    raw_turns: set[tuple[str, int]],
    parse_failures: int,
) -> dict[str, Any]:
    counts = Counter(raw_counts)
    warnings: list[dict[str, str]] = []
    for event in events:
        kind = event.get("kind")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if kind == "plan_warning":
            runtime_id = str(payload.get("adapter_id") or "unknown")
            warnings.append(
                {
                    "runtime_id": runtime_id,
                    "message": SAFE_PLAN_WARNING,
                }
            )
            continue
        if kind != "turn_completed":
            continue
        turn = payload.get("turn")
        evidence = payload.get("evidence")
        if not isinstance(turn, dict) or not isinstance(evidence, list):
            continue
        runtime_id = str(turn.get("adapter_id") or "")
        turn_number = turn.get("turn_number")
        if (
            not runtime_id
            or not isinstance(turn_number, int)
            or (runtime_id, turn_number) in raw_turns
        ):
            continue
        pairs = {
            str(item[0]): str(item[1])
            for item in evidence
            if isinstance(item, list) and len(item) == 2
        }
        try:
            counts[runtime_id] += max(
                int(pairs.get(key, "0")) for key in _RATE_EVIDENCE_KEYS
            )
        except ValueError:
            parse_failures += 1
    return {
        "observed_event_count": sum(counts.values()),
        "by_runtime": dict(sorted(counts.items())),
        "warning_count": len(warnings),
        "warnings": warnings,
        "capture_parse_failures": parse_failures,
    }


def _decision_summary(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        # An absent path is not evidence of an empty, verified chain.
        # ChainedLog intentionally treats a new path as an empty ledger, so
        # the read-only evidence projection must establish that the run
        # actually created a regular decision log before invoking it.
        if not stat.S_ISREG(path.lstat().st_mode):
            raise OSError("decision chain is not a regular file")
        records = ChainedLog(path).verified_records()
    except (
        ChainVerificationError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ):
        return (
            {
                "verified": False,
                "record_count": None,
                "head_sha256": None,
                "error": "Decision chain failed verification.",
            },
            {
                "derived_from_verified_chain": False,
                "permission_decisions": None,
                "audit_counts": None,
            },
        )

    return _decision_projection(records)


def _decision_projection(
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    decisions = Counter(
        str(record.get("decision"))
        for record in records
        if record.get("kind") == "permission_decision"
        and record.get("decision") in {"allow", "deny"}
    )
    audit_counts = Counter(
        str(record.get("kind"))
        for record in records
        if record.get("kind") != "permission_decision"
    )
    return (
        {
            "verified": True,
            "record_count": len(records),
            "head_sha256": records[-1].get("hash") if records else None,
            "error": None,
        },
        {
            "derived_from_verified_chain": True,
            "permission_decisions": {
                "allow": decisions["allow"],
                "deny": decisions["deny"],
                "total": decisions["allow"] + decisions["deny"],
            },
            "audit_counts": dict(sorted(audit_counts.items())),
        },
    )


def _read_verified_decision_projection(
    run_fd: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Revalidate the exact owner-only ledger in an already-open run dir."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    decision_fd = -1
    try:
        decision_fd = os.open("decisions.jsonl", flags, dir_fd=run_fd)
        file_stat = os.fstat(decision_fd)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_uid != os.geteuid()
            or stat.S_IMODE(file_stat.st_mode) & 0o077
            or file_stat.st_size > MAX_SAVED_DECISION_CHAIN_BYTES
        ):
            raise EvidenceSummaryIntegrityError(
                "decision chain is not an owner-only bounded file"
            )
        fcntl.flock(decision_fd, fcntl.LOCK_SH)
        try:
            chunks: list[bytes] = []
            remaining = file_stat.st_size
            while remaining:
                chunk = os.read(decision_fd, min(64 * 1024, remaining))
                if not chunk:
                    raise EvidenceSummaryIntegrityError(
                        "decision chain changed while reading"
                    )
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(decision_fd, 1):
                raise EvidenceSummaryIntegrityError(
                    "decision chain changed while reading"
                )
        finally:
            fcntl.flock(decision_fd, fcntl.LOCK_UN)
    except EvidenceSummaryIntegrityError:
        raise
    except OSError as exc:
        raise EvidenceSummaryIntegrityError("decision chain is unavailable") from exc
    finally:
        if decision_fd >= 0:
            os.close(decision_fd)
    try:
        text = b"".join(chunks).decode("utf-8")
        lines = text.splitlines(keepends=True)
        ok, _, _ = ChainedLog._verify_lines(lines)
        if not ok:
            raise EvidenceSummaryIntegrityError("decision chain failed verification")
        records = [json.loads(line) for line in lines if line.strip()]
    except EvidenceSummaryIntegrityError:
        raise
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise EvidenceSummaryIntegrityError("decision chain is malformed") from exc
    return _decision_projection(records)


def build_evidence_summary(
    *,
    config: RunConfig,
    outcome: RunOutcome,
    catalogs: Mapping[str, AdapterCapabilities],
    environment_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive a bounded summary from one closed run and verified catalogs."""

    run_path = Path(outcome.run_path)
    events, events_readable = _read_events(run_path / "events.jsonl")
    raw_inventory, raw_files = _raw_inventory(run_path / "raw")
    runtime_by_turn: dict[int, str] = {}
    for event in events:
        if event.get("kind") != "turn_completed":
            continue
        payload = event.get("payload")
        turn = payload.get("turn") if isinstance(payload, dict) else None
        if isinstance(turn, dict) and isinstance(turn.get("turn_number"), int):
            runtime_id = str(turn.get("adapter_id") or "")
            if runtime_id:
                runtime_by_turn[int(turn["turn_number"])] = runtime_id
    raw_rates, raw_rate_turns, parse_failures = _raw_rate_counts(
        raw_files, runtime_by_turn
    )
    rate_limits = _event_rate_summary(
        events, raw_rates, raw_rate_turns, parse_failures
    )
    decision_chain, governance = _decision_summary(
        run_path / "decisions.jsonl"
    )

    model_providers: dict[str, set[str]] = {}
    for event in events:
        if event.get("kind") != "turn_completed":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        turn = payload.get("turn")
        evidence = payload.get("evidence")
        if not isinstance(turn, dict) or not isinstance(evidence, list):
            continue
        runtime_id = str(turn.get("adapter_id") or "")
        for item in evidence:
            if (
                isinstance(item, list)
                and len(item) == 2
                and item[0] == "model_provider"
                and str(item[1])
            ):
                model_providers.setdefault(runtime_id, set()).add(str(item[1]))

    gates: list[dict[str, Any]] = []
    participants_by_runtime = {
        participant.adapter_id: participant
        for participant in config.participants
    }
    for runtime_id, participant in sorted(participants_by_runtime.items()):
        catalog = catalogs.get(participant.adapter_id)
        evidenced_turns = sum(
            1
            for turn in outcome.turns
            if turn.adapter_id == participant.adapter_id
            and turn.model_profile is not None
            and turn.model_profile.effective is not None
            and bool(turn.account_route)
            and bool(turn.runtime_version)
        )
        gates.append(
            {
                "runtime_id": participant.adapter_id,
                "catalog_verified": catalog is not None,
                "account_route": (
                    catalog.account_route
                    if catalog is not None
                    else participant.auth_route
                ),
                "runtime_version": (
                    catalog.runtime_version if catalog is not None else None
                ),
                "turn_revalidated_count": evidenced_turns,
                "model_providers": sorted(
                    model_providers.get(participant.adapter_id, ())
                ),
            }
        )

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "run_id": outcome.run_id,
        "run_status": outcome.status.value,
        "environment_gate": (
            {
                "verified": environment_gate.get("policy") == "allowlist",
                "policy": str(environment_gate.get("policy") or ""),
                "kept": [
                    str(item) for item in environment_gate.get("kept", ())
                ],
                "dropped_count": int(
                    environment_gate.get("dropped_count", 0)
                ),
            }
            if environment_gate is not None
            else {
                "verified": False,
                "policy": None,
                "kept": [],
                "dropped_count": None,
            }
        ),
        "runtime_gates": gates,
        "rate_limits": rate_limits,
        "governance": governance,
        "raw_capture": raw_inventory,
        "decision_chain": decision_chain,
        "event_log_readable": events_readable,
    }


def save_evidence_summary(run_path: Path, summary: dict[str, Any]) -> Path:
    """Atomically save the reader-facing summary at owner-only mode 0600."""

    target = Path(run_path) / "evidence_summary.json"
    temporary = target.parent / f".evidence-{secrets.token_hex(6)}.tmp"
    encoded = (
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    temporary.chmod(0o600)
    os.replace(temporary, target)
    target.chmod(0o600)
    return target
