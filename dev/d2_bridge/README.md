# Upstream D2 compiler bridge

This Go module adapts unmodified D2 v0.9.0, commit
`d5a51743b6d5c00f1ec6f8340003f5d5a6ba4eda`, to the `hx-d2-bridge/1` JSON
protocol. Build explicitly with `bash dev/scripts/setup_d2_bridge.sh`. Setup uses
Go 1.27+ when available or installs SHA-256-verified Go 1.27.3 under
`~/.local/lib/go1.27.3`; `--go-dir DIR` changes that fallback SDK location and
`--no-bootstrap` requires a compatible existing compiler. SDK setup supports
Linux/macOS on amd64/arm64. It changes no system installation or shell profile.
The SDK remains available after setup; add its `bin` directory to PATH to use Go
interactively. `go.mod` and `go.sum` pin the dependency graph. No compiler fork,
layout, rendering or Hx interpretation lives here. D2 is MPL-2.0; its source and
license are available at <https://github.com/d2lang/d2/tree/v0.9.0>.

`--version` prints identities. Otherwise `--root ROOT --input RELATIVE.d2`
compiles upstream D2 and returns objects (qualified IDs/key segments, labels,
classes, links and source references), directed edges, diagnostics, ignored
presentation indicators and hashes of files actually read. Exit 0 means upstream
compilation succeeded, 1 means a reported compile error, 2 means tool setup or
invocation failed. Python independently checks the protocol and interpreter rules.

Imports use a confined filesystem with symlink checks. Each opened file is read
into an immutable per-compilation byte snapshot; repeat imports use those bytes
and report their hash. There is no runtime network access. Ordinary Hx installation
does not build or install this module. Test with `go test ./...`.

The small adapter is Go because it calls D2's upstream Go compiler directly,
preserving native import/class/key semantics. It emits JSON for Python's Hx
interpretation layer; the layout/presenter remains JavaScript. Go is only a
build-time requirement for this executable.
