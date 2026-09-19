"""Owner-only, append-first persistence for Dialektikḗ topics.

Dialektikḗ is the canonical conversation store.  Provider-native sessions may
be linked as run identifiers, but topic state is deliberately independent of
those runtimes.  Every mutation is appended and fsynced before the readable
snapshot is atomically replaced.  The event log is authoritative and can
reconstruct a missing, stale, or corrupt snapshot after a process failure.

There is intentionally no evidence-purge API.  Deleting a topic writes a
tombstone and hides it from normal listings while retaining its cycles, linked
run identifiers, and all external run/governance evidence.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from dialektike.compaction import (
    canonical_entries_from_state,
    checkpoint_source_from_state,
    context_with_checkpoint,
    validate_checkpoint_source,
)
from dialektike.content import ContentNormalizationError, content_blocks_text
from dialektike.projects import validate_project_id
from dialektike.search import TopicSearchIndex


TOPIC_SCHEMA_VERSION = 1
DEFAULT_TOPIC_TITLE = "New topic"
_SAFE_TOPIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_SAFE_CHECKPOINT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_CYCLE_STATUSES = frozenset({"completed", "partial"})


class TopicStoreError(RuntimeError):
    """Base class for topic persistence failures."""


class TopicNotFoundError(TopicStoreError):
    """The requested topic does not exist."""


class TopicDeletedError(TopicStoreError):
    """The requested topic has been tombstoned."""


class TopicIntegrityError(TopicStoreError):
    """The append-only topic history cannot be replayed safely."""


def _json_copy(value: Any) -> Any:
    """Return a detached, strictly JSON-compatible representation."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be strictly JSON-compatible") from exc
    return json.loads(encoded)


def _canonical(value: Any, *, pretty: bool = False) -> bytes:
    options: dict[str, Any] = {
        "ensure_ascii": False,
        "allow_nan": False,
        "sort_keys": True,
    }
    if pretty:
        options["indent"] = 2
    else:
        options["separators"] = (",", ":")
    return (json.dumps(value, **options) + "\n").encode("utf-8")


def _validate_topic_id(topic_id: str) -> str:
    if not isinstance(topic_id, str) or not _SAFE_TOPIC_ID.fullmatch(topic_id):
        raise ValueError(f"unsafe topic id {topic_id!r}")
    return topic_id


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError(f"unsafe run id {run_id!r}")
    return run_id


def _validate_checkpoint_id(checkpoint_id: str) -> str:
    if (
        not isinstance(checkpoint_id, str)
        or not _SAFE_CHECKPOINT_ID.fullmatch(checkpoint_id)
    ):
        raise ValueError(f"unsafe checkpoint id {checkpoint_id!r}")
    return checkpoint_id


def _clean_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value.strip()


def derive_topic_title(prompt: str, *, limit: int = 72) -> str:
    """Derive a deterministic, compact title from the first Live prompt."""

    text = " ".join(_clean_text(prompt, "Live prompt").split())
    if limit < 8:
        raise ValueError("title limit must be at least 8 characters")
    if len(text) <= limit:
        return text
    prefix = text[: limit - 1].rstrip()
    if " " in prefix:
        candidate = prefix.rsplit(" ", 1)[0].rstrip()
        if len(candidate) >= limit // 2:
            prefix = candidate
    return prefix + "…"


def _secure_directory(path: Path) -> None:
    if path.is_symlink():
        raise TopicIntegrityError(f"refusing symbolic-link directory: {path.name}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir() or path.is_symlink():
        raise TopicIntegrityError(f"not a safe directory: {path.name}")
    path.chmod(0o700)


def _regular_file_or_missing(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise TopicIntegrityError(f"not a regular topic file: {path.name}")
    return True


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise OSError("short write while persisting topic state")
        offset += written


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class TopicStore:
    """Persistent local topic/session store with JSON-compatible boundaries.

    Projected messages are stored verbatim as mappings.  The canonical context
    selector recognizes completed direct answers and syntheses with the
    executor role. Their text may be in ``text`` or ``content``.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.topics_root = self.root / "topics"
        self._lock = threading.RLock()
        self._search_index = TopicSearchIndex()
        _secure_directory(self.root)
        _secure_directory(self.topics_root)

    @staticmethod
    def new_topic_id() -> str:
        return f"topic-{secrets.token_hex(12)}"

    def _topic_dir(self, topic_id: str) -> Path:
        return self.topics_root / _validate_topic_id(topic_id)

    def _paths(self, topic_id: str) -> tuple[Path, Path, Path]:
        topic_dir = self._topic_dir(topic_id)
        return topic_dir, topic_dir / "events.jsonl", topic_dir / "topic.json"

    def _append_event(
        self,
        topic_id: str,
        *,
        sequence: int,
        kind: str,
        payload: Mapping[str, Any],
        timestamp: float,
    ) -> dict[str, Any]:
        topic_dir, events_path, _ = self._paths(topic_id)
        _secure_directory(topic_dir)
        if _regular_file_or_missing(events_path):
            events_path.chmod(0o600)
        record = {
            "schema_version": TOPIC_SCHEMA_VERSION,
            "sequence": sequence,
            "timestamp": timestamp,
            "topic_id": topic_id,
            "kind": _clean_text(kind, "event kind"),
            "payload": _json_copy(dict(payload)),
        }
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(events_path, flags, 0o600)
        try:
            _write_all(fd, _canonical(record))
            os.fsync(fd)
        finally:
            os.close(fd)
        events_path.chmod(0o600)
        return record

    def _write_snapshot(self, state: Mapping[str, Any]) -> None:
        topic_id = str(state["topic_id"])
        topic_dir, _, snapshot_path = self._paths(topic_id)
        _secure_directory(topic_dir)
        # Replacing a symlink is safe, but refusing all non-regular existing
        # targets makes corruption explicit rather than silently repairing it.
        _regular_file_or_missing(snapshot_path)
        temp = topic_dir / f".topic-{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temp, flags, 0o600)
        try:
            _write_all(fd, _canonical(dict(state), pretty=True))
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            temp.chmod(0o600)
            os.replace(temp, snapshot_path)
            snapshot_path.chmod(0o600)
            _fsync_directory(topic_dir)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    def _read_events(self, topic_id: str) -> list[dict[str, Any]]:
        topic_dir, events_path, _ = self._paths(topic_id)
        if not topic_dir.exists():
            raise TopicNotFoundError(f"topic does not exist: {topic_id}")
        if topic_dir.is_symlink() or not topic_dir.is_dir():
            raise TopicIntegrityError(f"unsafe topic directory: {topic_id}")
        topic_dir.chmod(0o700)
        if not _regular_file_or_missing(events_path):
            raise TopicIntegrityError(f"topic has no event log: {topic_id}")
        events_path.chmod(0o600)
        try:
            encoded = events_path.read_bytes()
        except OSError as exc:
            raise TopicIntegrityError("topic event log is unreadable") from exc
        if encoded and not encoded.endswith(b"\n"):
            # Append-first commits are newline framed.  Anything after the
            # final newline is an uncommitted crash tail, even if it happens
            # to be syntactically valid JSON.  Remove it durably before a
            # later append can concatenate a new record onto the torn bytes.
            committed_length = encoded.rfind(b"\n") + 1
            flags = os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(events_path, flags)
                try:
                    os.ftruncate(fd, committed_length)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                events_path.chmod(0o600)
                _fsync_directory(topic_dir)
            except OSError as exc:
                raise TopicIntegrityError(
                    "topic crash tail could not be repaired"
                ) from exc
            encoded = encoded[:committed_length]
        lines = encoded.splitlines()
        records: list[dict[str, Any]] = []
        for line_number, encoded_line in enumerate(lines, start=1):
            if not encoded_line.strip():
                continue
            try:
                line = encoded_line.decode("utf-8")
                record = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise TopicIntegrityError(
                    f"invalid topic event at line {line_number}"
                ) from exc
            if not isinstance(record, dict):
                raise TopicIntegrityError(
                    f"topic event {line_number} is not an object"
                )
            records.append(record)
        return records

    @staticmethod
    def _apply_event(
        state: dict[str, Any] | None, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        kind = record.get("kind")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise TopicIntegrityError("topic event payload is not an object")
        if kind == "topic_created":
            if state is not None:
                raise TopicIntegrityError("duplicate topic_created event")
            state = {
                "schema_version": TOPIC_SCHEMA_VERSION,
                "topic_id": record["topic_id"],
                "title": payload["title"],
                "title_source": payload["title_source"],
                "created_at": payload["created_at"],
                "updated_at": payload["created_at"],
                "pinned": False,
                "archived": False,
                "deleted": False,
                "deleted_at": None,
                "participant_config": payload["participant_config"],
                "participant_revision": 1,
                "cycles": [],
                "linked_run_ids": [],
                "context_checkpoints": [],
                "active_context_checkpoint_id": None,
                # Existing M2 topic_created events predate Projects. Missing
                # project_id therefore replays as deliberately unassigned.
                "project_id": (
                    validate_project_id(payload["project_id"])
                    if payload.get("project_id") is not None
                    else None
                ),
                "last_sequence": record["sequence"],
            }
            return state
        if state is None:
            raise TopicIntegrityError("first topic event is not topic_created")
        if kind == "title_renamed":
            state["title"] = payload["title"]
            state["title_source"] = "manual"
        elif kind == "title_derived":
            if state["title_source"] == "pending":
                state["title"] = payload["title"]
                state["title_source"] = "derived"
        elif kind == "pin_changed":
            state["pinned"] = payload["pinned"]
        elif kind == "archive_changed":
            state["archived"] = payload["archived"]
        elif kind == "participants_changed":
            state["participant_config"] = payload["participant_config"]
            state["participant_revision"] = payload["participant_revision"]
        elif kind == "project_link_changed":
            state["project_id"] = (
                validate_project_id(payload["project_id"])
                if payload.get("project_id") is not None
                else None
            )
        elif kind == "cycle_appended":
            cycle = payload["cycle"]
            state["cycles"].append(cycle)
            run_id = cycle["run_id"]
            if run_id not in state["linked_run_ids"]:
                state["linked_run_ids"].append(run_id)
        elif kind == "context_checkpoint_drafted":
            checkpoint = payload["checkpoint"]
            if not isinstance(checkpoint, dict):
                raise TopicIntegrityError("checkpoint draft is not an object")
            checkpoint_id = _validate_checkpoint_id(checkpoint["checkpoint_id"])
            if any(
                item.get("checkpoint_id") == checkpoint_id
                for item in state["context_checkpoints"]
            ):
                raise TopicIntegrityError("duplicate context checkpoint id")
            state["context_checkpoints"].append(checkpoint)
        elif kind == "context_checkpoint_approved":
            checkpoint_id = _validate_checkpoint_id(payload["checkpoint_id"])
            checkpoint = next(
                (
                    item
                    for item in state["context_checkpoints"]
                    if item.get("checkpoint_id") == checkpoint_id
                ),
                None,
            )
            if checkpoint is None:
                raise TopicIntegrityError("approved context checkpoint is absent")
            checkpoint["approved_at"] = payload["approved_at"]
            state["active_context_checkpoint_id"] = checkpoint_id
        elif kind == "context_checkpoint_deactivated":
            checkpoint_id = _validate_checkpoint_id(payload["checkpoint_id"])
            if state["active_context_checkpoint_id"] != checkpoint_id:
                raise TopicIntegrityError(
                    "deactivated checkpoint was not the active checkpoint"
                )
            state["active_context_checkpoint_id"] = None
        elif kind == "topic_deleted":
            state["deleted"] = True
            state["deleted_at"] = payload["deleted_at"]
        else:
            raise TopicIntegrityError(f"unknown topic event kind: {kind!r}")
        state["updated_at"] = record["timestamp"]
        state["last_sequence"] = record["sequence"]
        return state

    def _replay(self, topic_id: str, *, repair_snapshot: bool) -> dict[str, Any]:
        records = self._read_events(topic_id)
        state: dict[str, Any] | None = None
        expected = 1
        for record in records:
            if record.get("schema_version") != TOPIC_SCHEMA_VERSION:
                raise TopicIntegrityError("unsupported topic schema version")
            if record.get("topic_id") != topic_id:
                raise TopicIntegrityError("topic event identifier mismatch")
            if record.get("sequence") != expected:
                raise TopicIntegrityError(
                    f"topic event sequence is not contiguous at {expected}"
                )
            timestamp = record.get("timestamp")
            if not isinstance(timestamp, (int, float)):
                raise TopicIntegrityError("topic event timestamp is invalid")
            try:
                state = self._apply_event(state, record)
            except (KeyError, TypeError, ValueError) as exc:
                raise TopicIntegrityError("topic event payload is invalid") from exc
            expected += 1
        if state is None:
            raise TopicIntegrityError(f"empty topic event log: {topic_id}")
        if repair_snapshot:
            _, _, snapshot_path = self._paths(topic_id)
            snapshot: Any = None
            if _regular_file_or_missing(snapshot_path):
                snapshot_path.chmod(0o600)
                try:
                    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    snapshot = None
            if snapshot != state:
                self._write_snapshot(state)
        return state

    def _ensure_mutable(self, state: Mapping[str, Any]) -> None:
        if state["deleted"]:
            raise TopicDeletedError(f"topic is deleted: {state['topic_id']}")

    def _commit(
        self,
        state: dict[str, Any],
        *,
        kind: str,
        payload: Mapping[str, Any],
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        recorded_at = time.time() if timestamp is None else timestamp
        record = self._append_event(
            state["topic_id"],
            sequence=state["last_sequence"] + 1,
            kind=kind,
            payload=payload,
            timestamp=recorded_at,
        )
        updated = self._apply_event(_json_copy(state), record)
        self._write_snapshot(updated)
        return _json_copy(updated)

    def create(
        self,
        *,
        participant_config: Mapping[str, Any],
        title: str | None = None,
        first_prompt: str | None = None,
        topic_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a topic without creating or modifying provider sessions."""

        with self._lock:
            chosen = _validate_topic_id(
                self.new_topic_id() if topic_id is None else topic_id
            )
            topic_dir, _, _ = self._paths(chosen)
            if topic_dir.exists() or topic_dir.is_symlink():
                raise FileExistsError(f"topic already exists: {chosen}")
            config = _json_copy(dict(participant_config))
            linked_project_id = (
                validate_project_id(project_id) if project_id is not None else None
            )
            if title is not None:
                chosen_title = _clean_text(title, "topic title")
                title_source = "manual"
            elif first_prompt is not None:
                chosen_title = derive_topic_title(first_prompt)
                title_source = "derived"
            else:
                chosen_title = DEFAULT_TOPIC_TITLE
                title_source = "pending"
            _secure_directory(topic_dir)
            now = time.time()
            record = self._append_event(
                chosen,
                sequence=1,
                kind="topic_created",
                payload={
                    "title": chosen_title,
                    "title_source": title_source,
                    "created_at": now,
                    "participant_config": config,
                    "project_id": linked_project_id,
                },
                timestamp=now,
            )
            state = self._apply_event(None, record)
            self._write_snapshot(state)
            return _json_copy(state)

    def read(
        self, topic_id: str, *, include_deleted: bool = False
    ) -> dict[str, Any]:
        with self._lock:
            state = self._replay(
                _validate_topic_id(topic_id), repair_snapshot=True
            )
            if state["deleted"] and not include_deleted:
                raise TopicDeletedError(f"topic is deleted: {topic_id}")
            return _json_copy(state)

    @staticmethod
    def _summary(state: Mapping[str, Any]) -> dict[str, Any]:
        cycles = state["cycles"]
        return {
            "topic_id": state["topic_id"],
            "title": state["title"],
            "created_at": state["created_at"],
            "updated_at": state["updated_at"],
            "pinned": state["pinned"],
            "archived": state["archived"],
            "deleted": state["deleted"],
            "participant_config": state["participant_config"],
            "participant_revision": state["participant_revision"],
            "cycle_count": len(cycles),
            "last_run_status": cycles[-1]["run_status"] if cycles else None,
            "project_id": state.get("project_id"),
        }

    @staticmethod
    def _matches_query(state: Mapping[str, Any], query: str) -> bool:
        return TopicSearchIndex.matches_topic(state, query)

    def list_topics(
        self,
        query: str | None = None,
        *,
        archived: bool | None = False,
        pinned: bool | None = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        """List topic summaries, with normal active topics as the default."""

        normalized_query = query.strip() if isinstance(query, str) else None
        with self._lock:
            states: list[dict[str, Any]] = []
            for candidate in self.topics_root.iterdir():
                if candidate.is_symlink() or not candidate.is_dir():
                    continue
                try:
                    topic_id = _validate_topic_id(candidate.name)
                    state = self._replay(topic_id, repair_snapshot=True)
                except (ValueError, TopicStoreError):
                    continue
                if state["deleted"] and not include_deleted:
                    continue
                if archived is not None and state["archived"] is not archived:
                    continue
                if pinned is not None and state["pinned"] is not pinned:
                    continue
                if normalized_query and not self._matches_query(
                    state, normalized_query
                ):
                    continue
                states.append(state)
            states.sort(
                key=lambda item: (
                    not bool(item["pinned"]),
                    -float(item["updated_at"]),
                    str(item["topic_id"]),
                )
            )
            return [_json_copy(self._summary(item)) for item in states]

    def search(
        self,
        query: str,
        *,
        archived: bool | None = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        return self.list_topics(
            _clean_text(query, "search query"),
            archived=archived,
            include_deleted=include_deleted,
        )

    def _replayed_states(self, *, include_deleted: bool) -> list[dict[str, Any]]:
        states: list[dict[str, Any]] = []
        for candidate in self.topics_root.iterdir():
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            try:
                topic_id = _validate_topic_id(candidate.name)
                state = self._replay(topic_id, repair_snapshot=True)
            except (ValueError, TopicStoreError):
                continue
            if state["deleted"] and not include_deleted:
                continue
            states.append(state)
        return states

    def search_occurrences(
        self,
        query: str,
        *,
        archived: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return backend-authoritative visible-text occurrence records.

        Active and archived topics are searched by default. Tombstoned topics
        and owner-only run/governance evidence are never search sources.
        """

        with self._lock:
            states = self._replayed_states(include_deleted=False)
            return _json_copy(
                self._search_index.search(
                    states,
                    query,
                    archived=archived,
                    limit=limit,
                )
            )

    def rebuild_search_index(self) -> None:
        """Rebuild the derived index solely from canonical topic event logs."""

        with self._lock:
            states = self._replayed_states(include_deleted=False)
            self._search_index.rebuild(states)

    def rename(self, topic_id: str, title: str) -> dict[str, Any]:
        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            cleaned = _clean_text(title, "topic title")
            if state["title"] == cleaned and state["title_source"] == "manual":
                return _json_copy(state)
            return self._commit(
                state, kind="title_renamed", payload={"title": cleaned}
            )

    def set_pinned(self, topic_id: str, pinned: bool) -> dict[str, Any]:
        if not isinstance(pinned, bool):
            raise ValueError("pinned must be a boolean")
        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            if state["pinned"] is pinned:
                return _json_copy(state)
            return self._commit(
                state, kind="pin_changed", payload={"pinned": pinned}
            )

    def pin(self, topic_id: str) -> dict[str, Any]:
        return self.set_pinned(topic_id, True)

    def unpin(self, topic_id: str) -> dict[str, Any]:
        return self.set_pinned(topic_id, False)

    def set_archived(self, topic_id: str, archived: bool) -> dict[str, Any]:
        if not isinstance(archived, bool):
            raise ValueError("archived must be a boolean")
        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            if state["archived"] is archived:
                return _json_copy(state)
            return self._commit(
                state,
                kind="archive_changed",
                payload={"archived": archived},
            )

    def archive(self, topic_id: str) -> dict[str, Any]:
        return self.set_archived(topic_id, True)

    def unarchive(self, topic_id: str) -> dict[str, Any]:
        return self.set_archived(topic_id, False)

    def update_participants(
        self, topic_id: str, participant_config: Mapping[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            config = _json_copy(dict(participant_config))
            if config == state["participant_config"]:
                return _json_copy(state)
            revision = int(state["participant_revision"]) + 1
            return self._commit(
                state,
                kind="participants_changed",
                payload={
                    "participant_config": config,
                    "participant_revision": revision,
                },
            )

    def set_project(
        self, topic_id: str, project_id: str | None
    ) -> dict[str, Any]:
        """Append a project link/unlink without rewriting topic history."""

        chosen_project_id = (
            validate_project_id(project_id) if project_id is not None else None
        )
        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            if state.get("project_id") == chosen_project_id:
                return _json_copy(state)
            return self._commit(
                state,
                kind="project_link_changed",
                payload={
                    "project_id": chosen_project_id,
                    "changed_by": "live",
                },
            )

    def append_cycle(
        self,
        topic_id: str,
        *,
        live_prompt: str,
        run_id: str,
        run_status: str,
        status: str,
        messages: Sequence[Mapping[str, Any]],
        participant_config: Mapping[str, Any] | None = None,
        review_target: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one completed or partial direct-chat or review cycle."""

        prompt = _clean_text(live_prompt, "Live prompt")
        linked_run_id = _validate_run_id(run_id)
        cleaned_run_status = _clean_text(run_status, "run status")
        if status not in _CYCLE_STATUSES:
            raise ValueError("cycle status must be 'completed' or 'partial'")
        projected = [_json_copy(dict(message)) for message in messages]
        for message in projected:
            blocks = message.get("blocks")
            if not isinstance(blocks, list) or not blocks:
                continue
            if not all(isinstance(block, Mapping) for block in blocks):
                raise ValueError("message content blocks must be objects")
            try:
                canonical_text = content_blocks_text(blocks)
            except ContentNormalizationError as exc:
                raise ValueError("message content blocks are not normalized") from exc
            message_text = message.get("text", message.get("content"))
            if message_text != canonical_text:
                raise ValueError(
                    "message text must reproduce its ordered content blocks"
                )
        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            if participant_config is not None:
                supplied = _json_copy(dict(participant_config))
                if supplied != state["participant_config"]:
                    raise ValueError(
                        "participant configuration changed; update the topic "
                        "before appending its cycle"
                    )
            if state["title_source"] == "pending":
                state = self._commit(
                    state,
                    kind="title_derived",
                    payload={"title": derive_topic_title(prompt)},
                )
            now = time.time()
            cycle = {
                "cycle_number": len(state["cycles"]) + 1,
                "status": status,
                "live_prompt": prompt,
                "participant_config": _json_copy(state["participant_config"]),
                "participant_revision": state["participant_revision"],
                "run_id": linked_run_id,
                "run_status": cleaned_run_status,
                "messages": projected,
                "recorded_at": now,
            }
            if review_target is not None:
                cycle["review_target"] = _json_copy(dict(review_target))
            return self._commit(
                state,
                kind="cycle_appended",
                payload={"cycle": cycle},
                timestamp=now,
            )

    def checkpoint_source(
        self,
        topic_id: str,
        *,
        through_anchor: str | None = None,
    ) -> dict[str, Any]:
        """Return the canonical prefix manifest for a checkpoint generator."""

        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            return _json_copy(
                checkpoint_source_from_state(
                    state,
                    through_anchor=through_anchor,
                )
            )

    def draft_context_checkpoint(
        self,
        topic_id: str,
        *,
        source: Mapping[str, Any],
        summary: str,
        creator: Mapping[str, Any],
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a reviewable draft without changing future model context."""

        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("checkpoint summary must not be empty")
        if not isinstance(creator, Mapping) or not creator:
            raise ValueError("checkpoint creator evidence must not be empty")
        chosen_id = _validate_checkpoint_id(
            checkpoint_id or f"checkpoint-{secrets.token_hex(12)}"
        )
        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            if any(
                item.get("checkpoint_id") == chosen_id
                for item in state["context_checkpoints"]
            ):
                raise FileExistsError(
                    f"context checkpoint already exists: {chosen_id}"
                )
            actual_source = validate_checkpoint_source(state, source)
            now = time.time()
            checkpoint = {
                "checkpoint_id": chosen_id,
                "topic_id": state["topic_id"],
                "source_start_anchor": actual_source["source_start_anchor"],
                "source_end_anchor": actual_source["source_end_anchor"],
                "source_entry_count": actual_source["source_entry_count"],
                "source_sha256": actual_source["source_sha256"],
                "summary": summary,
                "creator": _json_copy(dict(creator)),
                "created_at": now,
                "approved_at": None,
                "context_estimate": {
                    "unit": "utf8_bytes",
                    "before": actual_source["before_context_bytes"],
                    "after": len(summary.encode("utf-8")),
                },
            }
            return self._commit(
                state,
                kind="context_checkpoint_drafted",
                payload={"checkpoint": checkpoint},
                timestamp=now,
            )

    def approve_context_checkpoint(
        self, topic_id: str, checkpoint_id: str
    ) -> dict[str, Any]:
        """Append Live's approval and make that checkpoint active."""

        chosen_id = _validate_checkpoint_id(checkpoint_id)
        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            checkpoint = next(
                (
                    item
                    for item in state["context_checkpoints"]
                    if item.get("checkpoint_id") == chosen_id
                ),
                None,
            )
            if checkpoint is None:
                raise ValueError("context checkpoint draft does not exist")
            if state["active_context_checkpoint_id"] == chosen_id:
                return _json_copy(state)
            # Validate the original range again at approval time. Later cycles
            # may exist, but the immutable selected prefix must still hash to
            # exactly what the generator reviewed.
            validate_checkpoint_source(state, checkpoint)
            now = time.time()
            return self._commit(
                state,
                kind="context_checkpoint_approved",
                payload={
                    "checkpoint_id": chosen_id,
                    "approved_at": now,
                    "approved_by": "live",
                },
                timestamp=now,
            )

    def deactivate_context_checkpoint(self, topic_id: str) -> dict[str, Any]:
        """Stop using the active checkpoint without deleting its evidence."""

        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            self._ensure_mutable(state)
            checkpoint_id = state["active_context_checkpoint_id"]
            if checkpoint_id is None:
                return _json_copy(state)
            now = time.time()
            return self._commit(
                state,
                kind="context_checkpoint_deactivated",
                payload={
                    "checkpoint_id": checkpoint_id,
                    "deactivated_at": now,
                    "deactivated_by": "live",
                },
                timestamp=now,
            )

    def delete(self, topic_id: str) -> dict[str, Any]:
        """Tombstone a topic without deleting any topic or run evidence."""

        with self._lock:
            state = self._replay(_validate_topic_id(topic_id), repair_snapshot=True)
            if state["deleted"]:
                return _json_copy(state)
            now = time.time()
            return self._commit(
                state,
                kind="topic_deleted",
                payload={"deleted_at": now},
                timestamp=now,
            )

    def canonical_context(self, topic_id: str) -> list[dict[str, Any]]:
        """Return effective context while retaining original transcript state."""

        state = self.read(topic_id, include_deleted=False)
        original = canonical_entries_from_state(state)
        checkpoint_id = state["active_context_checkpoint_id"]
        if checkpoint_id is None:
            return original
        checkpoint = next(
            (
                item
                for item in state["context_checkpoints"]
                if item.get("checkpoint_id") == checkpoint_id
            ),
            None,
        )
        if checkpoint is None:
            raise TopicIntegrityError("active context checkpoint is absent")
        try:
            validate_checkpoint_source(state, checkpoint)
            return context_with_checkpoint(original, checkpoint)
        except ValueError as exc:
            raise TopicIntegrityError(str(exc)) from exc

    def review_source(self, topic_id: str, cycle_id: str, message_id: str) -> dict[str, Any]:
        """Resolve an exact completed answer and its original context locally.

        Use the immutable prefix before the target cycle, never later messages
        or a subsequently approved checkpoint that could include future text.
        """
        state = self.read(topic_id)
        for index, cycle in enumerate(state["cycles"]):
            if cycle["run_id"] != cycle_id:
                continue
            matches = [message for message in cycle["messages"]
                       if message.get("id") == message_id]
            if len(matches) != 1:
                break
            message = matches[0]
            if (message.get("stage") not in ("answer", "proposal", "synthesis")
                    or message.get("role") != "executor"
                    or message.get("partial") is True
                    or not isinstance(message.get("text"), str)
                    or not message["text"].strip()):
                break
            return {
                "cycle_id": cycle_id, "message_id": message_id,
                "question": (cycle.get("review_target") or {}).get("question", cycle["live_prompt"]),
                "answer": message["text"],
                "participant_id": message.get("participant_id"),
                "runtime_id": message.get("runtime_id"),
                "prior_context": canonical_entries_from_state({
                    **state, "cycles": state["cycles"][:index],
                }),
            }
        raise ValueError("review target must identify a completed answer in this topic")

    def events(self, topic_id: str) -> list[dict[str, Any]]:
        """Return a detached copy of the authoritative append-only history."""

        with self._lock:
            records = self._read_events(_validate_topic_id(topic_id))
            # Replay first so callers never receive a history that fails the
            # same integrity checks used by the store itself.
            self._replay(topic_id, repair_snapshot=True)
            return _json_copy(records)
