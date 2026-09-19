"""Owner-only append-first registry for Live-declared project folders."""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import stat
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dialektike.workspaces import (
    ProjectWorkspaceBinding,
    ProjectWorkspaceIdentity,
    ProjectWorkspaceError,
    canonicalize_declared_project_workspace,
    inspect_project_workspace,
    validate_project_workspace,
)


PROJECT_SCHEMA_VERSION = 2
_LEGACY_PROJECT_SCHEMA_VERSION = 1
PROJECT_RISK_ACKNOWLEDGEMENT = (
    "Participants use this folder as their native working directory. Actions "
    "the native runtime auto-permits may modify it without a Dialektikḗ card; "
    "those actions remain audited."
)
_SAFE_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


class ProjectStoreError(RuntimeError):
    """Base class for project-registry failures."""


class ProjectNotFoundError(ProjectStoreError):
    """The requested project is not registered."""


class ProjectIntegrityError(ProjectStoreError):
    """The append-only project registry cannot be replayed safely."""


class ProjectUnavailableError(ProjectStoreError):
    """A registered project folder is not currently safe to use."""


def validate_project_id(project_id: str) -> str:
    if not isinstance(project_id, str) or not _SAFE_PROJECT_ID.fullmatch(project_id):
        raise ValueError(f"unsafe project id {project_id!r}")
    return project_id


def _clean_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value.strip()


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


def _secure_directory(path: Path) -> None:
    if path.is_symlink():
        raise ProjectIntegrityError("refusing symbolic-link project registry")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir() or path.is_symlink():
        raise ProjectIntegrityError("project registry is not a safe directory")
    path.chmod(0o700)


def _regular_file_or_missing(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise ProjectIntegrityError("project registry entry is not a regular file")
    return True


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise OSError("short write while persisting project registry")
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


class ProjectStore:
    """Append-only registry whose canonical paths never cross into run input."""

    def __init__(self, root: Path):
        self.root = Path(root) / "projects"
        self.events_path = self.root / "events.jsonl"
        self.snapshot_path = self.root / "projects.json"
        self._lock = threading.RLock()
        _secure_directory(self.root)

    @staticmethod
    def new_project_id() -> str:
        return f"project-{secrets.token_hex(12)}"

    def _read_records(self) -> list[dict[str, Any]]:
        if not _regular_file_or_missing(self.events_path):
            return []
        self.events_path.chmod(0o600)
        try:
            encoded = self.events_path.read_bytes()
        except OSError as exc:
            raise ProjectIntegrityError("project event log is unreadable") from exc
        if encoded and not encoded.endswith(b"\n"):
            committed_length = encoded.rfind(b"\n") + 1
            flags = os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(self.events_path, flags)
            try:
                os.ftruncate(fd, committed_length)
                os.fsync(fd)
            finally:
                os.close(fd)
            _fsync_directory(self.root)
            encoded = encoded[:committed_length]
        records: list[dict[str, Any]] = []
        for line_number, encoded_line in enumerate(encoded.splitlines(), start=1):
            if not encoded_line.strip():
                continue
            try:
                value = json.loads(encoded_line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ProjectIntegrityError(
                    f"invalid project event at line {line_number}"
                ) from exc
            if not isinstance(value, dict):
                raise ProjectIntegrityError("project event is not an object")
            records.append(value)
        return records

    def _replay(self, *, repair_snapshot: bool) -> dict[str, dict[str, Any]]:
        projects: dict[str, dict[str, Any]] = {}
        for sequence, record in enumerate(self._read_records(), start=1):
            if set(record) != {
                "schema_version",
                "sequence",
                "timestamp",
                "kind",
                "payload",
            }:
                raise ProjectIntegrityError("project event has unknown fields")
            record_version = record.get("schema_version")
            if record_version not in {
                _LEGACY_PROJECT_SCHEMA_VERSION,
                PROJECT_SCHEMA_VERSION,
            }:
                raise ProjectIntegrityError("unsupported project schema version")
            if record.get("sequence") != sequence:
                raise ProjectIntegrityError("project event sequence is not contiguous")
            kind = record.get("kind")
            payload = record.get("payload")
            if not isinstance(payload, Mapping):
                raise ProjectIntegrityError("project event payload is invalid")
            if kind == "project_workspace_rebound":
                if record_version != PROJECT_SCHEMA_VERSION or set(payload) != {
                    "project_id",
                    "canonical_path",
                    "workspace_identity",
                    "rebound_at",
                    "risk_acknowledgement",
                    "registered_by",
                }:
                    raise ProjectIntegrityError("project rebound event is invalid")
                try:
                    project_id = validate_project_id(str(payload["project_id"]))
                    canonical_path = _clean_text(
                        str(payload["canonical_path"]), "canonical project path"
                    )
                    rebound_at = float(payload["rebound_at"])
                    acknowledgement = _clean_text(
                        str(payload["risk_acknowledgement"]),
                        "project risk acknowledgement",
                    )
                    registered_by = _clean_text(
                        str(payload["registered_by"]), "project registrar"
                    )
                    identity_raw = payload["workspace_identity"]
                    if not isinstance(identity_raw, Mapping):
                        raise ValueError("project workspace identity is invalid")
                    identity = ProjectWorkspaceIdentity.from_record(identity_raw)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProjectIntegrityError("project rebound event is invalid") from exc
                existing = projects.get(project_id)
                if (
                    existing is None
                    or existing["canonical_path"] != canonical_path
                    or acknowledgement != PROJECT_RISK_ACKNOWLEDGEMENT
                    or registered_by != "live"
                    or not math.isfinite(rebound_at)
                    or record.get("timestamp") != rebound_at
                ):
                    raise ProjectIntegrityError("project rebound event is invalid")
                existing["workspace_identity"] = identity.to_record()
                continue
            if kind != "project_registered":
                raise ProjectIntegrityError("unknown project event kind")
            expected_fields = {
                "project_id",
                "name",
                "canonical_path",
                "registered_at",
                "risk_acknowledgement",
                "registered_by",
            }
            if record_version == PROJECT_SCHEMA_VERSION:
                expected_fields.add("workspace_identity")
            if set(payload) != expected_fields:
                raise ProjectIntegrityError("project event payload has unknown fields")
            try:
                project_id = validate_project_id(str(payload["project_id"]))
                canonical_path = _clean_text(
                    str(payload["canonical_path"]), "canonical project path"
                )
                name = _clean_text(str(payload["name"]), "project name")
                registered_at = float(payload["registered_at"])
                acknowledgement = _clean_text(
                    str(payload["risk_acknowledgement"]),
                    "project risk acknowledgement",
                )
                registered_by = _clean_text(
                    str(payload["registered_by"]), "project registrar"
                )
                identity: ProjectWorkspaceIdentity | None = None
                if record_version == PROJECT_SCHEMA_VERSION:
                    identity_raw = payload["workspace_identity"]
                    if not isinstance(identity_raw, Mapping):
                        raise ValueError("project workspace identity is invalid")
                    identity = ProjectWorkspaceIdentity.from_record(identity_raw)
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectIntegrityError("project event payload is invalid") from exc
            if (
                acknowledgement != PROJECT_RISK_ACKNOWLEDGEMENT
                or registered_by != "live"
                or not math.isfinite(registered_at)
                or record.get("timestamp") != registered_at
                or len(name) > 512
            ):
                raise ProjectIntegrityError(
                    "project registration lacks Live's exact risk acknowledgement"
                )
            canonical = Path(canonical_path)
            if (
                not canonical.is_absolute()
                or "." in canonical.parts
                or ".." in canonical.parts
            ):
                raise ProjectIntegrityError("stored project path is not canonical")
            if project_id in projects:
                raise ProjectIntegrityError("duplicate project identifier")
            if any(
                item["canonical_path"] == canonical_path
                for item in projects.values()
            ):
                raise ProjectIntegrityError("duplicate canonical project path")
            projects[project_id] = {
                "schema_version": PROJECT_SCHEMA_VERSION,
                "project_id": project_id,
                "name": name,
                "canonical_path": canonical_path,
                "registered_at": registered_at,
                "risk_acknowledgement": acknowledgement,
                "registered_by": registered_by,
                "workspace_identity": (
                    identity.to_record() if identity is not None else None
                ),
            }
        if repair_snapshot:
            snapshot = {"schema_version": PROJECT_SCHEMA_VERSION, "projects": projects}
            current: Any = None
            if _regular_file_or_missing(self.snapshot_path):
                self.snapshot_path.chmod(0o600)
                try:
                    current = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    current = None
            if current != snapshot:
                self._write_snapshot(snapshot)
        return projects

    def _write_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        _regular_file_or_missing(self.snapshot_path)
        temp = self.root / f".projects-{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temp, flags, 0o600)
        try:
            _write_all(fd, _canonical(dict(snapshot), pretty=True))
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            temp.chmod(0o600)
            os.replace(temp, self.snapshot_path)
            self.snapshot_path.chmod(0o600)
            _fsync_directory(self.root)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    def _append_registration(self, payload: Mapping[str, Any], sequence: int) -> None:
        record = {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "sequence": sequence,
            "timestamp": payload["registered_at"],
            "kind": "project_registered",
            "payload": dict(payload),
        }
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.events_path, flags, 0o600)
        try:
            _write_all(fd, _canonical(record))
            os.fsync(fd)
        finally:
            os.close(fd)
        self.events_path.chmod(0o600)

    def _append_rebound(self, payload: Mapping[str, Any], sequence: int) -> None:
        record = {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "sequence": sequence,
            "timestamp": payload["rebound_at"],
            "kind": "project_workspace_rebound",
            "payload": dict(payload),
        }
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.events_path, flags, 0o600)
        try:
            _write_all(fd, _canonical(record))
            os.fsync(fd)
        finally:
            os.close(fd)
        self.events_path.chmod(0o600)

    def register(
        self,
        path: str | Path,
        *,
        acknowledgement: str,
        name: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Register only after Live returns the exact risk acknowledgement."""

        if acknowledgement != PROJECT_RISK_ACKNOWLEDGEMENT:
            raise ValueError("project workspace risk was not acknowledged by Live")
        canonical = canonicalize_declared_project_workspace(path)
        canonical, identity = inspect_project_workspace(canonical)
        chosen_name = (
            _clean_text(name, "project name")
            if name is not None
            else canonical.name or str(canonical)
        )
        if len(chosen_name) > 512:
            raise ValueError("project name is too long")
        with self._lock:
            projects = self._replay(repair_snapshot=True)
            for existing in projects.values():
                if existing["canonical_path"] == str(canonical):
                    if existing.get("workspace_identity") != identity.to_record():
                        rebound_at = time.time()
                        self._append_rebound(
                            {
                                "project_id": existing["project_id"],
                                "canonical_path": str(canonical),
                                "workspace_identity": identity.to_record(),
                                "rebound_at": rebound_at,
                                "risk_acknowledgement": acknowledgement,
                                "registered_by": "live",
                            },
                            len(self._read_records()) + 1,
                        )
                        projects = self._replay(repair_snapshot=True)
                        return dict(projects[existing["project_id"]])
                    return dict(existing)
            chosen_id = validate_project_id(project_id or self.new_project_id())
            if chosen_id in projects:
                raise FileExistsError(f"project already exists: {chosen_id}")
            registered_at = time.time()
            payload = {
                "project_id": chosen_id,
                "name": chosen_name,
                "canonical_path": str(canonical),
                "registered_at": registered_at,
                "risk_acknowledgement": acknowledgement,
                "registered_by": "live",
                "workspace_identity": identity.to_record(),
            }
            self._append_registration(payload, len(self._read_records()) + 1)
            projects = self._replay(repair_snapshot=True)
            return dict(projects[chosen_id])

    def read(self, project_id: str, *, require_available: bool = False) -> dict[str, Any]:
        chosen = validate_project_id(project_id)
        with self._lock:
            project = self._replay(repair_snapshot=True).get(chosen)
            if project is None:
                raise ProjectNotFoundError(f"project does not exist: {chosen}")
            if require_available:
                try:
                    identity_raw = project.get("workspace_identity")
                    if not isinstance(identity_raw, Mapping):
                        raise ProjectWorkspaceError(
                            "project directory identity is not bound"
                        )
                    validate_project_workspace(
                        project["canonical_path"],
                        expected_identity=ProjectWorkspaceIdentity.from_record(
                            identity_raw
                        ),
                    )
                except (ProjectWorkspaceError, ValueError) as exc:
                    raise ProjectUnavailableError(
                        "the registered project directory is unavailable"
                    ) from exc
            return dict(project)

    def resolve_workspace(self, project_id: str) -> Path:
        return self.resolve_workspace_binding(project_id).path

    def resolve_workspace_binding(self, project_id: str) -> ProjectWorkspaceBinding:
        """Return the registered path and identity for every later turn."""

        project = self.read(project_id, require_available=False)
        try:
            identity_raw = project.get("workspace_identity")
            if not isinstance(identity_raw, Mapping):
                raise ProjectWorkspaceError("project directory identity is not bound")
            binding = ProjectWorkspaceBinding(
                path=Path(project["canonical_path"]),
                identity=ProjectWorkspaceIdentity.from_record(identity_raw),
            )
            binding.validate()
            return binding
        except (ProjectWorkspaceError, ValueError) as exc:
            raise ProjectUnavailableError(
                "the registered project directory is unavailable"
            ) from exc

    def list_projects(self) -> list[dict[str, Any]]:
        with self._lock:
            projects = self._replay(repair_snapshot=True)
            result: list[dict[str, Any]] = []
            for project in projects.values():
                try:
                    identity_raw = project.get("workspace_identity")
                    if not isinstance(identity_raw, Mapping):
                        raise ProjectWorkspaceError(
                            "project directory identity is not bound"
                        )
                    validate_project_workspace(
                        project["canonical_path"],
                        expected_identity=ProjectWorkspaceIdentity.from_record(
                            identity_raw
                        ),
                    )
                    available = True
                except (ProjectWorkspaceError, ValueError):
                    available = False
                result.append({**dict(project), "available": available})
            result.sort(
                key=lambda item: (
                    str(item["name"]).casefold(),
                    item["project_id"],
                )
            )
            return result
