"""Evidence persistence for Dialektikḗ runs.

Audit R5 fixes: nothing is overwritten (per-phase filenames + collision guard);
raw payloads (full event streams, anything that may embed session identifiers or
prompt text) go under raw/, which is git-ignored; git-tracked evidence carries
hashes of the raw files instead. Session IDs in tracked files are hashed.

Deterministic bookkeeping — automatic by governance 0001."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import time
from pathlib import Path


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_name(name: str) -> str:
    """Filenames may embed UNTRUSTED input (e.g. a server-chosen JSON-RPC id —
    R7: path traversal). Collapse anything outside [A-Za-z0-9._-] and cap
    length; content is unaffected (verbatim rule applies to content, not
    filenames)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", str(name))[:120].lstrip(".")
    return cleaned or "unnamed"


class EvidenceDir:
    """One directory per leg. Tracked in git, except raw/ (git-ignored)."""

    def __init__(self, root: Path, run_name: str):
        self.dir = root / run_name
        self.raw = self.dir / "raw"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.raw.mkdir(parents=True, exist_ok=True)

    def _fresh(self, name: str) -> Path:
        """Never overwrite: if the name exists, add a numeric suffix (R5 f.5).
        Names are sanitized and the result must stay inside the directory (R7)."""
        path = self.dir / safe_name(name)
        stem, suffix, n = path.stem, path.suffix, 1
        while path.exists():
            path = self.dir / f"{stem}.{n}{suffix}"
            n += 1
        if not path.resolve().is_relative_to(self.dir.resolve()):
            raise PermissionError(f"evidence filename escapes {self.dir}: {name!r}")
        return path

    def write_manifest(self, phase: str, extra: dict | None = None) -> Path:
        manifest = {
            "ts": time.time(),
            "phase": phase,
            "python": sys.version,
            "platform": platform.platform(),
            "anthropic_api_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "openai_api_key_present": bool(os.environ.get("OPENAI_API_KEY")),
            "packages": self._pinned_versions(),
            **(extra or {}),
        }
        path = self._fresh(f"{phase}_run_manifest.json")
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return path

    @staticmethod
    def _pinned_versions() -> dict:
        versions = {}
        try:
            from importlib.metadata import version
            versions["claude-agent-sdk"] = version("claude-agent-sdk")
        except Exception as exc:
            versions["claude-agent-sdk"] = f"unresolved ({exc})"
        return versions

    def save_json(self, name: str, obj) -> Path:
        path = self._fresh(name)
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
        return path

    def save_text(self, name: str, text: str) -> Path:
        path = self._fresh(name)
        path.write_text(text)
        return path

    def save_raw(self, name: str, obj) -> str:
        """Write payload to git-ignored raw/; return its sha256 so tracked
        evidence can reference it without exposing content. The name is
        sanitized (R7: it may embed a server-chosen id — path traversal)."""
        text = json.dumps(obj, indent=2, ensure_ascii=False) if not isinstance(obj, str) else obj
        path = self.raw / safe_name(name)
        stem, suffix, n = path.stem, path.suffix, 1
        while path.exists():
            path = self.raw / f"{stem}.{n}{suffix}"
            n += 1
        if not path.resolve().is_relative_to(self.raw.resolve()):
            raise PermissionError(f"raw filename escapes {self.raw}: {name!r}")
        path.write_text(text)
        return sha256_text(text)

    @staticmethod
    def hashed_id(session_id: str) -> str:
        """Session/thread ids appear in tracked files only as hashes (R5 f.5)."""
        return "sha256:" + sha256_text(session_id)

    # -- cross-process state (mutable working state, NOT evidence) --
    # Lives under raw/ (git-ignored) because it holds raw session/thread ids (R6).

    def record_state(self, key: str, value) -> None:
        state_path = self.raw / "state.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        state[key] = value
        state_path.write_text(json.dumps(state, indent=2))

    def read_state(self, key: str):
        state_path = self.raw / "state.json"
        if not state_path.exists():
            raise FileNotFoundError(f"no persisted state at {state_path} — run earlier phase first")
        return json.loads(state_path.read_text())[key]
