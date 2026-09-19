"""PyInstaller entry point for the native macOS sidecar resource."""

from dialektike.sidecar import main


if __name__ == "__main__":
    raise SystemExit(main())
