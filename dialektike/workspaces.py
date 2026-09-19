"""Validation for Live-declared provider working directories.

Project workspaces are user-owned directories outside Dialektikḗ's private
run store.  Validation must therefore never create them, follow a newly
introduced alias silently, or change their ownership/mode merely to use them.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ProjectWorkspaceError(RuntimeError):
    """A declared project directory is absent, aliased, or inaccessible."""


@dataclass(frozen=True, slots=True)
class ProjectWorkspaceIdentity:
    """Owner-only filesystem identity captured from an opened directory."""

    device: int
    inode: int
    birthtime_ns: int | None = None

    def __post_init__(self) -> None:
        if self.device < 0 or self.inode <= 0:
            raise ValueError("project workspace identity is invalid")
        if self.birthtime_ns is not None and self.birthtime_ns < 0:
            raise ValueError("project workspace birth time is invalid")

    def to_record(self) -> dict[str, int | None]:
        return {
            "device": self.device,
            "inode": self.inode,
            "birthtime_ns": self.birthtime_ns,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "ProjectWorkspaceIdentity":
        if set(value) != {"device", "inode", "birthtime_ns"}:
            raise ValueError("project workspace identity has unknown fields")
        device = value.get("device")
        inode = value.get("inode")
        birthtime_ns = value.get("birthtime_ns")
        if (
            not isinstance(device, int)
            or isinstance(device, bool)
            or not isinstance(inode, int)
            or isinstance(inode, bool)
            or (
                birthtime_ns is not None
                and (
                    not isinstance(birthtime_ns, int)
                    or isinstance(birthtime_ns, bool)
                )
            )
        ):
            raise ValueError("project workspace identity is invalid")
        return cls(device=device, inode=inode, birthtime_ns=birthtime_ns)


@dataclass(frozen=True, slots=True)
class ProjectWorkspaceBinding:
    """A canonical Project path paired with its registered identity."""

    path: Path
    identity: ProjectWorkspaceIdentity

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise ValueError("project workspace binding path must be absolute")

    def __str__(self) -> str:
        return str(self.path)

    def validate(self) -> Path:
        return validate_project_workspace(
            self.path,
            expected_identity=self.identity,
        )


def _identity_from_stat(details: os.stat_result) -> ProjectWorkspaceIdentity:
    birthtime_ns = getattr(details, "st_birthtime_ns", None)
    if birthtime_ns is None:
        birthtime = getattr(details, "st_birthtime", None)
        if birthtime is not None:
            birthtime_ns = int(float(birthtime) * 1_000_000_000)
    return ProjectWorkspaceIdentity(
        device=int(details.st_dev),
        inode=int(details.st_ino),
        birthtime_ns=birthtime_ns,
    )


def inspect_project_workspace(
    path: str | Path,
) -> tuple[Path, ProjectWorkspaceIdentity]:
    """Open and inspect the exact canonical directory without following it."""

    candidate = Path(path)
    if not candidate.is_absolute():
        raise ProjectWorkspaceError("project directory must be absolute")
    try:
        canonical = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProjectWorkspaceError("project directory is unavailable") from exc
    if canonical != candidate:
        raise ProjectWorkspaceError("project directory is no longer canonical")

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ProjectWorkspaceError("project directory is unavailable") from exc
    try:
        opened = os.fstat(descriptor)
        named = os.stat(candidate, follow_symlinks=False)
        if not stat.S_ISDIR(opened.st_mode) or not stat.S_ISDIR(named.st_mode):
            raise ProjectWorkspaceError("project directory is not a real directory")
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise ProjectWorkspaceError("project directory changed during validation")
        identity = _identity_from_stat(opened)
    except OSError as exc:
        raise ProjectWorkspaceError("project directory is unavailable") from exc
    finally:
        os.close(descriptor)

    try:
        if candidate.is_symlink() or not os.access(candidate, os.R_OK | os.X_OK):
            raise ProjectWorkspaceError("project directory is not accessible")
    except OSError as exc:
        raise ProjectWorkspaceError("project directory is unavailable") from exc
    return candidate, identity


def validate_project_workspace(
    path: str | Path,
    *,
    expected_identity: ProjectWorkspaceIdentity | None = None,
) -> Path:
    """Return one canonical, currently usable existing directory.

    The stored form must already be absolute and canonical.  Requiring an
    exact match on every use makes a later symlink/alias substitution fail
    closed instead of quietly changing which tree a provider can access.
    This function is deliberately read-only: it never creates or chmods the
    external directory.
    """

    candidate, identity = inspect_project_workspace(path)
    if expected_identity is not None and identity != expected_identity:
        raise ProjectWorkspaceError("project directory identity has changed")
    return candidate


def canonicalize_declared_project_workspace(path: str | Path) -> Path:
    """Canonicalize a freshly selected absolute directory, then validate it."""

    candidate = Path(path)
    if not candidate.is_absolute():
        raise ProjectWorkspaceError("project directory must be absolute")
    try:
        canonical = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProjectWorkspaceError("project directory is unavailable") from exc
    return validate_project_workspace(canonical)
