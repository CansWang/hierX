# Prepare tutorial projects

Run the helper from the repository root with the virtual environment active:

```bash
python examples/prepare.py c /tmp/hx-c-tutorial
cd /tmp/hx-c-tutorial
```

The helper copies an existing test fixture into a new directory. It never
overwrites an existing destination. Choose a different path to start again.
All edits, caches, graphs, and snapshots in the tutorials belong to that copy.

For C and C++, it also creates `build/compile_commands.json` using absolute
workspace paths and relative source paths. This describes the example compile
flags; preparation does not execute a compiler. On your own project, obtain a
compilation database from the actual build, for example with CMake's
`-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` or `bear -- make`.

| Helper argument | Example entry | Tutorial or guide |
|---|---|---|
| `c` | `src/main.c:app_run` | [C/C++ review](../tutorials/c-review.md) |
| `cpp` | `src/main.cpp:run` | [C/C++ guide](../guides/c-cpp.md) |
| `netlist` | `ota.sp:.` | [Netlist quickstart](../tutorials/netlists.md) |
| `sv` | `rtl/top.sv:top` | [SystemVerilog guide](../guides/systemverilog.md) |
| `rust` | `src/lib.rs:app_run` | [Rust guide](../guides/rust.md) |
| `python` | `hxfix/main.py:app_run` | [Python guide](../guides/python.md) |

Return to the checkout before running `examples/prepare.py` for a different
language. Each tutorial names its destination explicitly. The examples are
source inputs for extraction; you do not need to execute their application code.

The helper and fixtures are checkout resources, not part of the installed hx
command. You can use an absolute path to the helper when working elsewhere.
