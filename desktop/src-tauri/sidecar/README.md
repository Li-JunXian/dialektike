# Packaged sidecar resource

`scripts/build_macos_sidecar.py` creates the ignored
`dialektike-sidecar` arm64 executable in this directory. Tauri copies that
fixed resource into the native application bundle; the Rust supervisor never
accepts a WebView-supplied command or path.

Build order from the repository root:

```sh
./venv/bin/python -m pip install -e '.[macos-release]'
cd desktop
npm run tauri build
```

The Tauri pre-build runs `scripts/build_macos_sidecar.py` automatically. It
performs no-model protocol and gate-boundary smokes under a Finder-like
minimal `PATH` before the fixed resource is bundled. The checked-in Tauri
configuration uses ad-hoc signing (`-`) for Live's local build. Distribution
outside this Mac additionally requires replacing that identity with Live's
Developer ID Application identity and supplying notarization credentials;
neither belongs in the repository.
