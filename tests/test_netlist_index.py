"""DesignIndex: scoped, guard-aware lookup; bin families; include resolution, probes, cycles and sections."""
import os
import shutil

import pytest

from hx.netlist.index import DesignIndex
from hx.netlist.names import EMPTY_GUARD, chain_id, guard_compatible
from hx.netlist.profiles import NGSPICE

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "spice")


def _index(deck, search_paths=(), root=None):
    root = root or os.path.dirname(deck)
    return DesignIndex(deck, NGSPICE, "ngspice", list(search_paths), root, None).build()


def test_scoped_definitions_and_model_shadowing():
    idx = _index(os.path.join(FIX, "scoped", "scoped.sp"))
    keys = sorted((k[0], "/".join(k[1]), k[2]) for k in idx.decls)
    assert ("subckt", "", "leaf") in keys and ("subckt", "outer_a", "leaf") in keys and ("model", "outer_a", "dmod") in keys
    inner = idx.lookup("subckt", ("outer_a",), "leaf", EMPTY_GUARD)
    outer = idx.lookup("subckt", ("outer_b",), "leaf", EMPTY_GUARD)
    assert inner.scope_found == ("outer_a",) and outer.scope_found == () and not inner.ambiguous
    assert idx.lookup("model", ("outer_a",), "dmod", EMPTY_GUARD).alternatives[0].scope == ("outer_a",)
    assert [d.scope for d in idx.shadowed("model", ("outer_a",), "dmod")] == [()]


def test_guard_compatibility_is_constraint_based():
    """A model declared under .if(usemodel) is visible to a device under .if(usedevice): neither guard prefixes the
    other, they are simply compatible."""
    idx = _index(os.path.join(FIX, "conditional", "independent.sp"))
    use_device = frozenset({(chain_id((), ["(usedevice > 0)"]), 0)})
    lk = idx.lookup("model", (), "dm", use_device)
    assert len(lk.alternatives) == 1 and not lk.ambiguous
    decl = lk.alternatives[0]
    assert decl.guard and guard_compatible(decl.guard, use_device) and decl.guard != use_device


def test_overlapping_guarded_declarations_are_ambiguous():
    idx = _index(os.path.join(FIX, "conditional", "independent.sp"))
    lk = idx.lookup("model", (), "dup", EMPTY_GUARD)
    assert len(lk.alternatives) == 2 and lk.ambiguous                    # independent guards can both hold


def test_guard_compatible_lookup_keeps_alternatives():
    idx = _index(os.path.join(FIX, "conditional", "cond.sp"))
    lk = idx.lookup("model", (), "dm", EMPTY_GUARD)
    assert len(lk.alternatives) == 3 and not lk.ambiguous               # if / elseif / else: mutually exclusive
    cid = chain_id((), ["(pick > 0)", "(pick < 0)"])
    in_first = idx.lookup("model", (), "dm", frozenset({(cid, 0)}))
    assert len(in_first.alternatives) == 1 and in_first.alternatives[0].line == 20


def test_model_bin_family_resolution():
    idx = _index(os.path.join(FIX, "bins", "bins.sp"))
    lk = idx.lookup("model", ("nm",), "nm", EMPTY_GUARD)
    assert not lk.alternatives and [d.name for d in lk.bins] == ["nm.0", "nm.1", "nm.2"] and lk.found
    assert idx.is_model_visible(("nm",), "nm", EMPTY_GUARD)


def test_same_scope_duplicate_is_ambiguous():
    idx = _index(os.path.join(FIX, "fail", "duplicate_def.sp"))
    lk = idx.lookup("subckt", (), "dup", EMPTY_GUARD)
    assert len(lk.alternatives) == 2 and lk.ambiguous


def test_probes_record_missing_candidates(tmp_path):
    idx = _index(os.path.join(FIX, "fail", "missing_include.sp"))
    assert [d["code"] for d in idx.diagnostics] == ["missing-include"]
    p = idx.probes[0]
    assert p["requested"] == "nowhere.inc" and p["resolved"] is None and all(not c["exists"] for c in p["candidates"])
    # a search-path-only include: the deck-directory candidate is probed first and recorded as missing
    deck = os.path.join(FIX, "oracle", "search_path", "deck.sp")
    idx2 = _index(deck, search_paths=["inc"])
    p2 = next(p for p in idx2.probes if p["requested"] == "only_here.inc")
    assert p2["candidates"][0]["exists"] is False and p2["resolved"].endswith(os.path.join("inc", "only_here.inc"))
    assert idx2.lookup("subckt", (), "shared", EMPTY_GUARD).found and not idx2.diagnostics
    assert _index(deck).diagnostics[0]["code"] == "missing-include"      # without the search path the include is missing


def test_include_cycle_and_sections():
    idx = _index(os.path.join(FIX, "fail", "include_cycle.sp"))
    assert [d["code"] for d in idx.diagnostics] == ["include-cycle"]
    names = [st.name for st, _g in idx.top_items if hasattr(st, "letter")]
    assert sorted(names) == ["r1", "r_a", "r_b"]                                           # each file read once
    ota = _index(os.path.join(FIX, "ota", "ota.sp"))
    roles = [(f.role, f.section) for f in ota.files]
    assert roles == [("deck", None), ("include", None), ("lib", "tt"), ("include", "tt")]
    assert any(p.endswith("tt_models.inc") for p in ota.deps) and not any(p.endswith("ff_models.inc") for p in ota.deps)
    assert ota.stats["sections"] == [[os.path.join("lib", "corners.lib"), "tt"]] and not ota.diagnostics


def test_forward_reference_and_params():
    idx = _index(os.path.join(FIX, "ota", "ota_reformatted.sp"))
    assert idx.lookup("subckt", (), "five_t_opamp", EMPTY_GUARD).found      # defined after its instances
    assert idx.lookup("param", (), "vdd_val", EMPTY_GUARD).alternatives[0].expr == "1.8"
    assert idx.globals == {"vdd": "VDD"} and idx.title.startswith("Five-transistor")


def test_library_reference_errors_are_diagnostics_and_the_selected_section_still_loads():
    """A missing library file, a missing section, a section that pulls itself and an inline section outside any
    reference each have their own code; the good section's model is still visible and the unselected one is not."""
    idx = _index(os.path.join(FIX, "fail", "lib_errors.sp"))
    by_code = {}
    for d in idx.diagnostics:
        by_code.setdefault(d["code"], []).append(d["message"])
    assert sorted(by_code) == ["include-cycle", "lib-section-skipped", "missing-include", "missing-lib-section"]
    assert ".lib 'nowhere.lib' not found" in by_code["missing-include"][0]
    assert "section 'nosuch' not found" in by_code["missing-lib-section"][0]
    assert "section 'tt' is already being read" in by_code["include-cycle"][0]
    assert ".lib inline" in by_code["lib-section-skipped"][0]
    lk = idx.lookup("model", (), "nch", EMPTY_GUARD)
    assert lk.found and len(lk.alternatives) == 1 and "level=1" in lk.alternatives[0].params_text   # tt once, ff never
    assert idx.stats["sections"] == [["sections.lib", "tt"]]
