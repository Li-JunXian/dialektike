#!/usr/bin/env python3
"""Build and smoke-test the frozen arm64 sidecar used by the Tauri app."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


PYINSTALLER_VERSION = "6.21.0"
PROTOCOL = "dialektike.sidecar.v1"
ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "macos_sidecar.spec"
OUTPUT = ROOT / "desktop" / "src-tauri" / "sidecar" / "dialektike-sidecar"
WORK = ROOT / "desktop" / ".build" / "pyinstaller"


def command(command_id: str, name: str) -> str:
    return json.dumps(
        {
            "protocol": PROTOCOL,
            "id": command_id,
            "command": name,
            "payload": {},
        },
        separators=(",", ":"),
    )


def frozen_environment(home: Path, temp: Path) -> dict[str, str]:
    """Finder-like environment shared by every frozen-binary smoke."""

    return {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "TMPDIR": str(temp),
    }


def smoke(executable: Path) -> None:
    """Prove the frozen imports and fixed JSONL control path work."""
    with tempfile.TemporaryDirectory(prefix="dialektike-frozen-smoke-") as temp:
        root = Path(temp)
        store = root / "runs"
        process = subprocess.run(
            [str(executable), "--store-root", str(store)],
            input=command("smoke-1", "initialize")
            + "\n"
            + command("smoke-2", "shutdown")
            + "\n",
            capture_output=True,
            text=True,
            timeout=60,
            env=frozen_environment(Path(os.environ["HOME"]), root),
        )
    if process.returncode != 0:
        raise SystemExit(
            "frozen sidecar smoke failed "
            f"(exit {process.returncode}): {process.stderr or process.stdout}"
        )
    records = [json.loads(line) for line in process.stdout.splitlines() if line]
    events = [record.get("event") for record in records]
    if events != ["sidecar.ready", "sidecar.shutdown"]:
        raise SystemExit(f"unexpected frozen sidecar events: {events!r}")
    if any(record.get("protocol") != PROTOCOL for record in records):
        raise SystemExit("frozen sidecar emitted the wrong protocol version")


def gate_probe(executable: Path, auth: dict[str, object]) -> str:
    """Return one frozen discovery failure without contacting a model."""

    with tempfile.TemporaryDirectory(prefix="dialektike-frozen-gate-") as temp:
        root = Path(temp)
        home = root / "home"
        cli = home / ".local" / "bin" / "claude"
        cli.parent.mkdir(parents=True)
        auth_json = json.dumps(auth, separators=(",", ":"))
        cli.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then\n'
            f"  printf '%s\\n' {shlex.quote(auth_json)}\n"
            "fi\n"
        )
        cli.chmod(0o700)
        process = subprocess.run(
            [str(executable), "--store-root", str(root / "runs")],
            input=(
                command("gate-1", "initialize")
                + "\n"
                + command("gate-2", "capabilities.discover")
                + "\n"
                + command("gate-3", "shutdown")
                + "\n"
            ),
            capture_output=True,
            text=True,
            timeout=60,
            env=frozen_environment(home, root),
        )
    if process.returncode != 0:
        raise SystemExit(
            "frozen gate smoke failed "
            f"(exit {process.returncode}): {process.stderr or process.stdout}"
        )
    records = [json.loads(line) for line in process.stdout.splitlines() if line]
    results = [
        record
        for record in records
        if record.get("event") == "capabilities.result"
        and record.get("request_id") == "gate-2"
    ]
    if len(results) != 1:
        raise SystemExit(f"unexpected frozen gate-smoke records: {records!r}")
    providers = (results[0].get("payload") or {}).get("providers") or []
    claude = next(
        (
            item
            for item in providers
            if isinstance(item, dict)
            and item.get("runtime_id") == "claude-code"
        ),
        None,
    )
    if claude is None:
        raise SystemExit(
            f"frozen gate smoke omitted the Claude provider: {records!r}"
        )
    availability = claude.get("availability") or {}
    if availability.get("available") is not False:
        raise SystemExit(
            f"frozen gate smoke unexpectedly advertised Claude: {claude!r}"
        )
    return str(availability.get("reason") or "")


def gate_smoke(executable: Path) -> None:
    """Prove the frozen trusted-disclosure boundary in both directions."""

    visible = gate_probe(
        executable,
        {
            "loggedIn": True,
            "authMethod": "console",
            "apiProvider": "api",
        },
    )
    if "ABORT: auth is not first-party claude.ai subscription" not in visible:
        raise SystemExit(f"authored frozen gate verdict was not visible: {visible!r}")

    masked = gate_probe(
        executable,
        {
            "loggedIn": True,
            "authMethod": "claude.ai",
            "apiProvider": "firstParty",
            "subscriptionType": "pro",
        },
    )
    expected = (
        "Runtime discovery failed safely. Full diagnostics remain owner-only."
    )
    if masked != expected:
        raise SystemExit(
            "ordinary frozen capability failure crossed the trusted boundary: "
            f"{masked!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--skip-smoke",
        action="store_true",
        help="build only (the default also performs a no-model JSONL smoke)",
    )
    mode.add_argument(
        "--smoke-only",
        action="store_true",
        help="smoke the existing frozen artifact without rebuilding it",
    )
    args = parser.parse_args()

    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("the M2 release sidecar must be built on macOS arm64")
    if args.smoke_only:
        if not OUTPUT.is_file():
            raise SystemExit(f"no frozen sidecar exists at {OUTPUT}")
        smoke(OUTPUT)
        gate_smoke(OUTPUT)
        print(f"smoke passed: {OUTPUT}")
        return 0
    try:
        import PyInstaller
    except ImportError as exc:
        raise SystemExit(
            "PyInstaller is missing; install the pinned build extra with "
            "`./venv/bin/python -m pip install -e '.[macos-release]'`"
        ) from exc
    if PyInstaller.__version__ != PYINSTALLER_VERSION:
        raise SystemExit(
            f"PyInstaller {PyInstaller.__version__} != pinned "
            f"{PYINSTALLER_VERSION}"
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    # Keep PyInstaller's binary-analysis cache inside the repository's ignored
    # build directory. This makes the build independent of the invoking
    # user's Application Support permissions and straightforward to clean.
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(WORK / "config")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--log-level",
            "WARN",
            "--distpath",
            str(OUTPUT.parent),
            "--workpath",
            str(WORK),
            str(SPEC),
        ],
        cwd=ROOT,
        check=True,
    )
    mode = OUTPUT.stat().st_mode
    if not stat.S_ISREG(mode) or not (mode & stat.S_IXUSR):
        raise SystemExit(f"build did not produce an executable at {OUTPUT}")
    architecture = subprocess.run(
        ["/usr/bin/file", "-b", str(OUTPUT)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if "Mach-O 64-bit executable arm64" not in architecture:
        raise SystemExit(f"unexpected sidecar artifact: {architecture}")
    if not args.skip_smoke:
        smoke(OUTPUT)
        gate_smoke(OUTPUT)
    print(f"built {OUTPUT}")
    print(f"size_bytes={OUTPUT.stat().st_size}")
    print(f"format={architecture}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
