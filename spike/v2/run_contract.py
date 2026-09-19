"""Dialektikḗ spike v2.6 — THE run contract (single manifest definition).

Live's GO clarification 1 (R8.1): the phase list, expected native actions, and
evidence layout are defined ONCE, here. The legs execute it, verify_run.py
checks it, synthetic_check.py fabricates it, and EXECUTION_MANIFEST.md v6
mirrors it in prose. Seven phases — the count is derived, never assumed.

Nothing in this module talks to a model or the network. Pure data + hashing.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CASE = "spike-v2.6"
CLAUDE_MODEL = "haiku"
CLAUDE_MODEL_LABEL = f"claude ({CLAUDE_MODEL})"
CODEX_MODEL_LABEL = "codex (chatgpt plan)"

# Default locations; verify_run/synthetic_check may relocate via parameters.
EVIDENCE_ROOT = REPO / "evidence"
CLAUDE_EVIDENCE = "spike-v2-claude"
CODEX_EVIDENCE = "spike-v2-codex"
STAGING = REPO / "spike" / "v2" / "staging"
CODEX_CWD = REPO / "spike" / "v2" / "codex-empty-cwd"

# Incident-001 / R12: every run gets an ISOLATED evidence directory, created
# by run_manifest.py and handed to the legs via this env var. Legs REFUSE to
# start without it — direct invocation reproduced the pasted-command-list
# failure mode and is no longer a supported path.
RUN_DIR_ENV = "DIALEKTIKE_RUN_DIR"


def required_run_dir() -> Path:
    val = os.environ.get(RUN_DIR_ENV)
    if not val:
        raise SystemExit(
            f"ABORT: {RUN_DIR_ENV} not set — phases must be launched through "
            "spike/v2/run_manifest.py (incident-001: runner-enforced sequencing)")
    return Path(val)

BILLING_CLAIM = ("Subscription authentication verified before execution; "
                 "no API-billing credential source detected.")

# Controlled spike ExecutionProfile — explicitly labeled per Live's GO
# clarification 1 / governance 0003: this is NOT Live's native default
# configuration; the platform's default is inherit-native-settings.
PROFILE_LABEL = "controlled-spike-profile"
PROFILE_NOTE = ("Labeled controlled profile for spike determinism "
                "(setting_sources=[], per-phase native tool set, "
                "permission_mode=default). NOT Live's native defaults; "
                "platform default = inherit native settings (governance 0003).")

# ---- phases (GO clarification 1: exactly these, no invented eighth) ----

CLAUDE_PHASES = ("verdict", "resume", "auto-read", "approval-allow", "approval-deny")
CODEX_PHASES = ("verdict", "resume")

PHASE_ROLE = {"verdict": "auditor", "resume": "auditor", "auto-read": "auditor",
              "approval-allow": "executor", "approval-deny": "executor"}

# Native built-in tool set per phase (controlled profile; minimal surface).
PHASE_TOOLS = {"verdict": [], "resume": [],
               "auto-read": ["Read"],
               "approval-allow": ["Write"], "approval-deny": ["Write"]}

# Phases that clean the staging workspace before running (manifest-disclosed).
STAGING_CLEANING_PHASES = ("auto-read", "approval-allow", "approval-deny")

# R9 f.4: given the fixed manifest order (auto-read → approval-allow →
# approval-deny), two pre-clean snapshots are DETERMINISTIC and required:
# approval-allow must find exactly the brief auto-read staged; approval-deny
# must find exactly the file approval-allow wrote. auto-read's own pre-clean
# snapshot stays optional (depends on pre-run staging state).
def required_preclean_snapshots() -> dict[str, dict]:
    from core.broker import sha256_text  # local import: keep module data-only at top
    return {
        "approval-allow": {BRIEF_NAME: sha256_text(BRIEF_CONTENT)},
        "approval-deny": {APPROVED_NAME: sha256_text(WRITE_CONTENT)},
    }

# ---- exact native actions (GO clarifications 2 and 3) ----

BRIEF_NAME = "brief.txt"
BRIEF_MARKER = "MARKER-2c9d41"
BRIEF_CONTENT = f"{BRIEF_MARKER}: the staged brief for the auto-read phase"

WRITE_CONTENT = "dialektike spike v2.6"
APPROVED_NAME = "approved.txt"
DENIED_NAME = "denied.txt"


def brief_path(staging: Path = STAGING) -> Path:
    return staging / BRIEF_NAME


def write_target(phase: str, staging: Path = STAGING) -> Path:
    return staging / (APPROVED_NAME if phase == "approval-allow" else DENIED_NAME)


def expected_write_payload(phase: str, staging: Path = STAGING) -> dict:
    """The exact native Write request each approval phase must produce
    (GO clarification 3: one exact, harmless native action — the built-in
    Write tool, absolute disposable target, exact content)."""
    return {"tool": "Write",
            "input": {"file_path": str(write_target(phase, staging)),
                      "content": WRITE_CONTENT}}


# (phase, expected decision) — the only two cards of the run.
EXPECTED_DECISIONS = (("approval-allow", "allow"), ("approval-deny", "deny"))

# auto-read: the exact Read the model is asked to perform. The audit match is
# on tool == "Read" and resolved file path (Read may add offset/limit — those
# are native optional parameters, not a different action).
AUTO_READ_TOOL = "Read"

VERDICT_ENUM = {"AGREE", "CHALLENGE", "INSUFFICIENT EVIDENCE"}
CLAIM_ID = "C1"

# ---- Codex leg constants ----

REQUIRED_CODEX_VERSION = "0.139.0"
# R8 P0-3: the effective modelProvider must be a first-party subscription
# provider. Pinned fail-closed; if the live run evidences a different
# first-party id, re-pin from evidence with disclosure in the audit round.
ALLOWED_MODEL_PROVIDERS = {"openai"}
# Incident-001 / R12 amendment 6: the REQUEST uses the wire string, but the
# server ECHOES a schema-shaped SandboxPolicy object (vendored
# ThreadStartResponse: oneOf readOnly/workspaceWrite/dangerFullAccess...).
# The two representations are validated separately; equivalence is NOT
# assumed. Writable types and network access are explicitly rejected.
REQUESTED_CODEX_CONFIG = {"sandbox": "read-only", "approvalPolicy": "untrusted",
                          "approvalsReviewer": "user"}
EFFECTIVE_ECHO_STRINGS = {"approvalPolicy": "untrusted", "approvalsReviewer": "user"}


def sandbox_effective_ok(sandbox) -> bool:
    """True only for the strictest effective sandbox: readOnly, no network."""
    return (isinstance(sandbox, dict) and sandbox.get("type") == "readOnly"
            and not sandbox.get("networkAccess"))
RELAYABLE_METHODS = ("item/commandExecution/requestApproval",
                     "item/fileChange/requestApproval",
                     "execCommandApproval", "applyPatchApproval",
                     "item/permissions/requestApproval")

# ---- evidence inventory (tracked files; every entry must exist exactly once) ----

CLAUDE_COMMON_FILES = ("{phase}_billing_evidence.json", "{phase}_env_attestation.json",
                       "{phase}_safety_attestation.json", "{phase}_shadow_warnings.json",
                       "{phase}_run_manifest.json")
CLAUDE_PHASE_FILES = {
    "verdict": ("verdict_result.json",),
    "resume": ("resume_reply.txt", "resume_continuity.json"),
    "auto-read": ("auto-read_observation.json", "auto-read_reply.txt"),
    "approval-allow": ("approval-allow_result.json", "approval-allow_staging_snapshot.json",
                       "approval-allow_staging_snapshot_before_clean.json"),
    "approval-deny": ("approval-deny_result.json", "approval-deny_staging_snapshot.json",
                      "approval-deny_staging_snapshot_before_clean.json"),
}
CODEX_COMMON_FILES = ("{phase}_billing_evidence.json", "{phase}_safety_attestation.json",
                      "{phase}_client_health.json", "{phase}_item_summary.json",
                      "{phase}_events_ref.json", "{phase}_run_manifest.json")
CODEX_PHASE_FILES = {
    "verdict": ("thread_start_effective.json", "verdict_result.json", "verdict_path.json"),
    "resume": ("thread_resume_effective.json", "resume_reply.txt"),
}


def claude_files(phase: str) -> list[str]:
    return [t.format(phase=phase) for t in CLAUDE_COMMON_FILES] + \
        list(CLAUDE_PHASE_FILES[phase])


def codex_files(phase: str) -> list[str]:
    return [t.format(phase=phase) for t in CODEX_COMMON_FILES] + \
        list(CODEX_PHASE_FILES[phase])
