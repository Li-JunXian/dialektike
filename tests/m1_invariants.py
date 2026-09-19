"""M1 correction-pass invariants (reproducible, non-model). Kept in the
working tree so any auditor can rerun (audit R2: the correction paths need
durable regression coverage); commits happen only at Live's word. Covers:
credential-blind environment scrub, relay behavior under raw-store failure,
terminal sanitization, codex item-audit classification, rate-limit
classification on both legs, and the stop/audit control flow.

Run: ./venv/bin/python tests/m1_invariants.py   (exit 0 = all hold)
"""
import asyncio
import collections.abc
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from claude_agent_sdk import RateLimitEvent, RateLimitInfo  # noqa: E402

from core.broker import ChainedLog, sha256_text  # noqa: E402
from core.relay import (NormalizedRequest, PermissionRelay,  # noqa: E402
                        RelayIntegrityError, sanitize_terminal)
from dialektike import claude_leg, cli as cli_module, codex_leg, gates  # noqa: E402
from dialektike.claude_leg import classify_rate_limit  # noqa: E402
from dialektike.codex_leg import (AMBIENT_ITEM_TYPES, AppServerError,  # noqa: E402
                                  RELAY_DECISIONS, AppServerClient,
                                  _audit_items, rate_limit_reached)
from dialektike.cli import fenced  # noqa: E402

FAILS = []


def check(name, cond):
    print(("OK    " if cond else "FAIL  ") + name)
    if not cond:
        FAILS.append(name)


# ---- 1: the environment scrub never reads a non-allowlisted value ----

class SpyEnviron(collections.abc.MutableMapping):
    """Records every value retrieval; deletion must not retrieve."""

    def __init__(self, data):
        self.data = dict(data)
        self.reads = []

    def __getitem__(self, key):
        self.reads.append(key)
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __delitem__(self, key):
        del self.data[key]

    def __iter__(self):
        return iter(dict(self.data))

    def __len__(self):
        return len(self.data)


real_environ = os.environ
try:
    spy = SpyEnviron({"HOME": "/x", "PATH": "/bin", "UNRELATED_SECRET": "s3cr3t",
                      "AWS_SECRET_ACCESS_KEY": "k"})
    os.environ = spy
    evidence = gates.scrub_environment()
    check("scrub retrieves ZERO values (names only)", spy.reads == [])
    check("scrub keeps exactly the allowlisted names present",
          set(spy.data) == {"HOME", "PATH"} and evidence["kept"] == ["HOME", "PATH"]
          and evidence["dropped_count"] == 2)

    spy2 = SpyEnviron({"HOME": "/x", "ANTHROPIC_API_KEY": "k"})
    os.environ = spy2
    try:
        gates.scrub_environment()
        check("billing selector aborts (fail closed)", False)
    except SystemExit:
        check("billing selector aborts (fail closed)", True)
    check("selector abort reads no values", spy2.reads == [])
finally:
    os.environ = real_environ


# ---- 1b: Claude subscription gate has positive and fail-closed evidence ----

gate_calls = []
saved_gate_resolve = gates.resolve_executable
saved_gate_run = gates.subprocess.run
try:
    gates.resolve_executable = lambda name, preferred=None: "/trusted/claude"

    def gate_status(stdout, *, returncode=0, stderr=""):
        def run(argv, **kwargs):
            gate_calls.append((list(argv), kwargs))
            return SimpleNamespace(
                stdout=stdout, stderr=stderr, returncode=returncode
            )

        gates.subprocess.run = run

    gate_status(
        '{"loggedIn":true,"authMethod":"claude.ai",'
        '"apiProvider":"firstParty","subscriptionType":"pro"}'
    )
    certified = gates.assert_claude_subscription()
    check(
        "Claude subscription gate accepts only positive first-party evidence",
        certified["auth_method"] == "claude.ai"
        and certified["api_provider"] == "firstParty"
        and certified["executable"] == "/trusted/claude",
    )

    gate_status(
        '{"loggedIn":true,"authMethod":"console",'
        '"apiProvider":"api","subscriptionType":"pro"}'
    )
    try:
        gates.assert_claude_subscription()
        check("Claude subscription gate rejects API/console auth", False)
    except SystemExit:
        check("Claude subscription gate rejects API/console auth", True)

    gate_status("not-json")
    try:
        gates.assert_claude_subscription()
        check("Claude subscription gate rejects malformed status", False)
    except SystemExit:
        check("Claude subscription gate rejects malformed status", True)

    gate_status(
        '{"loggedIn":true,"authMethod":"claude.ai",'
        '"apiProvider":"firstParty","subscriptionType":"pro"}',
        stderr="api key marker",
    )
    try:
        gates.assert_claude_subscription()
        check("Claude subscription gate rejects credential markers", False)
    except SystemExit:
        check("Claude subscription gate rejects credential markers", True)
finally:
    gates.resolve_executable = saved_gate_resolve
    gates.subprocess.run = saved_gate_run

check(
    "Claude subscription gate invokes the exact resolved runtime auth status wire",
    bool(gate_calls)
    and all(call[0] == ["/trusted/claude", "auth", "status"] for call in gate_calls),
)


# ---- 2: relay decisions never depend on raw-store health ----

def req(payload, corr):
    return NormalizedRequest(provider="t", case="c", phase="p", model="m",
                             role="r", kind="k", payload=payload,
                             correlation_id=corr)


def raise_oserror(_):
    raise OSError("disk full")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    log = ChainedLog(root / "log.jsonl")
    raw = root / "raw"
    assert PermissionRelay(log, lambda q, c: "allow", raw).relay(
        req({"x": 1}, "c1"))[0] == "allow"

    broken = PermissionRelay(log, lambda q, c: "deny", raw)
    broken._stash_raw = raise_oserror
    d, reason = broken.relay(req({"x": 1}, "c1"))
    check("exact replay survives raw-store failure (returns recorded allow)",
          d == "allow" and "replayed" in reason)

    d, reason = broken.relay(req({"x": 2}, "c2"))
    check("fresh request under dead raw store → recorded deny",
          d == "deny" and "raw evidence store" in reason)
    d2, r2 = PermissionRelay(log, lambda q, c: "allow", raw).relay(req({"x": 2}, "c2"))
    check("that deny is durable on replay", d2 == "deny" and "replayed" in r2)

    bad = PermissionRelay(log, lambda q, c: "allow", raw)
    d, reason = bad.relay(req({"bad": object()}, "c3"))
    check("unenrichable payload → deny once", d == "deny" and "malformed" in reason)
    try:
        bad.relay(req({"bad": object()}, "c3"))
        check("unenrichable retransmission → RelayIntegrityError", False)
    except RelayIntegrityError:
        check("unenrichable retransmission → RelayIntegrityError", True)


# ---- 3: terminal sanitization ----

s = sanitize_terminal("evil\x1b[2J\x9b\x07CARD\rok\nline\ttab")
check("sanitizer strips C0/C1/DEL, keeps newline+tab",
      all(bad not in s for bad in ("\x1b", "\x9b", "\x07", "\r"))
      and "\n" in s and "\t" in s and "\\x1b" in s)


# ---- 4: codex item-audit classification (schema-faithful; audit R2 f.3) ----

class ForbiddenPresenter:
    def __call__(self, q, c):
        raise AssertionError("audit must never present a card")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    log = ChainedLog(root / "audit.jsonl")
    client = SimpleNamespace(
        item_events=[
            {"threadId": "t1", "turnId": "u1",
             "item": {"id": "ws1", "type": "webSearch", "query": "q"}},
            {"threadId": "t1", "turnId": "u1",
             "item": {"id": "c1", "type": "commandExecution", "status": "completed"}},
            {"threadId": "t1", "turnId": "u1",
             "item": {"id": "f1", "type": "fileChange", "status": "completed"}},
            {"threadId": "t1", "turnId": "u1",
             "item": {"id": "c2", "type": "commandExecution", "status": "failed"}},
            {"threadId": "t1", "turnId": "u1",
             "item": {"id": "a1", "type": "agentMessage", "text": "hi"}},
            {"threadId": "OTHER", "turnId": "u1",
             "item": {"id": "c9", "type": "commandExecution", "status": "completed"}},
        ],
        relayed_item_decisions={
            sha256_text("f1"): "allow",
            sha256_text("c2"): "deny",
        },
        relay=PermissionRelay(log, ForbiddenPresenter(), root / "raw"),
        model_label="codex (test)", fatal=[],
    )
    _audit_items(client, "t1", "u1")
    recs = {(r.get("annotations") or {}).get("item_id_sha256"): r
            for r in log.verified_records()}
    ws = recs.get(sha256_text("ws1"))
    check("statusless webSearch completion → native_auto_permitted (NOT failed)",
          ws is not None and ws["kind"] == "native_auto_permitted"
          and "statusless" in ws["annotations"]["status"])
    c1 = recs.get(sha256_text("c1"))
    check("completed unrelayed command → native_auto_permitted/native_auto",
          c1 is not None and c1["kind"] == "native_auto_permitted"
          and c1["annotations"]["decision_provenance"] == "native_auto")
    f1 = recs.get(sha256_text("f1"))
    check("completed RELAYED fileChange → tool_completed/relayed_approval",
          f1 is not None and f1["kind"] == "tool_completed"
          and f1["annotations"]["decision_provenance"] == "relayed_approval")
    c2 = recs.get(sha256_text("c2"))
    check(
        "denied command → tool_failed/relayed_denial",
        c2 is not None
        and c2["kind"] == "tool_failed"
        and c2["annotations"]["decision_provenance"] == "relayed_denial",
    )
    check("agentMessage and foreign-thread items not audited",
          sha256_text("a1") not in recs and sha256_text("c9") not in recs)

check("dynamicToolCall is an audited ambient type",
      "dynamicToolCall" in AMBIENT_ITEM_TYPES)


# ---- 4b: every Codex relay answer maps to the schema-pinned wire value ----

class _WireRelay:
    def __init__(self, decision):
        self.decision = decision

    def audit(self, request, kind):
        return None

    def relay(self, request):
        return self.decision, "test"


def _wire_client(decision):
    client = object.__new__(AppServerClient)
    client.model_label = "codex (wire-test)"
    client.relay = _WireRelay(decision)
    client.relayed_item_decisions = {}
    client.declined = []
    client.item_events = []
    client._turn_completion_condition = __import__("threading").Condition()
    client._turn_completions = {}
    client._turn_completion_error = None
    client.rate_limit_events = []
    client.rate_limit_stop = None
    sent = []
    client._send = sent.append
    return client, sent


wire_mapping_holds = True
wire_provenance_holds = True
for method, (allow_wire, deny_wire) in RELAY_DECISIONS.items():
    for decision, expected in (("allow", allow_wire), ("deny", deny_wire)):
        client, sent = _wire_client(decision)
        item_id = f"{method}-{decision}"
        client._handle(
            {
                "id": 7,
                "method": method,
                "params": {"itemId": item_id},
            }
        )
        wire_mapping_holds &= sent == [
            {"id": 7, "result": {"decision": expected}}
        ]
        wire_provenance_holds &= (
            client.relayed_item_decisions.get(sha256_text(item_id)) == decision
        )

for decision in ("allow", "deny"):
    client, sent = _wire_client(decision)
    item_id = f"profile-{decision}"
    requested_permissions = {"filesystem": {"read": ["/tmp"]}}
    client._handle(
        {
            "id": 8,
            "method": "item/permissions/requestApproval",
            "params": {
                "itemId": item_id,
                "permissions": requested_permissions,
            },
        }
    )
    expected_permissions = requested_permissions if decision == "allow" else {}
    wire_mapping_holds &= sent == [
        {
            "id": 8,
            "result": {
                "permissions": expected_permissions,
                "scope": "turn",
            },
        }
    ]
    wire_provenance_holds &= (
        client.relayed_item_decisions.get(sha256_text(item_id)) == decision
    )

check("Codex relay answers map exactly onto all approval wires", wire_mapping_holds)
check("Codex item audit remembers allow versus deny", wire_provenance_holds)


# ---- 5: rate-limit classification, both legs ----

def info(status="allowed", overage="rejected", raw=None, kind="five_hour", util=None):
    return SimpleNamespace(status=status, overage_status=overage, raw=raw or {},
                           rate_limit_type=kind, utilization=util)


check("healthy snapshot, overage rejected, does NOT stop (evidence 2026-07-16)",
      classify_rate_limit(info(raw={"isUsingOverage": False,
                                    "overageDisabledReason": "out_of_credits"})) is None)
check("healthy snapshot, overage AVAILABLE but unused, does NOT stop (evidence 2026-07-24)",
      classify_rate_limit(info(overage="allowed", raw={"isUsingOverage": False})) is None)
check("allowed_warning stops", classify_rate_limit(info(status="allowed_warning")) is not None)
check("rejected stops", classify_rate_limit(info(status="rejected")) is not None)
check("overage CONSUMPTION stops (axiom 1: isUsingOverage is the signal)",
      classify_rate_limit(info(overage="allowed", raw={"isUsingOverage": True})) is not None)
check("mere overage AVAILABILITY is NOT consumption (does not stop)",
      classify_rate_limit(info(overage="allowed", raw={"isUsingOverage": False})) is None
      and classify_rate_limit(info(overage="allowed_warning",
                                   raw={"isUsingOverage": False})) is None)

# enum value from the vendored RateLimitReachedType (audit R3 f.3)
check("codex reached limit detected",
      rate_limit_reached({"rateLimits": {"rateLimitReachedType": "rate_limit_reached"}})
      == "rate_limit_reached")
check("codex snapshot without reached type is bookkeeping",
      rate_limit_reached({"rateLimits": {"primary": {"usedPercent": 50}}}) is None
      and rate_limit_reached({}) is None)


# ---- 6: fence can never be broken out of ----

evil = "text\n```\ninjected\n````\nmore"
f = fenced(evil)
fence = f.split("\n", 1)[0]
check("fence strictly longer than any backtick run in content",
      fence.startswith("```") and fence not in evil and f.endswith(fence))


# ---- 7: the permanent CLI binds both turns to the exact gated binaries ----

cli_bindings = {}
saved_cli_bindings = {
    "scrub_environment": cli_module.gates.scrub_environment,
    "assert_claude_subscription": cli_module.gates.assert_claude_subscription,
    "assert_codex_version": cli_module.gates.assert_codex_version,
    "claude_respond": cli_module.claude_leg.respond,
    "codex_respond": cli_module.codex_leg.respond,
    "make_run_dir": cli_module.make_run_dir,
}


async def capture_claude(_prompt, _relay, _workspace, *, cli_path):
    cli_bindings["claude"] = str(cli_path)
    return {"text": "first", "model": "test", "rate_limit_stop": None}


def capture_codex(_prompt, _log, _raw, _workspace, *, executable):
    cli_bindings["codex"] = str(executable)
    return {"text": "second", "model": "test", "rate_limit_stop": None}


with tempfile.TemporaryDirectory(dir=REPO) as td:
    run_dir = Path(td) / "run"
    (run_dir / "raw").mkdir(parents=True)
    cli_module.gates.scrub_environment = lambda: {"policy": "test"}
    cli_module.gates.assert_claude_subscription = lambda: {
        "executable": "/gated/claude",
    }
    cli_module.gates.assert_codex_version = lambda: {
        "executable": "/gated/codex",
    }
    cli_module.claude_leg.respond = capture_claude
    cli_module.codex_leg.respond = capture_codex
    cli_module.make_run_dir = lambda: run_dir
    try:
        cli_status = cli_module.main(["binding probe"])
    finally:
        cli_module.gates.scrub_environment = saved_cli_bindings["scrub_environment"]
        cli_module.gates.assert_claude_subscription = (
            saved_cli_bindings["assert_claude_subscription"]
        )
        cli_module.gates.assert_codex_version = (
            saved_cli_bindings["assert_codex_version"]
        )
        cli_module.claude_leg.respond = saved_cli_bindings["claude_respond"]
        cli_module.codex_leg.respond = saved_cli_bindings["codex_respond"]
        cli_module.make_run_dir = saved_cli_bindings["make_run_dir"]

check("permanent CLI passes each gate's exact executable into its turn",
      cli_status == 0
      and cli_bindings == {
          "claude": "/gated/claude",
          "codex": "/gated/codex",
      })


# ---- 8: control flow of the stop/audit paths (audit R3) ----

def _rate_event(status="allowed_warning"):
    return RateLimitEvent(
        rate_limit_info=RateLimitInfo(status=status, rate_limit_type="five_hour"),
        uuid="u", session_id="s")


class _FakeClaudeClient:
    """Stand-in for ClaudeSDKClient: yields a warning event, then records if
    the loop advances PAST it (proving break vs. continue)."""

    def __init__(self, *, interrupt_raises, options=None, **_):
        self.interrupt_raises = interrupt_raises
        self.options = options
        self.advanced_past_warning = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def query(self, prompt):
        pass

    async def interrupt(self):
        if self.interrupt_raises:
            raise RuntimeError("interrupt refused")

    async def receive_response(self):
        yield _rate_event()
        # only reached if the loop asks for the next item (interrupt success)
        self.advanced_past_warning = True


def _run_claude(interrupt_raises):
    made = {}

    def factory(**kwargs):
        made["client"] = _FakeClaudeClient(interrupt_raises=interrupt_raises, **kwargs)
        return made["client"]

    orig = claude_leg.ClaudeSDKClient
    claude_leg.ClaudeSDKClient = factory
    try:
        with tempfile.TemporaryDirectory() as td:
            relay = PermissionRelay(ChainedLog(Path(td) / "l.jsonl"),
                                    ForbiddenPresenter(), Path(td) / "raw")
            cli_path = Path(td) / "gated-claude"
            entry = asyncio.run(claude_leg.respond(
                "hi", relay, Path(td) / "ws", cli_path=cli_path))
            made["gated_path"] = str(cli_path)
        return entry, made["client"], made["gated_path"]
    finally:
        claude_leg.ClaudeSDKClient = orig


entry, cli, gated_claude = _run_claude(interrupt_raises=True)
check("Claude SDK receives the exact gated executable",
      str(cli.options.cli_path) == gated_claude)
check("Claude failed interrupt → stream not consumed past the warning",
      cli.advanced_past_warning is False)
check("Claude failed interrupt → interrupted False, error recorded, stop preserved",
      entry["interrupted"] is False and entry["interrupt_error"] is not None
      and entry["rate_limit_stop"] is not None and entry["interrupt_attempted"] is True)

entry_ok, cli_ok, _ = _run_claude(interrupt_raises=False)
check("Claude successful interrupt → interrupted True, drains normally",
      entry_ok["interrupted"] is True and entry_ok["interrupt_error"] is None
      and cli_ok.advanced_past_warning is True)


# Codex: failure is arbitrated only AFTER close() drains a late reached-limit.
class _FakePopen:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


with tempfile.TemporaryDirectory() as td:
    captured_argv = []
    original_popen = codex_leg.subprocess.Popen

    def capture_popen(argv, **_kwargs):
        captured_argv.append(list(argv))
        return _FakePopen()

    codex_leg.subprocess.Popen = capture_popen
    try:
        root = Path(td)
        raw_dir = root / "raw"
        raw_dir.mkdir()
        gated_codex = root / "gated-codex"
        direct_client = codex_leg.AppServerClient(
            ChainedLog(root / "l.jsonl"),
            raw_dir,
            executable=gated_codex,
        )
        direct_client.close()
    finally:
        codex_leg.subprocess.Popen = original_popen
    check("Codex app-server Popen argv starts with the exact gated executable",
          captured_argv == [[str(gated_codex), "app-server"]])


CODEX_RESPOND_EXECUTABLE_MATCHES = []


class _FakeAppServerClient:
    def __init__(self, log, raw_dir, *, executable,
                 on_close_stop=None, close_raises=None):
        self.executable = str(executable)
        self.fatal = []
        self.declined = []
        self.item_events = []
        self.relayed_item_decisions = {}
        self.rate_limit_events = []
        self.rate_limit_stop = None
        self.model_label = "codex (test)"
        self.relay = PermissionRelay(log, ForbiddenPresenter(), raw_dir)
        self._on_close_stop = on_close_stop
        self._close_raises = close_raises

    def close(self):
        if self._on_close_stop:  # a reached-limit only drained during close()
            self.rate_limit_stop = self._on_close_stop
            self.rate_limit_events.append({"rateLimits":
                                           {"rateLimitReachedType": self._on_close_stop}})
        if self._close_raises:
            raise self._close_raises


def _run_codex(*, run_turn, on_close_stop=None, close_raises=None):
    stash = {}
    expected_path = None

    def factory(log, raw_dir, *, executable):
        CODEX_RESPOND_EXECUTABLE_MATCHES.append(str(executable) == expected_path)
        stash["client"] = _FakeAppServerClient(log, raw_dir,
                                               executable=executable,
                                               on_close_stop=on_close_stop,
                                               close_raises=close_raises)
        return stash["client"]

    saved = {n: getattr(codex_leg, n) for n in
             ("AppServerClient", "_handshake", "_assert_chatgpt_account",
              "_served_models", "_start_thread", "_run_turn", "_audit_items")}
    codex_leg.AppServerClient = factory
    codex_leg._handshake = lambda c: None
    codex_leg._assert_chatgpt_account = lambda c: {"planType": "plus"}
    codex_leg._served_models = lambda c: ({"gpt-5.5"}, "gpt-5.5")
    codex_leg._start_thread = lambda c, ws, model=None: (
        "tid", {"model": "gpt-5.5", "modelProvider": "openai"})
    codex_leg._run_turn = run_turn
    codex_leg._audit_items = lambda c, t, u: None
    try:
        with tempfile.TemporaryDirectory() as td:
            gated_path = Path(td) / "gated-codex"
            expected_path = str(gated_path)
            result = codex_leg.respond(
                "in",
                ChainedLog(Path(td) / "l.jsonl"),
                Path(td) / "raw",
                Path(td) / "ws",
                executable=gated_path,
            )
            stash["gated_path"] = str(gated_path)
            return result
    finally:
        for n, v in saved.items():
            setattr(codex_leg, n, v)


def _boom(c, t, i):
    raise AppServerError("boom")


try:
    _run_codex(run_turn=_boom, on_close_stop="rate_limit_reached")
    check("Codex late reached-limit + turn failure → PLAN USAGE WARNING", False)
except AppServerError as exc:
    check("Codex late reached-limit + turn failure → PLAN USAGE WARNING",
          "PLAN USAGE WARNING" in str(exc) and "boom" in str(exc))


def _empty_turn(c, t, i):
    return "turn-1"  # completes, but the fake yields no agentMessage items


try:
    _run_codex(run_turn=_empty_turn, on_close_stop="rate_limit_reached")
    check("Codex warning outranks empty-text failure", False)
except AppServerError as exc:
    check("Codex warning outranks empty-text failure",
          "PLAN USAGE WARNING" in str(exc) and "no agentMessage" in str(exc))

# primary failure + failed close(): primary leads, secondary surfaced (R3 polish)
try:
    _run_codex(run_turn=_boom, close_raises=RuntimeError("socket stuck"))
    check("Codex primary failure surfaces secondary close fault", False)
except AppServerError as exc:
    check("Codex primary failure surfaces secondary close fault",
          "boom" in str(exc) and "secondary faults during shutdown" in str(exc)
          and "socket stuck" in str(exc))

check("Codex respond passes its exact gated executable to AppServerClient",
      bool(CODEX_RESPOND_EXECUTABLE_MATCHES)
      and all(CODEX_RESPOND_EXECUTABLE_MATCHES))

print()
if FAILS:
    print(f"M1 INVARIANTS FAILED: {len(FAILS)}")
    sys.exit(1)
print("M1 INVARIANTS — all hold")
