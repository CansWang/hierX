Advanced SystemVerilog fixture for the CVA6-review regressions (Phase 4.6): a 16,384-bit parameter,
module-scoped struct under two specializations (32/64-bit) plus an equal-size variant in tests, generate
`if`/`for` scopes with arrayed instances, shorthand `.clk` and `.*` connections, an anonymous inline struct
port, a SELRANGE warning, an environment-dependent file list (`env.f`, `$(HX_SV_CFG)`), and a nested
`-F lists/parent.f` → `-f sub/child.f` list (`root.f`) resolved with Verilator's rules.
