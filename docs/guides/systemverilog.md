# SystemVerilog and Verilog

Install `verilator` and prepare a project from the checkout:

```bash
python examples/prepare.py sv /tmp/hx-sv-tutorial
cd /tmp/hx-sv-tutorial
```

<!-- hx:test sv-extract -->
```bash
hx extract rtl/top.sv:top -f files.f --top top --depth 3
```

The output contains module-instance nodes, explicit port directions, parameters,
connections on `instance` edges, and functions/tasks where reached. Open it with
`hx serve --open`.

## Use the simulator's source list

Real designs require package ordering, include directories, defines, and a chosen
configuration. Supply the same Verilator argument list your build uses. `-f` and
nested `-F` entries follow Verilator's path and environment expansion rules:
`-f` paths resolve against the working directory, `-F` paths against the list's
directory. Include directories, parameter overrides, and defines in that list
are part of the extraction configuration.

The CLI exposes `-f`/`--filelist`; an additional `-F` can be passed through repeated
`--extra-arg` values. `--sv-file GLOB` supplies explicit source globs. Automatic
discovery of a lone root `*.f` or all HDL files is useful for small examples, not
as a substitute for a real build configuration.

## Focus on an instance

<!-- hx:test sv-instance -->
```bash
hx extract rtl/core.sv:top.u_core_b.u_alu -f files.f --top top --include-callers --depth 1 -o .hx/alu.json
```

The entry file must define a module on that path. Generate-array paths use
source spelling such as `top.gen_lane[0].u_lane`; quote brackets in shell commands.
`--include-callers` includes parent instances above the chosen occurrence.

HDL `size`, `offset`, and `bit_width` values describe bits, with packed-struct
offsets measured from the most significant side. Types specialized to different
layouts have different IDs. Compiler/elaborator precision does not mean a
simulation trace: signals and connections describe elaborated structure.

Cache identity includes the expanded argument files, configuration, top module,
extra arguments, and Verilator version. A warning count is separate from errors;
use `-v` to inspect diagnostics.
