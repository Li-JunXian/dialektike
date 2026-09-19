# Codex app-server schema generation — 0.145.0

Generated locally on 2026-07-24 from the authenticated standalone runtime:

```text
codex app-server generate-json-schema \
  --out vendor/codex-app-server-0.145.0 \
  --experimental
```

Runtime version: `codex-cli 0.145.0` (Apple Silicon standalone package).

The generator produced 347 JSON schema files. Before this provenance file was
added, the SHA-256 of the sorted per-file SHA-256 manifest was:

```text
696aaf875cfb94c9ea105be0338d025a930992afe46340a17996ec32759966d2
```

Key contract hashes:

```text
cb228b049453ac932668bdfb552bf3f87a967eb6d6057b652eb236c05eb1288b  codex_app_server_protocol.v2.schemas.json
6e5e52922a2cd66123b074ac0ef197557a151120db815b3a6ca8402da5aec7a0  v2/ModelListResponse.json
b3685411ceb8ad264a1920e8facd66301e5280948ef9c2a6871b95d4c19da639  v2/ThreadStartParams.json
b4ae167f12f0ed48e14d014eaa131c097dc237613081e597e08f486149312933  v2/ThreadStartResponse.json
f23021c02d28b60fccb6dcaaace9ff676127065f8254537265d6622656860dca  v2/TurnStartParams.json
49132b57b09f09dc545ed1cd373c12eede6e880e9afb54ae50add78bb42490cd  v2/TurnInterruptParams.json
```

The earlier `vendor/codex-app-server-0.139.0/` tree remains untouched as M1
historical evidence.
