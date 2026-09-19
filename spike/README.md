# Feasibility spike

Three claims to prove before any platform code: subscription-authenticated structured turns,
session resume, and a permission broker that actually gates a model's write.

## Claude leg — PASSED 2026-07-13 (all three checks)

```text
PART 1 PASS — schema-valid verdict: CHALLENGE on C1
PART 2 PASS — session 7b2ac546… resumed; model recalled: C1
PART 3a PASS — broker ALLOWED; approved.txt exists in staging
PART 3b PASS — broker DENIED; denied.txt absent
```

Re-run it yourself, with YOU as the broker (you'll see the permission card and type a/d):

```bash
cd /Users/live/dialektike
BROKER_MODE=ask ./venv/bin/python spike/claude_spike.py
```

## Codex leg — run this yourself (uses your ChatGPT login)

```bash
cd /Users/live/dialektike
python3 spike/codex_spike.py
```

Proves the structured turn + resume on `codex exec --json`. Raw event streams land in
`spike/out/codex-*.jsonl` — keep them; they are the specimen data for writing the Codex adapter.
(Approval flow on the Codex side arrives with the app-server adapter in CLI alpha; in Dialektikḗ
the Auditor role holds no tools anyway — content reaches it only via broker-approved disclosure.)

## Historical note

The first verdict ever produced inside Dialektikḗ was Claude, as Auditor, **CHALLENGING** claim C1
("a shared filesystem is an acceptable blindness boundary") — the very claim whose rejection
shaped this platform's architecture. The machinery agrees with its own design.
