"""Pure helpers for honest Dialektikḗ context checkpoints.

These helpers operate only on the canonical topic transcript.  They do not
call a provider-native compaction operation and do not mutate provider
sessions.  TopicStore owns the append-only draft/approval/deactivation events.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_entries_from_state(
    state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project Live prompts, completed direct answers and Syntheses with anchors.

    Legacy synthesis entries retain their exact shape so already-approved M2
    checkpoint digests continue to validate.
    """

    context: list[dict[str, Any]] = []
    for cycle in state.get("cycles") or ():
        if not isinstance(cycle, Mapping):
            continue
        cycle_number = int(cycle["cycle_number"])
        run_id = str(cycle["run_id"])
        prompt = cycle.get("live_prompt")
        if isinstance(prompt, str):
            context.append(
                {
                    "anchor": f"{run_id}:live",
                    "role": "live",
                    "stage": "prompt",
                    "text": prompt,
                    "cycle_number": cycle_number,
                }
            )
        for message_index, message in enumerate(cycle.get("messages") or ()):
            if not isinstance(message, Mapping):
                continue
            if (
                message.get("role") != "executor"
                or message.get("stage") not in ("synthesis", "answer")
                or message.get("partial") is True
            ):
                continue
            text = message.get("text", message.get("content"))
            if not isinstance(text, str) or not text.strip():
                continue
            anchor = message.get("id")
            if not isinstance(anchor, str) or not anchor:
                anchor = f"{run_id}:message:{message_index + 1}"
            context.append(
                {
                    "anchor": anchor,
                    "role": "executor",
                    "stage": message["stage"],
                    "text": text,
                    "cycle_number": cycle_number,
                }
            )
            if message["stage"] == "answer":
                context[-1].update({
                    "participant_id": message.get("participant_id"),
                    "runtime_id": message.get("runtime_id"),
                    "effective": message.get("effective"),
                })
    return context


def _canonical_source_bytes(entries: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        entries,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def checkpoint_source_from_state(
    state: Mapping[str, Any],
    *,
    through_anchor: str | None = None,
) -> dict[str, Any]:
    """Return an immutable source manifest suitable for asynchronous drafting.

    A caller supplies this manifest back to TopicStore after generating a
    candidate.  TopicStore re-derives and validates it before appending the
    draft, so a stale or fabricated range cannot silently become active.
    """

    entries = canonical_entries_from_state(state)
    synthesis_indices = [
        index
        for index, entry in enumerate(entries)
        if entry.get("role") == "executor"
        and entry.get("stage") in ("synthesis", "answer")
    ]
    if not synthesis_indices:
        raise ValueError(
            "a context checkpoint requires a completed answer or synthesis"
        )
    if through_anchor is not None:
        if not isinstance(through_anchor, str) or not through_anchor:
            raise ValueError("through_anchor must be omitted or non-empty")
        end_index = next(
            (
                index
                for index, entry in enumerate(entries)
                if entry["anchor"] == through_anchor
            ),
            None,
        )
        if end_index is None:
            raise ValueError("checkpoint source anchor is not canonical context")
        entries = entries[: end_index + 1]
        if entries[-1].get("stage") not in ("synthesis", "answer"):
            raise ValueError(
                "a context checkpoint must end at a completed answer or synthesis"
            )
    else:
        # A later partial cycle's Live prompt remains canonical context, but it
        # must stay outside the compacted prefix until that cycle has a
        # completed synthesis.
        entries = entries[: synthesis_indices[-1] + 1]
    encoded = _canonical_source_bytes(entries)
    return {
        "topic_id": str(state["topic_id"]),
        "source_start_anchor": entries[0]["anchor"],
        "source_end_anchor": entries[-1]["anchor"],
        "source_entry_count": len(entries),
        "source_sha256": hashlib.sha256(encoded).hexdigest(),
        "before_context_bytes": sum(
            len(str(entry["text"]).encode("utf-8")) for entry in entries
        ),
        # The source entries are returned for the local generator. They are
        # not copied into checkpoint events because the transcript is already
        # canonical and immutable.
        "entries": entries,
    }


def validate_checkpoint_source(
    state: Mapping[str, Any], source: Mapping[str, Any]
) -> dict[str, Any]:
    """Re-derive a proposed source range and compare every stable claim."""

    if source.get("topic_id") != state.get("topic_id"):
        raise ValueError("checkpoint source belongs to a different topic")
    end_anchor = source.get("source_end_anchor")
    if not isinstance(end_anchor, str) or not end_anchor:
        raise ValueError("checkpoint source requires an end anchor")
    actual = checkpoint_source_from_state(state, through_anchor=end_anchor)
    for field in (
        "source_start_anchor",
        "source_end_anchor",
        "source_entry_count",
        "source_sha256",
        "before_context_bytes",
    ):
        claimed = source.get(field)
        if field == "before_context_bytes" and claimed is None:
            estimate = source.get("context_estimate")
            if isinstance(estimate, Mapping):
                claimed = estimate.get("before")
        if claimed != actual[field]:
            raise ValueError(f"checkpoint source {field} no longer matches")
    if "entries" in source and source.get("entries") != actual["entries"]:
        raise ValueError("checkpoint source entries no longer match")
    return actual


def context_with_checkpoint(
    original_entries: list[dict[str, Any]],
    checkpoint: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Replace only the approved prefix; retain every later original entry."""

    end_anchor = checkpoint.get("source_end_anchor")
    end_index = next(
        (
            index
            for index, entry in enumerate(original_entries)
            if entry.get("anchor") == end_anchor
        ),
        None,
    )
    if end_index is None:
        raise ValueError("active checkpoint source is absent from canonical context")
    return [
        {
            "anchor": f"checkpoint:{checkpoint['checkpoint_id']}",
            "role": "context",
            "stage": "checkpoint",
            "text": checkpoint["summary"],
            "checkpoint_id": checkpoint["checkpoint_id"],
            "source_start_anchor": checkpoint["source_start_anchor"],
            "source_end_anchor": checkpoint["source_end_anchor"],
            "approved_at": checkpoint.get("approved_at"),
        },
        *original_entries[end_index + 1 :],
    ]
