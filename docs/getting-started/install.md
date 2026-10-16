# Install and choose a frontend

## Install from a checkout

Requires Python 3.10 or newer. These tutorials use a repository checkout so that
the example fixtures and preparation helper are available:

```bash
git clone https://github.com/CansWang/hierX.git
cd hierX
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
hx --help
```

Run the remaining commands in that activated environment. If using an existing
checkout, begin with the virtual environment commands. The base install includes
libclang bindings, the viewer, MCP, and Pyright with its packaged Node.js runtime.
It does not install every external language toolchain.

## Choose a frontend

| Input | Additional requirements | Graph precision |
|---|---|---|
| C/C++ | Compilation database; compiler/SDK headers; `clang` for resource-header discovery | `exact`: layouts, globals, macros, and call sites |
| SystemVerilog/Verilog | `verilator`; source list and project flags | `exact`: instances, ports, parameters, and packed layouts |
| Rust | Rust toolchain, `rust-analyzer`, `rust-src`, and a root `Cargo.toml` | `lsp`: server-provided calls and signatures |
| Python | No extra server install; Pyright is included | `lsp`: server-provided calls and annotated fields |
| SPICE/ngspice netlists | No simulator for extraction | `syntax`: hierarchy, terminals, connectivity, and symbolic expressions |

On Ubuntu/Debian, install C/C++ and HDL prerequisites with:

```bash
sudo apt-get update
sudo apt-get install -y clang build-essential verilator
```

With [Rustup](https://rustup.rs/) installed:

```bash
rustup toolchain install stable --profile minimal
rustup component add --toolchain stable rust-analyzer rust-src
. "$HOME/.cargo/env"
```

For the optional netlist oracle, install `ngspice` through your system package
manager. Extraction works without it. Vendor executables listed by hx's tool
registry do not imply support for their dialects: the current parser accepts
`spice` and `ngspice`.

Go via `gopls` is experimental and has no integration-test coverage. Install the
Go SDK and `gopls` separately and request `--lang go`; it is not a documented
production frontend.

## Precision affects what you can conclude

C/C++ layouts describe the selected build configuration. HDL layout sizes are in
bits, while C/C++ sizes are in bytes. LSP graphs omit memory layouts and globals,
and cannot show indirect calls the language server does not report. Netlists
preserve parameter expressions without evaluating them or selecting model bins.

Language is normally inferred from the entry file extension. Override it with
`--lang`; use `--dialect` for a netlist dialect. Continue with
[preparing the examples](examples.md).

## Build this documentation locally

From the checkout in the activated environment:

```bash
python -m pip install -e '.[docs]'
mkdocs serve
```

Open `http://127.0.0.1:8000/`. This is the documentation server; `hx serve` runs
the graph viewer on port 8765. See [contributing docs](../contributing.md) for
strict builds and checks.
