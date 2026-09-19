"""Dialektikḗ M1 — billing gates (axiom 1: subscription plans only).

Extracted from the frozen spike v2.x legs per the M1 directive, minus the
manifest machinery. Every gate fails closed with a clear ABORT before any
model is spoken to. The Codex account/provider gate needs a live app-server
connection and lives in codex_leg (account/read type=="chatgpt",
thread/start modelProvider allowlist).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# One env, one truth: the Claude SDK merges this process's full os.environ
# into its child, and the codex app-server subprocess inherits it too — so
# the scrub happens HERE, in-process, before either runtime is spawned.
ENV_ALLOWLIST = ("HOME", "PATH", "USER", "LOGNAME", "SHELL", "TMPDIR",
                 "LANG", "LC_ALL", "LC_CTYPE", "TERM")
SELECTOR_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_")
SELECTOR_EXACT = ("OPENAI_API_KEY",)

FORBIDDEN_AUTH_MARKERS = ("apikey", "api_key", "api key", "console",
                          "bedrock", "vertex", "foundry")

# The Codex adapter speaks the wire exactly as verified against the vendored
# 0.145.0 schemas; a different binary would silently invalidate those facts.
REQUIRED_CODEX_VERSION = "0.145.0"
_CLAUDE_VSCODE_EXTENSION = re.compile(
    r"^anthropic\.claude-code-(\d+(?:\.\d+)*)-darwin-arm64$"
)


def _claude_extension_version(path: Path) -> tuple[int, ...]:
    """Return the numeric extension version containing one native binary."""

    try:
        extension_name = path.parents[2].name
    except IndexError:
        return ()
    match = _CLAUDE_VSCODE_EXTENSION.fullmatch(extension_name)
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _claude_extension_candidates(home: Path) -> list[Path]:
    candidates: list[Path] = []
    for extensions in (
        home / ".vscode" / "extensions",
        home / ".vscode-insiders" / "extensions",
    ):
        candidates.extend(
            extensions.glob(
                "anthropic.claude-code-*-darwin-arm64/"
                "resources/native-binary/claude"
            )
        )
    return sorted(
        candidates,
        key=_claude_extension_version,
        reverse=True,
    )


def resolve_executable(
    name: str,
    *,
    preferred: str | os.PathLike[str] | None = None,
) -> str:
    """Resolve a subscription runtime without relying on an interactive PATH.

    macOS applications launched from Finder normally inherit a minimal PATH.
    The personal standalone installers used by the two runtimes place their
    launchers in a small set of conventional locations, so inspect those
    before falling back to ``shutil.which``.  Every returned path is resolved
    to an executable regular file; the callers still perform their exact
    version/authentication gates before trusting it.
    """
    if not name or Path(name).name != name:
        raise ValueError("executable name must be one plain file name")

    candidates: list[Path] = []
    if preferred is not None:
        candidates.append(Path(preferred).expanduser())
    else:
        home = Path(os.environ.get("HOME", "~")).expanduser()
        if name == "claude":
            # The VS Code extension may carry a newer first-party Claude Code
            # runtime than Homebrew. Prefer the newest installed arm64 binary,
            # then gate that exact path and bind the Agent SDK to it.
            candidates.extend(_claude_extension_candidates(home))
        candidates.extend(
            (
                home / ".local" / "bin" / name,
                home / ".npm-global" / "bin" / name,
                Path("/opt/homebrew/bin") / name,
                Path("/usr/local/bin") / name,
            )
        )
        discovered = shutil.which(name)
        if discovered:
            candidates.append(Path(discovered))

    checked: list[str] = []
    for candidate in candidates:
        checked.append(str(candidate))
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return str(resolved)
    detail = ", ".join(checked) if checked else "(no candidates)"
    raise FileNotFoundError(f"no executable {name!r} found; checked {detail}")


def scrub_environment() -> dict:
    """Reduce THIS process's environment to the allowlist WITHOUT reading
    non-allowlisted values (M1 audit finding 3; axiom 1: the platform never
    reads/stores raw credentials — key NAMES are inspected, values are
    retrieved only for allowlisted keys). Any billing or provider selector
    aborts rather than being silently dropped — presence means the operator
    may be routing to API billing (fail closed)."""
    names = set(os.environ.keys())
    selectors = sorted(k for k in names
                       if k.startswith(SELECTOR_PREFIXES) or k in SELECTOR_EXACT)
    if selectors:
        sys.exit(f"ABORT: billing/provider selectors present {selectors} — "
                 "cannot certify subscription billing (fail closed)")
    # Allowlisted entries stay in place untouched; every other name is
    # DELETED by name. Never os.environ.clear()/popitem — MutableMapping
    # retrieves each value before deleting it (audit R2 P0: reproduced),
    # while __delitem__ unsets without a read. No value is ever retrieved.
    kept = sorted(names & set(ENV_ALLOWLIST))
    for name in sorted(names - set(ENV_ALLOWLIST)):
        del os.environ[name]
    return {"policy": "allowlist", "kept": kept,
            "dropped_count": len(names) - len(kept)}


def assert_claude_subscription(
    claude_executable: str | os.PathLike[str] | None = None,
) -> dict:
    """POSITIVE first-party subscription evidence from `claude auth status`;
    unparseable output fails closed. Runs in the already-scrubbed env — the
    same one the SDK child will inherit."""
    try:
        executable = resolve_executable(
            "claude",
            preferred=claude_executable,
        )
        proc = subprocess.run([executable, "auth", "status"], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.exit(f"ABORT: `claude auth status` did not run ({exc}) — fail closed")
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        sys.exit(f"ABORT: `claude auth status` exited {proc.returncode} — "
                 "unauthenticated (fail closed)")
    try:
        status = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit("ABORT: `claude auth status` output not parseable JSON — cannot "
                 "positively certify subscription billing (fail closed)")
    if not (status.get("loggedIn") is True and status.get("authMethod") == "claude.ai"
            and status.get("apiProvider") == "firstParty"):
        sys.exit(f"ABORT: auth is not first-party claude.ai subscription — "
                 f"authMethod={status.get('authMethod')!r} "
                 f"apiProvider={status.get('apiProvider')!r} (fail closed)")
    hits = [m for m in FORBIDDEN_AUTH_MARKERS if m in out.lower()]
    if hits:
        sys.exit(f"ABORT: auth status suggests API-billing credential source "
                 f"{hits} (fail closed)")
    return {"auth_method": status.get("authMethod"),
            "api_provider": status.get("apiProvider"),
            "subscription_type": status.get("subscriptionType"),
            "executable": executable}


def assert_codex_version(
    codex_executable: str | os.PathLike[str] | None = None,
) -> dict:
    try:
        executable = resolve_executable(
            "codex",
            preferred=codex_executable,
        )
        ver = subprocess.run([executable, "--version"], capture_output=True,
                             text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.exit(f"ABORT: `codex --version` did not run ({exc}) — fail closed")
    token = ver.stdout.strip().split()[-1] if ver.stdout.strip() else ""
    if token != REQUIRED_CODEX_VERSION:  # exact equality, not substring
        sys.exit(f"ABORT: codex version {token!r} != {REQUIRED_CODEX_VERSION!r} — "
                 "the app-server adapter was verified against that exact version "
                 "(fail closed)")
    return {"codex_version": token, "executable": executable}
