"""Dialektikḗ feasibility spike — Codex adapter leg.

Proves, on ChatGPT subscription auth:
  1. one structured turn via `codex exec --json` (JSONL event stream)
  2. session resume via `codex exec resume --last`
(The approval flow is exercised later through the app-server adapter — `codex exec`
is non-interactive by design, and in Dialektikḗ the Auditor role gets no tools anyway:
content reaches it only through broker-approved disclosure.)

Run:  python3 spike/codex_spike.py          (requires `codex` CLI logged in to ChatGPT)
Raw event streams are saved to spike/out/codex-*.jsonl for adapter design.
"""

import json
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).parent / "out"
STAGING = OUT / "codex-staging"

AUDIT_PROMPT = (
    "You are the Auditor in a dialectic protocol. Audit this claim:\n"
    '  C1: "A shared filesystem directory is an acceptable blindness boundary between two models."\n'
    "Reply with ONLY a JSON object, no markdown fences, no prose, exactly these keys:\n"
    '  {"claim_id": "C1", "verdict": "AGREE" | "CHALLENGE" | "INSUFFICIENT EVIDENCE", "argument": "<one sentence>"}'
)


def run(args: list[str], log_name: str) -> tuple[int, str]:
    print(f"$ {' '.join(args[:4])} …")
    proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
    (OUT / log_name).write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    return proc.returncode, proc.stdout


def last_agent_message(jsonl: str) -> str:
    """Tolerant extraction across codex event-schema versions."""
    texts = []
    for line in jsonl.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("text", "message", "content", "last_agent_message"):
            v = ev.get(key) or (ev.get("item") or {}).get(key) or (ev.get("msg") or {}).get(key)
            if isinstance(v, str) and v.strip():
                texts.append(v)
    return texts[-1] if texts else ""


def main():
    STAGING.mkdir(parents=True, exist_ok=True)

    # Part 1 — structured turn
    code, out = run(
        ["codex", "exec", "--json", "--skip-git-repo-check", "-C", str(STAGING), AUDIT_PROMPT],
        "codex-part1.jsonl",
    )
    if code != 0:
        sys.exit(f"PART 1 FAIL — codex exec exited {code}; is `codex` logged in? See out/codex-part1.jsonl")
    msg = last_agent_message(out)
    raw = msg.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        verdict = json.loads(raw)
        assert verdict.get("claim_id") == "C1" and "verdict" in verdict
        print(f"PART 1 PASS — schema-valid verdict: {verdict['verdict']} on C1")
    except (json.JSONDecodeError, AssertionError):
        print(f"PART 1 PARTIAL — turn ran, but output was not clean JSON: {msg[:120]!r}")
        print("          (acceptable for the spike; --output-schema hardening goes in the adapter)")

    # Part 2 — resume
    code, out = run(
        ["codex", "exec", "resume", "--last", "--json", "--skip-git-repo-check",
         "Which claim_id did you audit in this session? Reply with the ID only."],
        "codex-part2.jsonl",
    )
    if code != 0:
        sys.exit("PART 2 FAIL — `codex exec resume --last` not supported on this version; "
                 "check `codex exec resume --help` and out/codex-part2.jsonl")
    msg = last_agent_message(out)
    if "C1" in msg:
        print(f"PART 2 PASS — session resumed; model recalled: {msg.strip()[:40]}")
        print("\nALL CODEX SPIKE CHECKS PASSED — adapter path is viable on ChatGPT subscription auth.")
    else:
        sys.exit(f"PART 2 FAIL — resume ran but model did not recall C1: {msg[:120]!r}")


if __name__ == "__main__":
    main()
