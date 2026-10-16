# Netlist dialect matrix

TLDR: what each SPICE-family construct does in hx today, per dialect profile, with the fixture and test that
prove it. "supported" = parsed into the typed statement model and resolved (ids, nets, terminals, diagnostics);
"partial" = preserved with a diagnostic, not resolved; "planned" = a later phase (N2 HSPICE/Xyce, N3 Spectre).
Terms: deck = top-level netlist file; subckt = `.subckt` definition; guard = the set of enclosing `.if`
constraints an occurrence lives under; oracle = a simulator run only to cross-check hx's structure.

| construct | spice | ngspice | hspice (N2) | xyce (N2) | spectre (N3) | fixture / test |
|---|---|---|---|---|---|---|
| grammar | `spice` (letter-prefixed elements) | `spice` | `spice` | `spice` | `spectre` (master-name resolution) | `hx/netlist/grammar.py` |
| profile | `SPICE` | `NGSPICE = replace(SPICE, …)` (data only) | planned | planned | planned | `test_netlist_lexer.py::test_profiles_differ_only_in_data` |
| title line (deck line 1 is the title whatever it says; an include keeps line 1) | supported | supported | planned | planned | n/a | `title/dot_title.sp`, `params/inc_first_subckt.inc`; `test_netlist_parser.py::test_title_rule_precedes_structure`, `::test_include_keeps_a_subckt_on_line_one` |
| `+` continuation with per-piece spans | supported | supported | planned | planned | `\` planned | `test_netlist_lexer.py` |
| comments `*` line, `$`/`;` inline; `//` inline | `$` `;` | `$` `;` `//` | planned | planned | `//` `/* */` planned | `params/params.sp`; `test_netlist_parser.py::test_params_keyword_and_double_slash_comment` |
| inline-comment guard inside `{…}`/`'…'`/`"…"` (`$G_1` kept) | supported | supported | planned | planned | n/a | `test_netlist_lexer.py` |
| `.subckt … .ends`, `PARAMS:`, defaults | supported | supported | planned | planned | `subckt … ends` planned | `ota/ota.sp`, `params/params.sp` |
| `X` instance with parameters; terminal count from the definition | supported | supported | planned | planned | planned | `ota/`, `fail/wrong_terminals.sp` (`terminal-count-mismatch`) |
| devices R C L D V I E G F H K J Z M Q (arity from the family table) | supported | supported | planned | planned | planned | `bjt/bjt.sp` (3/4-terminal Q), `numeric_nets/numeric.sp`; `test_netlist_resolve.py::test_bjt_arity` |
| optional model token located by scope lookup (`q2 c b e npnmod`) | supported | supported | planned | planned | n/a | `test_netlist_parser.py::test_element_grammar_resolves_optional_model_by_scope` |
| `.model` cards, continuation parameters | supported | supported | planned | planned | `model` planned | `ota/lib/devices.inc`, `fail/missing_model.sp` (`missing-model`) |
| model bin families (`nm.0 … nm.15`) | supported (`status: binned`) | supported | planned | planned | n/a | `bins/bins.sp`; `test_netlist_index.py::test_model_bin_family_resolution` |
| numeric bin selection by W/L | planned (N2) | planned | planned | planned | planned | — |
| `.include` (absolute → including dir → `--search-path` → root), probes recorded | supported | supported | planned | planned | `include` planned | `oracle/search_path/`; `test_netlist_index.py::test_probes_record_missing_candidates`, `test_project.py::test_watch_reacts_to_a_newly_created_include_and_a_shadowing_candidate` |
| `.lib "file" section` / `.lib sect … .endl` (selected section only) | supported | supported | planned | planned | `section` planned | `ota/lib/corners.lib` |
| missing include / include cycle | error diagnostic, extraction continues | same | planned | planned | planned | `fail/missing_include.sp`, `fail/include_cycle.sp` |
| `.param` (symbolic; never evaluated) | supported | supported | planned | planned | `parameters` planned | `ota/ota.sp`; `test_diff.py::test_spice_model_card_and_param_definition_changes` |
| `.global` nets, ground `0`/`gnd` | supported | supported | planned | planned | planned | `globals/globals.sp` |
| scoped declarations (local subckt/model shadow global; same-scope duplicate = ambiguous) | supported | supported | planned | planned | planned | `scoped/scoped.sp`, `fail/duplicate_def.sp`; `test_netlist_index.py::test_scoped_definitions_and_model_shadowing`, `::test_same_scope_duplicate_is_ambiguous` |
| `.if / .elseif / .else / .endif` with guards, alternatives, guarded duplicates | n/a | supported | planned (`.if` exists in HSPICE too) | supported later | n/a | `conditional/*`; `test_netlist_index.py::test_guard_compatibility_is_constraint_based`, `test_netlist_hash.py::test_swapping_identical_condition_blocks_keeps_ids` |
| `.control … .endc` (verbatim block; stripped from the oracle input) | n/a | supported | n/a | n/a | n/a | `oracle/search_path/inc/with_control.inc`; `test_netlist_oracle.py::test_control_blocks_in_includes_are_stripped` |
| `.csparam`, `.option`, analyses, `.print`/`.probe`, `.end` | recorded as directives with a role | same | planned | planned | planned | `circuit.directives` |
| `.prot … .unprot` (encrypted) | preserved (`encrypted-content`) | same | planned | planned | n/a | `fail/unsupported.sp` |
| `.alter`, `.measure`, `.func`, `.data`, `.step` | partial (`unsupported-directive`) | partial | planned | planned | planned | `fail/unsupported.sp` |
| `Y` (Xyce) and `A` (XSPICE) devices | partial (`unknown-device-family`) | partial | — | planned | n/a | `fail/unsupported.sp` |
| recursion and depth limit (`MAX_HIER_DEPTH = 64`) | supported | supported | planned | planned | planned | `fail/recursive.sp` |
| `simulator lang=` switching | refused (later phase) | refused | — | — | planned | `test_cli_langs.py::test_spice_cli` |
| switches `S` (4 terminals + model) and `W` (2 terminals, controlling source, then model) | supported | supported | planned | planned | planned | `switches/switches.sp`; `test_netlist_parser.py::test_switch_grammar_orders_refs_before_models`, live agreement |
| controlling reference with guarded alternatives (`F`/`H`/`K` → a source declared in `.if`/`.else`); duplicate targets `ambiguous-reference`; missing target = ghost | n/a | supported | planned | planned | n/a | `conditional/ref_alternatives.sp`, `fail/ref_duplicate_and_missing.sp`; `test_netlist_resolve.py::test_unconditional_reference_keeps_guarded_alternatives` |
| nested guarded bindings (a device under two guarded ancestors takes its own chain's nets) | n/a | supported | planned | planned | n/a | `conditional/nested_guard.sp`; `test_netlist_resolve.py::test_nested_guarded_bindings_follow_the_ancestor_chain`, `test_diff.py::test_spice_ancestor_rewiring_is_reported_once` |
| per-branch declarations all serialised (same file included from both branches too); same-scope duplicates both kept | n/a | supported | planned | planned | n/a | `conditional/per_branch.sp`, `conditional/shared_include.sp`, `fail/duplicate_model.sp`; `test_spice_fe.py::test_per_branch_declarations_are_all_serialized` |
| condition-aware scope hashes; expression spacing ignored (`{w * 2}` ≡ `{w*2}`) | supported | supported | planned | planned | planned | `test_netlist_hash.py::test_condition_only_edit_moves_scope_hashes`, `::test_statement_and_scope_hash_rules` |
| standalone library entry (`lib.inc:@name` without `--deck`: line 1 kept when it is a dot-directive); `title-is-directive` on a deck | supported | supported | planned | planned | n/a | `params/inc_first_subckt.inc`; `test_spice_fe.py::test_standalone_library_entry_keeps_line_one` |
| oracle | ngspice `listing expand` (rendered closure on stdin); required-model families always compared; subtree filters both sides; definition entries per unguarded instance with deck context | same | HSPICE registry entry only | Xyce `-syntax` / `-norun -namesfile`, XDM re-parse (N2) | Spectre registry entry only | `test_netlist_oracle.py`, `hx netlist check` |

Verified simulator facts (ngspice 45.2, X11 build) behind the oracle rules live in the SSOT "Phase N1" section.
