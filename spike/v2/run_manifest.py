"""Dialektikḗ spike v2.6 — THE manifest runner (incident-001 / R12 amendment 5).

Incident-001 proved sequencing must be ENFORCED, not described: a pasted
command list started 13 Claude phase processes across contaminated evidence.
This runner is now the ONLY supported way to execute the manifest:

  - preflight runs ONCE with Live's externally supplied --expected-commit;
  - every run gets an ISOLATED evidence directory evidence/runs/<run-id>/
    (run id = UTC timestamp + short commit) — contamination is structurally
    impossible and failed runs preserve themselves;
  - SOURCE ATTESTATION repeats before EVERY phase: HEAD must still equal the
    approved commit and no file may have changed outside this run's own
    evidence directory (closes the R11 TOCTOU residual risk);
  - phases inherit the terminal (stdin included) so native permission cards
    remain interactive — the runner NEVER answers a card;
  - the first nonzero exit stops everything; dependent phases and the final
    verifier never run after a failure;
  - the verifier runs only after all phases pass, pointed at this run's
    evidence root.

Run: ./venv/bin/python spike/v2/run_manifest.py --expected-commit <audited-hash>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "spike" / "v2"))

import run_contract as rc  # noqa: E402

SPIKE = REPO / "spike" / "v2"
PHASES = [("claude_leg.py", p) for p in rc.CLAUDE_PHASES] + \
         [("codex_leg.py", p) for p in rc.CODEX_PHASES]


def git(*args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:  # R11 backlog: integrity-check failures fail closed
        sys.exit(f"ABORT: git {' '.join(args)} exited {proc.returncode}: "
                 f"{proc.stderr.strip()} (fail closed)")
    return proc


def source_attestation(expected: str, run_dir: Path) -> None:
    """HEAD unchanged AND nothing modified outside this run's evidence dir."""
    head = git("rev-parse", "HEAD").stdout.strip()
    if head != expected:
        sys.exit(f"ABORT: HEAD changed mid-run ({head[:12]} != {expected[:12]}) — "
                 "source no longer attested (fail closed)")
    rel = str(run_dir.relative_to(REPO))
    foreign = [line for line in
               git("status", "--porcelain", "--untracked-files=all").stdout.splitlines()
               if line.strip() and rel not in line]
    if foreign:
        sys.exit("ABORT: repository changed outside this run's evidence directory "
                 f"during the run (fail closed):\n" + "\n".join(foreign))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-commit", required=True,
                        help="the audited commit hash from Live's approval command")
    expected = parser.parse_args().expected_commit

    run_id = (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
              + "-" + expected[:12])
    run_dir = rc.EVIDENCE_ROOT / "runs" / run_id

    # preflight ONCE, before the run dir exists (it asserts non-existence)
    pre = subprocess.run([sys.executable, str(SPIKE / "preflight.py"),
                          "--expected-commit", expected,
                          "--run-dir", str(run_dir)])
    if pre.returncode != 0:
        sys.exit("RUN ABORTED — preflight failed; no model phase was started")

    run_dir.mkdir(parents=True)
    manifest = {"run_id": run_id, "expected_commit": expected,
                "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "phases": []}
    env = {**os.environ, rc.RUN_DIR_ENV: str(run_dir)}

    for script, phase in PHASES:
        source_attestation(expected, run_dir)  # per-phase TOCTOU closure
        print(f"\n===== {script} {phase} (run {run_id}) =====")
        started = time.time()
        # stdin/stdout/stderr inherited: cards stay interactive, nothing is
        # captured, and the runner can never answer a card itself
        proc = subprocess.run([sys.executable, str(SPIKE / script), phase], env=env)
        manifest["phases"].append({"script": script, "phase": phase,
                                   "exit_code": proc.returncode,
                                   "seconds": round(time.time() - started, 1)})
        (run_dir / "runner_manifest.json").write_text(json.dumps(manifest, indent=2))
        if proc.returncode != 0:
            print(f"\nRUN STOPPED at {script} {phase} (exit {proc.returncode}) — "
                  f"dependent phases and verification will NOT run.\n"
                  f"Evidence preserved in {run_dir}")
            sys.exit(1)

    source_attestation(expected, run_dir)
    print(f"\n===== verify_run.py (run {run_id}) =====")
    ver = subprocess.run([sys.executable, str(SPIKE / "verify_run.py")],
                         env={**env, "DIALEKTIKE_EVIDENCE_ROOT": str(run_dir)})
    manifest["verify_exit_code"] = ver.returncode
    manifest["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    (run_dir / "runner_manifest.json").write_text(json.dumps(manifest, indent=2))
    if ver.returncode != 0:
        sys.exit(f"RUN COMPLETE but VERIFICATION FAILED — evidence in {run_dir}")
    print(f"\nRUN {run_id} COMPLETE AND VERIFIED — evidence in {run_dir}")


if __name__ == "__main__":
    main()
