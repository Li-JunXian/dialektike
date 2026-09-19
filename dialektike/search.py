"""Derived, owner-local full-text search for canonical topic content.

The index in this module is deliberately non-canonical.  It is rebuilt from
replayed topic state, never written to disk, and contains only text that the
ordinary topic UI is allowed to display.  Authored strings are retained
unchanged; NFKC normalization and Unicode case folding are used only by the
derived matching representation.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from dialektike.content import ContentNormalizationError, content_block_text


def normalize_for_search(value: str) -> str:
    """Return the declared derived matching representation."""

    return unicodedata.normalize("NFKC", value).casefold()


@dataclass(frozen=True, slots=True)
class SearchDocument:
    topic_id: str
    topic_title: str
    archived: bool
    source_kind: str
    source_anchor: str
    source_field: str
    text: str
    stage: str | None
    speaker: str
    timestamp: str | None
    source_order: int


def _iso_timestamp(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (
            datetime.fromtimestamp(float(value), timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    return None


def _visible_block_text(block: Mapping[str, Any]) -> str | None:
    """Project one normalized content block exactly as ordinary UI text.

    Arbitrary/raw provider payload fields are intentionally ignored.  This
    list may grow with the versioned shared block vocabulary, but must remain a
    positive allowlist of fields the renderer actually exposes.
    """

    try:
        return content_block_text(block)
    except ContentNormalizationError:
        # A provider-native object that has not crossed the normalized block
        # boundary is not search-visible merely because it contains strings.
        return None


def documents_from_topic(state: Mapping[str, Any]) -> tuple[SearchDocument, ...]:
    """Build ordered visible search documents from one replayed topic."""

    if state.get("deleted") is True:
        return ()
    topic_id = str(state["topic_id"])
    title = str(state["title"])
    archived = bool(state.get("archived"))
    documents: list[SearchDocument] = [
        SearchDocument(
            topic_id=topic_id,
            topic_title=title,
            archived=archived,
            source_kind="title",
            source_anchor=f"topic:{topic_id}:title",
            source_field="title",
            text=title,
            stage=None,
            speaker="Topic title",
            timestamp=_iso_timestamp(state.get("updated_at")),
            source_order=0,
        )
    ]
    source_order = 1
    for cycle in state.get("cycles") or ():
        if not isinstance(cycle, Mapping):
            continue
        run_id = str(cycle.get("run_id") or "")
        live_prompt = cycle.get("live_prompt")
        if isinstance(live_prompt, str):
            documents.append(
                SearchDocument(
                    topic_id=topic_id,
                    topic_title=title,
                    archived=archived,
                    source_kind="live_prompt",
                    source_anchor=f"{run_id}:live",
                    source_field="text",
                    text=live_prompt,
                    stage="prompt",
                    speaker="Live",
                    timestamp=_iso_timestamp(cycle.get("recorded_at")),
                    source_order=source_order,
                )
            )
            source_order += 1
        messages = cycle.get("messages") or ()
        for message_index, message in enumerate(messages):
            if not isinstance(message, Mapping):
                continue
            anchor = message.get("id")
            if not isinstance(anchor, str) or not anchor:
                anchor = f"{run_id}:message:{message_index + 1}"
            stage = message.get("stage")
            role = message.get("role")
            speaker = message.get("participant_id") or role or message.get("runtime_id")
            speaker_text = str(speaker or "Participant")
            timestamp = _iso_timestamp(
                message.get("created_at", cycle.get("recorded_at"))
            )
            blocks = message.get("blocks")
            visible_blocks: list[tuple[int, str]] = []
            if isinstance(blocks, list):
                for block_index, block in enumerate(blocks):
                    if not isinstance(block, Mapping):
                        continue
                    visible = _visible_block_text(block)
                    if visible is not None:
                        visible_blocks.append((block_index, visible))
            if visible_blocks:
                for block_index, visible in visible_blocks:
                    documents.append(
                        SearchDocument(
                            topic_id=topic_id,
                            topic_title=title,
                            archived=archived,
                            source_kind="message",
                            source_anchor=anchor,
                            source_field=f"block:{block_index}",
                            text=visible,
                            stage=str(stage) if isinstance(stage, str) else None,
                            speaker=speaker_text,
                            timestamp=timestamp,
                            source_order=source_order,
                        )
                    )
                    source_order += 1
            else:
                text = message.get("text", message.get("content"))
                if isinstance(text, str):
                    documents.append(
                        SearchDocument(
                            topic_id=topic_id,
                            topic_title=title,
                            archived=archived,
                            source_kind="message",
                            source_anchor=anchor,
                            source_field="text",
                            text=text,
                            stage=str(stage) if isinstance(stage, str) else None,
                            speaker=speaker_text,
                            timestamp=timestamp,
                            source_order=source_order,
                        )
                    )
                    source_order += 1
    return tuple(documents)


def _normalized_with_source_spans(
    text: str,
) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Return the matching form plus an authored span for every output char.

    Per-code-point normalization is the fast path and covers ordinary text,
    compatibility characters and case-fold expansions.  When normalization
    depends on neighbouring code points (composition, canonical reordering,
    or Hangul composition), an incremental diff propagates the complete
    authored dependency span onto each changed normalized character.  The
    result is deliberately conservative: a highlight may include an
    intervening combining mark, but can never attribute a normalized glyph to
    source text that did not produce it.
    """

    normalized = normalize_for_search(text)
    pieces = tuple(normalize_for_search(character) for character in text)
    if "".join(pieces) == normalized:
        spans = tuple(
            (index, index + 1)
            for index, piece in enumerate(pieces)
            for _ in piece
        )
        return normalized, spans

    def interacts_with_previous(character: str) -> bool:
        decomposed = unicodedata.normalize("NFKD", character)
        if not decomposed:
            return False
        first = decomposed[0]
        if unicodedata.combining(first):
            return True
        name = unicodedata.name(first, "")
        return name.startswith("HANGUL JUNGSEONG") or name.startswith(
            "HANGUL JONGSEONG"
        )

    cluster_starts = [0]
    for index, character in enumerate(text[1:], start=1):
        if not interacts_with_previous(character):
            cluster_starts.append(index)
    cluster_starts.append(len(text))

    def precise_cluster(start: int, end: int) -> tuple[str, list[tuple[int, int]]]:
        fragment = text[start:end]
        # Bound the incremental diff. Pathological combining-mark runs remain
        # linear and conservatively map to the complete normalization cluster.
        if len(fragment) > 64:
            value = normalize_for_search(fragment)
            return value, [(start, end)] * len(value)

        current = ""
        spans: list[tuple[int, int]] = []
        for local_index in range(len(fragment)):
            source_index = start + local_index
            updated = normalize_for_search(fragment[: local_index + 1])
            prefix = 0
            common = min(len(current), len(updated))
            while prefix < common and current[prefix] == updated[prefix]:
                prefix += 1

            suffix = 0
            old_remaining = len(current) - prefix
            new_remaining = len(updated) - prefix
            while (
                suffix < old_remaining
                and suffix < new_remaining
                and current[len(current) - suffix - 1]
                == updated[len(updated) - suffix - 1]
            ):
                suffix += 1

            old_middle_end = len(current) - suffix
            changed = spans[prefix:old_middle_end]
            changed_start = min(
                [source_index, *(origin_start for origin_start, _ in changed)]
            )
            changed_end = max(
                [source_index + 1, *(origin_end for _, origin_end in changed)]
            )
            new_middle_end = len(updated) - suffix
            new_middle_length = max(0, new_middle_end - prefix)
            retained_suffix = spans[old_middle_end:] if suffix else []
            spans = [
                *spans[:prefix],
                *([(changed_start, changed_end)] * new_middle_length),
                *retained_suffix,
            ]
            current = updated
        return current, spans

    normalized_clusters: list[str] = []
    spans: list[tuple[int, int]] = []
    for start, end in zip(cluster_starts, cluster_starts[1:]):
        cluster, cluster_spans = precise_cluster(start, end)
        normalized_clusters.append(cluster)
        spans.extend(cluster_spans)

    current = "".join(normalized_clusters)
    if current != normalized:
        # Unicode normalization boundaries are intentionally derived rather
        # than hand-implementing UAX #15. If a future Unicode table exposes an
        # interaction not covered above, preserve correctness with one linear
        # whole-string normalization and a conservative authored span.
        spans = [(0, len(text))] * len(normalized)
        current = normalized

    if current != normalized or len(spans) != len(normalized):
        raise RuntimeError("search normalization offset map is inconsistent")
    return normalized, tuple(spans)


def _source_span(
    origins: tuple[tuple[int, int], ...], start: int, end: int
) -> tuple[int, int]:
    """Cover every authored code point that produced one normalized match."""

    selected = origins[start:end]
    if not selected:
        raise RuntimeError("search match has no authored source span")
    return min(span[0] for span in selected), max(span[1] for span in selected)


def _snippet(
    text: str,
    start: int,
    end: int,
    *,
    context_characters: int,
) -> tuple[list[dict[str, Any]], bool, bool]:
    snippet_start = max(0, start - context_characters)
    snippet_end = min(len(text), end + context_characters)
    segments: list[dict[str, Any]] = []
    if snippet_start < start:
        segments.append({"text": text[snippet_start:start], "highlighted": False})
    segments.append({"text": text[start:end], "highlighted": True})
    if end < snippet_end:
        segments.append({"text": text[end:snippet_end], "highlighted": False})
    return segments, snippet_start > 0, snippet_end < len(text)


class TopicSearchIndex:
    """Sequence-keyed derived cache that can be rebuilt from canonical state."""

    def __init__(self) -> None:
        self._documents: dict[str, tuple[int, tuple[SearchDocument, ...]]] = {}

    def clear(self) -> None:
        self._documents.clear()

    def rebuild(self, states: Iterable[Mapping[str, Any]]) -> None:
        self.clear()
        for state in states:
            self._documents_for(state)

    def _documents_for(
        self, state: Mapping[str, Any]
    ) -> tuple[SearchDocument, ...]:
        topic_id = str(state["topic_id"])
        if state.get("deleted") is True:
            self._documents.pop(topic_id, None)
            return ()
        sequence = int(state.get("last_sequence") or 0)
        cached = self._documents.get(topic_id)
        if cached is not None and cached[0] == sequence:
            return cached[1]
        documents = documents_from_topic(state)
        self._documents[topic_id] = (sequence, documents)
        return documents

    @staticmethod
    def matches_topic(state: Mapping[str, Any], query: str) -> bool:
        """Use the occurrence search's one normalization/content contract."""

        needle = normalize_for_search(query.strip())
        return bool(needle) and any(
            needle in normalize_for_search(document.text)
            for document in documents_from_topic(state)
        )

    def search(
        self,
        states: Iterable[Mapping[str, Any]],
        query: str,
        *,
        archived: bool | None = None,
        limit: int = 100,
        context_characters: int = 72,
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search query must not be empty")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("search limit must be a positive integer")
        if limit > 500:
            raise ValueError("search limit must not exceed 500")
        needle = normalize_for_search(query.strip())
        if not needle:
            raise ValueError("normalized search query must not be empty")

        ordered_states = sorted(
            (state for state in states if state.get("deleted") is not True),
            key=lambda state: (
                not bool(state.get("pinned")),
                -float(state.get("updated_at") or 0),
                str(state["topic_id"]),
            ),
        )
        hits: list[dict[str, Any]] = []
        for state in ordered_states:
            if archived is not None and bool(state.get("archived")) is not archived:
                continue
            occurrence_by_source: dict[tuple[str, str], int] = {}
            for document in self._documents_for(state):
                normalized, origins = _normalized_with_source_spans(document.text)
                emitted_source_spans: set[tuple[int, int]] = set()
                offset = 0
                while len(hits) < limit:
                    match_start = normalized.find(needle, offset)
                    if match_start < 0:
                        break
                    match_end = match_start + len(needle)
                    source_start, source_end = _source_span(
                        origins, match_start, match_end
                    )
                    source_span = (source_start, source_end)
                    if source_span in emitted_source_spans:
                        # One authored character may expand to several equal
                        # folded characters (ß -> ss, ﬀ -> ff). A one-letter
                        # query must still yield one authored occurrence.
                        offset = (
                            match_end if match_end > match_start else match_start + 1
                        )
                        continue
                    emitted_source_spans.add(source_span)
                    segments, prefix_truncated, suffix_truncated = _snippet(
                        document.text,
                        source_start,
                        source_end,
                        context_characters=context_characters,
                    )
                    source_key = (document.source_anchor, document.source_field)
                    ordinal = occurrence_by_source.get(source_key, 0) + 1
                    occurrence_by_source[source_key] = ordinal
                    hits.append(
                        {
                            "occurrence_id": (
                                f"{document.source_anchor}:{document.source_field}:"
                                f"match:{ordinal}"
                            ),
                            "topic_id": document.topic_id,
                            "topic_title": document.topic_title,
                            "archived": document.archived,
                            "source_kind": document.source_kind,
                            "source_anchor": document.source_anchor,
                            "source_field": document.source_field,
                            "stage": document.stage,
                            "speaker": document.speaker,
                            "timestamp": document.timestamp,
                            "match_start_utf8": len(
                                document.text[:source_start].encode("utf-8")
                            ),
                            "match_end_utf8": len(
                                document.text[:source_end].encode("utf-8")
                            ),
                            "snippet_segments": segments,
                            "prefix_truncated": prefix_truncated,
                            "suffix_truncated": suffix_truncated,
                        }
                    )
                    offset = match_end if match_end > match_start else match_start + 1
                if len(hits) >= limit:
                    return hits
        return hits
