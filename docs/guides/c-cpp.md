# C and C++

Use the [review tutorial](../tutorials/c-review.md) for a complete workflow.
C/C++ extraction uses libclang and your build's compilation database. The database
must describe the actual include paths, defines, language standard, and target.

## Configure your own project

Generate `compile_commands.json` with your build system and run from the project
root:

```bash
hx extract src/main.c:app_run --compile-commands build --depth 3
hx extract src/main.c:app_run --extra-arg=-DMODE=1 --exclude 'third_party/*'
```

The database argument can name a directory or the JSON file itself. Without an
override, hx searches the root and common build locations. Use `--resource-dir`
if `clang -print-resource-dir` discovers headers from the wrong Clang installation.
A cross-compiled project also needs the target SDK headers from its build flags.
`--extra-arg` is repeatable; the `=...` form avoids argparse treating a leading
minus in a value as another option.

## Try C++ overloads

From the checkout:

```bash
python examples/prepare.py cpp /tmp/hx-cpp-tutorial
cd /tmp/hx-cpp-tutorial
```

<!-- hx:test cpp-extract -->
```bash
hx extract src/main.cpp:run --depth 3
```

The graph distinguishes the `hw::Bus::write` overloads by parameter types in their
IDs. The current entry parser splits at the final colon, so namespace-qualified
C++ entries containing `::` cannot be passed directly; use the bare name `run`.
Stable IDs distinguish graph records but are not accepted as C/C++ CLI entries.
When several overloads share a name and file, lookup selects the first indexed
match. Start at an unambiguous caller to inspect its overload targets,
then use their IDs for graph and MCP queries.

## Interpret the result

C/C++ nodes have `precision: exact`. Struct sizes, alignment, and field offsets
are bytes, with separate bitfield offsets and widths. By-value and pointer-to-const
parameters default to `in`; other pointers and arrays default to `inout`. These
are heuristics (`dir_source: heuristic`); annotations can override them.

Function-pointer calls are recorded but are not resolved to every possible
runtime target. Templates record primary declarations without expanding all
instantiations. Build variants can have different bodies and layouts: IDs and
notes reflect the selected compilation database. See
[identity rules](../reference/graph.md#identity-and-hashes).

The cache lives under `.hx/cache/`. Repeating an unchanged extraction reuses
translation-unit summaries. `--no-cache` bypasses cache reads and writes.
