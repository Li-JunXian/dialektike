"""Dialektikḗ spike v2.5.1 — NON-MODEL preflight gate (R9 f.5 + R10 f.1).

The manifest's preconditions must be PROVEN before the first model phase
spends quota, not discovered afterwards by the verifier. This command runs no
model and must exit 0 immediately before manifest command 1:

  0. R10 P0 — execution is BOUND to the audited commit: `--expected-commit`
     (supplied externally in Live's execution-approval command; never embedded
     in the repo — a committed hash of itself is impossible) must equal
     `git rev-parse HEAD` exactly, and the worktree must be clean including
     untracked files. These run FIRST, before anything can generate artefacts.
  1. evidence directories for this run do not pre-exist (rerun contamination
     is prevented, not merely detected);
  2. `codex --version` token EXACTLY equals the vendored schema version;
  3. `claude auth status` gives positive first-party subscription evidence;
  4. every spike module compiles;
  5. both committed invariant suites pass (tests/);
  6. the synthetic evidence-layout suite passes on this exact working tree
     (the verifier provably CAN pass — manifest precondition 1).

Run: ./venv/bin/python spike/v2/preflight.py --expected-commit <audited-hash>
"""

from __future__ import annotations

import argparse
import json
import py_compile
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "spike" / "v2"))

import run_contract as rc  # noqa: E402

failures: list[str] = []


def check(cond: bool, msg: str):
    print(("OK    " if cond else "FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def git(*args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:  # R11 backlog: integrity checks fail closed
        sys.exit(f"ABORT: git {' '.join(args)} exited {proc.returncode}: "
                 f"{proc.stderr.strip()} (fail closed)")
    return proc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-commit", required=True,
                        help="the R-audited commit hash from Live's approval command")
    parser.add_argument("--run-dir", required=True,
                        help="this run's isolated evidence directory (must not exist yet)")
    args = parser.parse_args()
    expected = args.expected_commit

    # R10 P0: commit binding FIRST — before compilation or tests can run
    head = git("rev-parse", "HEAD").stdout.strip()
    check(bool(head) and head == expected,
          f"HEAD is the audited commit (HEAD={head[:12] or '?'}, "
          f"expected={expected[:12]})")
    dirty = git("status", "--porcelain", "--untracked-files=all").stdout.strip()
    check(dirty == "", "worktree clean including untracked files"
          if dirty == "" else f"worktree NOT clean:\n{dirty}")
    if failures:  # unbound execution: stop here, run nothing else
        print()
        print(f"PREFLIGHT FAILED — {len(failures)} problem(s); do NOT start model phases")
        sys.exit(1)

    check(not Path(args.run_dir).exists(),
          f"run evidence directory does not pre-exist ({args.run_dir})")

    ver = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=15)
    token = ver.stdout.strip().split()[-1] if ver.stdout.strip() else ""
    check(token == rc.REQUIRED_CODEX_VERSION,
          f"codex version exactly {rc.REQUIRED_CODEX_VERSION} (found {token!r})")

    auth = subprocess.run(["claude", "auth", "status"], capture_output=True,
                          text=True, timeout=30)
    try:
        status = json.loads(auth.stdout)
    except json.JSONDecodeError:
        status = {}
    check(auth.returncode == 0 and status.get("loggedIn") is True
          and status.get("authMethod") == "claude.ai"
          and status.get("apiProvider") == "firstParty",
          "claude auth: positive first-party subscription evidence")

    modules = ["core/broker.py", "core/relay.py", "core/evidence.py",
               "spike/v2/run_contract.py", "spike/v2/claude_leg.py",
               "spike/v2/codex_leg.py", "spike/v2/verify_run.py",
               "spike/v2/synthetic_check.py", "spike/v2/run_manifest.py"]
    compile_ok = True
    for m in modules:
        try:
            py_compile.compile(str(REPO / m), doraise=True)
        except Exception as exc:
            compile_ok = False
            print(f"      compile error in {m}: {exc}")
    check(compile_ok, f"all {len(modules)} spike modules compile")

    for suite in ("tests/relay_invariants.py", "tests/broker_invariants.py"):
        run = subprocess.run([sys.executable, str(REPO / suite)],
                             capture_output=True, text=True, timeout=120)
        check(run.returncode == 0, f"{suite} passes")
        if run.returncode != 0:
            print(run.stdout[-1500:])

    synth = subprocess.run([sys.executable, str(REPO / "spike" / "v2" / "synthetic_check.py")],
                           capture_output=True, text=True, timeout=300)
    check(synth.returncode == 0,
          "synthetic evidence-layout suite passes (verifier CAN pass)")
    if synth.returncode != 0:
        print(synth.stdout[-2000:])

    print()
    if failures:
        print(f"PREFLIGHT FAILED — {len(failures)} problem(s); do NOT start model phases")
        sys.exit(1)
    print("PREFLIGHT PASSED — manifest preconditions proven before any quota use")


if __name__ == "__main__":
    main()
