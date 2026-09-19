"""Non-model invariants for the Finder launch and macOS release path.

Run: ``./venv/bin/python tests/m2_packaging_invariants.py``.
"""

from __future__ import annotations

import ast
import json
import io
import os
import shutil
import stat
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dialektike import gates  # noqa: E402
from dialektike import sidecar as sidecar_module  # noqa: E402


FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("OK    " if condition else "FAIL  ") + name)
    if not condition:
        FAILS.append(name)


with tempfile.TemporaryDirectory() as temp:
    home = Path(temp)
    launcher = home / ".local" / "bin" / "codex"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nprintf 'codex-cli 0.145.0\\n'\n")
    launcher.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    with (
        patch.dict(
            os.environ,
            {"HOME": str(home), "PATH": "/usr/bin:/bin"},
            clear=True,
        ),
        patch.object(shutil, "which", return_value=None),
    ):
        resolved = gates.resolve_executable("codex")
        evidence = gates.assert_codex_version()
    check(
        "Finder-minimal PATH resolves the per-user standalone Codex",
        resolved == str(launcher.resolve()),
    )
    check(
        "resolved Codex is still exact-version gated",
        evidence["codex_version"] == "0.145.0"
        and evidence["executable"] == str(launcher.resolve()),
    )

with tempfile.TemporaryDirectory() as temp:
    home = Path(temp)
    older = (
        home
        / ".vscode/extensions/anthropic.claude-code-2.1.9-darwin-arm64"
        / "resources/native-binary/claude"
    )
    newer = (
        home
        / ".vscode/extensions/anthropic.claude-code-2.1.10-darwin-arm64"
        / "resources/native-binary/claude"
    )
    for candidate in (older, newer):
        candidate.parent.mkdir(parents=True)
        candidate.write_text("#!/bin/sh\nexit 0\n")
        candidate.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    with (
        patch.dict(
            os.environ,
            {"HOME": str(home), "PATH": "/usr/bin:/bin"},
            clear=True,
        ),
        patch.object(shutil, "which", return_value=None),
    ):
        resolved_claude = gates.resolve_executable("claude")
    check(
        "Finder resolution prefers the newest VS Code Claude runtime numerically",
        resolved_claude == str(newer.resolve()),
    )

try:
    gates.resolve_executable(
        "codex",
        preferred="/definitely/not/a/dialektike/runtime",
    )
except FileNotFoundError:
    check("an explicit missing runtime fails closed without PATH fallback", True)
else:
    check("an explicit missing runtime fails closed without PATH fallback", False)

config = json.loads(
    (REPO / "desktop" / "src-tauri" / "tauri.conf.json").read_text()
)
desktop_package = json.loads(
    (REPO / "desktop" / "package.json").read_text()
)
macos = config["bundle"]["macOS"]
check(
    "Tauri packages only fixed sidecar directory resources",
    config["bundle"]["resources"] == ["sidecar/*"],
)
check(
    "personal macOS app receives a verifiable ad-hoc signature",
    macos["signingIdentity"] == "-",
)

pyproject = (REPO / "pyproject.toml").read_text()
spec = (REPO / "packaging" / "macos_sidecar.spec").read_text()
supervisor = (
    REPO / "desktop" / "src-tauri" / "src" / "supervisor.rs"
).read_text()
claude_adapter = (
    REPO / "dialektike" / "adapters" / "claude.py"
).read_text()
check(
    "frozen-sidecar build tool is exactly pinned",
    '"pyinstaller==6.21.0"' in pyproject,
)
check(
    "unusable PyInstaller-extracted Claude CLI copy is excluded",
    "binaries = []" in spec
    and 'excludes=["_bundled/claude"]' in spec,
)
check(
    "approved provider descriptors are frozen as inert sidecar data",
    'provider_datas = collect_data_files(' in spec
    and '"dialektike"' in spec
    and '"providers/*.json"' in spec
    and '"providers/descriptors/*.json"' in spec
    and "*provider_datas" in spec,
)
check(
    "Claude auth, catalog, and turns bind one exact installed executable",
    "auth = gates.assert_claude_subscription()" in claude_adapter
    and 'path = Path(str(auth["executable"]))' in claude_adapter
    and claude_adapter.count("cli_path=str(cli_path)") == 2,
)
check(
    "release supervisor launches one fixed packaged sidecar path",
    'resource_dir.join("sidecar/dialektike-sidecar")' in supervisor,
)
check(
    "every Tauri release build rebuilds and smokes the frozen sidecar",
    config["build"]["beforeBuildCommand"] == "npm run build:desktop"
    and desktop_package["scripts"]["build:desktop"]
    == "npm run build:sidecar && npm run build"
    and desktop_package["scripts"]["build:sidecar"]
    == "../venv/bin/python ../scripts/build_macos_sidecar.py",
)

legacy_broker_uses: list[str] = []
for source in [*(REPO / "core").rglob("*.py"), *(REPO / "dialektike").rglob("*.py")]:
    tree = ast.parse(source.read_text(), filename=str(source))
    for node in ast.walk(tree):
        imports_broker = (
            isinstance(node, ast.ImportFrom)
            and node.module == "core.broker"
            and any(alias.name == "Broker" for alias in node.names)
        )
        calls_broker = (
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "Broker")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "Broker")
            )
        )
        if imports_broker or calls_broker:
            legacy_broker_uses.append(f"{source.relative_to(REPO)}:{node.lineno}")
check(
    "frozen production modules never construct the legacy manifest broker",
    not legacy_broker_uses,
)

binary = (
    REPO
    / "desktop"
    / "src-tauri"
    / "sidecar"
    / "dialektike-sidecar"
)
build_inputs = [
    REPO / "pyproject.toml",
    REPO / "scripts" / "build_macos_sidecar.py",
    REPO / "packaging" / "macos_sidecar.spec",
    REPO / "packaging" / "macos_sidecar_entry.py",
    *(REPO / "core").rglob("*.py"),
    *(REPO / "dialektike").rglob("*.py"),
    *(REPO / "dialektike" / "providers").rglob("*.json"),
]
check(
    "existing packaged sidecar is not older than its governed source inputs",
    not binary.exists()
    or binary.stat().st_mtime_ns
    >= max(path.stat().st_mtime_ns for path in build_inputs),
)

with tempfile.TemporaryDirectory() as temp:
    gate_text = (
        "ABORT: billing/provider selectors present ['OPENAI_API_KEY'] — "
        "cannot certify subscription billing (fail closed)"
    )
    stdout = io.StringIO()
    with (
        patch.object(
            gates,
            "scrub_environment",
            side_effect=SystemExit(gate_text),
        ),
        redirect_stdout(stdout),
    ):
        status = sidecar_module.main(
            ["--store-root", str(Path(temp) / "runs")]
        )
    message = json.loads(stdout.getvalue())
    diagnostic = (
        Path(temp) / "runs" / "sidecar-diagnostics.jsonl"
    ).read_text()
    check(
        "authored startup billing gate is displayed and owner-only saved",
        status == 1
        and gate_text in message["payload"]["message"]
        and gate_text in diagnostic,
    )

if FAILS:
    print(f"\nM2 PACKAGING INVARIANTS — {len(FAILS)} failure(s): {FAILS}")
    raise SystemExit(1)
print("\nM2 PACKAGING INVARIANTS — all hold")
