"""Owner-only, append-first persistence for M2 runs.

M2 intentionally keeps the accepted M1 JSON/JSONL evidence model.  Every state
transition is appended and fsynced before the readable snapshot is replaced, so
a cancellation or process failure still leaves useful partial evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, cast

from dialektike.domain import TurnPaths
from dialektike.workspaces import ProjectWorkspaceBinding


RUN_SCHEMA_VERSION = 2
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def to_primitive(value: Any) -> Any:
    """Convert immutable domain values into stable JSON-compatible values."""

    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            key: to_primitive(item)
            for key, item in asdict(cast(Any, value)).items()
        }
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _secure_touch(path: Path) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    path.chmod(0o600)


class RunHandle:
    """Writable handle for one run directory."""

    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        self.events_path = path / "events.jsonl"
        self.decisions_path = path / "decisions.jsonl"
        self.snapshot_path = path / "transcript.json"
        self._lock = threading.Lock()
        self._sequence = 0

    @property
    def raw_dir(self) -> Path:
        return self.path / "raw"

    @property
    def workspace_dir(self) -> Path:
        return self.path / "workspace"

    def turn_paths(
        self,
        turn_number: int,
        participant_id: str,
        *,
        project_workspace: ProjectWorkspaceBinding | None = None,
    ) -> TurnPaths:
        if turn_number < 1:
            raise ValueError("turn numbers start at 1")
        participant_hash = hashlib.sha256(
            participant_id.encode("utf-8")
        ).hexdigest()[:16]
        raw_dir = self.raw_dir / f"turn-{turn_number:04d}"
        _secure_directory(raw_dir)
        if project_workspace is None:
            workspace_dir = self.workspace_dir / f"participant-{participant_hash}"
            _secure_directory(workspace_dir)
            workspace_source = "generated"
        else:
            # A Live-declared project belongs to Live, not the run store. It is
            # validated immediately before use and is never created/chmodded.
            workspace_dir = project_workspace.validate()
            workspace_source = "project"
        return TurnPaths(
            run_path=str(self.path),
            raw_dir=str(raw_dir),
            workspace_dir=str(workspace_dir),
            decisions_path=str(self.decisions_path),
            workspace_source=workspace_source,
            workspace_identity=(
                project_workspace.identity
                if project_workspace is not None
                else None
            ),
        )

    def append_event(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not kind.strip():
            raise ValueError("event kind must not be empty")
        with self._lock:
            self._sequence += 1
            record = {
                "schema_version": RUN_SCHEMA_VERSION,
                "sequence": self._sequence,
                "timestamp": time.time(),
                "kind": kind,
                "run_id": self.run_id,
                "payload": to_primitive(payload),
            }
            encoded = (_canonical(record) + "\n").encode("utf-8")
            fd = os.open(
                self.events_path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o600,
            )
            try:
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)
            self.events_path.chmod(0o600)
            return record

    def write_snapshot(self, snapshot: dict[str, Any]) -> Path:
        """Atomically replace the reader-facing snapshot at mode 0600."""

        body = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": self.run_id,
            **to_primitive(snapshot),
        }
        encoded = (json.dumps(
            body, indent=2, ensure_ascii=False, sort_keys=True
        ) + "\n").encode("utf-8")
        temp = self.path / f".transcript-{secrets.token_hex(6)}.tmp"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)
        temp.chmod(0o600)
        os.replace(temp, self.snapshot_path)
        self.snapshot_path.chmod(0o600)
        return self.snapshot_path

    def events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.events_path.read_text().splitlines()
            if line.strip()
        ]

    def snapshot(self) -> dict[str, Any]:
        return json.loads(self.snapshot_path.read_text())


class RunStore:
    """Creates collision-safe owner-only run directories beneath one root."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._diagnostic_lock = threading.Lock()
        _secure_directory(self.root)

    def append_diagnostic(
        self, kind: str, detail: Mapping[str, Any]
    ) -> Path:
        """Persist private sidecar diagnostics without crossing into the GUI.

        Run-scoped failures already live in each owner-only event log. This
        root log covers failures that happen before a run exists, such as
        capability discovery or startup. Its contents are never projected
        into the WebView.
        """

        if not kind.strip():
            raise ValueError("diagnostic kind must not be empty")
        target = self.root / "sidecar-diagnostics.jsonl"
        record = {
            "schema_version": RUN_SCHEMA_VERSION,
            "timestamp": time.time(),
            "kind": kind,
            "detail": to_primitive(dict(detail)),
        }
        encoded = (_canonical(record) + "\n").encode("utf-8")
        with self._diagnostic_lock:
            fd = os.open(
                target,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o600,
            )
            try:
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)
            target.chmod(0o600)
        return target

    @staticmethod
    def new_run_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%fZ")
        return f"{stamp}-{secrets.token_hex(3)}"

    def create(self, run_id: str | None = None) -> RunHandle:
        chosen = run_id or self.new_run_id()
        if not _SAFE_RUN_ID.fullmatch(chosen):
            raise ValueError(f"unsafe run id {chosen!r}")
        path = self.root / chosen
        try:
            path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise FileExistsError(f"run already exists: {chosen}") from exc
        path.chmod(0o700)
        _secure_directory(path / "raw")
        _secure_directory(path / "workspace")
        _secure_touch(path / "events.jsonl")
        _secure_touch(path / "decisions.jsonl")
        return RunHandle(path, chosen)
