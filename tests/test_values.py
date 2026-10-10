"""hx.values: wide-value encoding, parsing, equality (CVA6 review H1)."""
import decimal
import json

import pytest

from hx import values as V


def test_safe_integer_boundaries():
    assert V.encode(2 ** 53 - 1) == 2 ** 53 - 1 and V.encode(-(2 ** 53 - 1)) == -(2 ** 53 - 1)
    assert V.encode(2 ** 53) == "0x20000000000000" and V.encode(-(2 ** 53)) == "-0x20000000000000"
    assert V.encode(2 ** 53 + 1) == "0x20000000000001"
    assert V.encode(0) == 0 and V.encode(-7) == -7 and V.encode(True) == 1


def test_chunked_decimal_conversion_matches_decimal_module():
    decimal.getcontext().prec = 20000
    for n in (1, 3999, 4000, 4001, 8000, 8001, 12345):
        s = "".join(str((i * 7 + 3) % 10) for i in range(n)).lstrip("0") or "0"
        assert V.int_from_decimal(s) == int(decimal.Decimal(s))
        assert V.int_from_decimal("-" + s) == -int(decimal.Decimal(s))
    assert V.int_from_decimal("9" * 5000) == 10 ** 5000 - 1
    assert V.int_from_decimal("1" + "0" * 4321) == 10 ** 4321
    with pytest.raises(ValueError):
        V.int_from_decimal("12a")


def test_huge_legacy_decimal_equals_hex_literal():
    n = 10 ** 5000 + 12345                     # 5,001 decimal digits: beyond the default int<->str limit
    dec = "1" + "0" * 4995 + "12345"
    assert V.parse(dec).int == n
    assert V.equal(dec, f"{n.bit_length()}'h{n:x}")
    assert V.equal(dec, "0x" + format(n, "x"))
    assert not V.equal(dec, "0x" + format(n + 1, "x"))
    enc = V.encode(dec)
    assert isinstance(enc, str) and enc.startswith("0x") and V.parse(enc).int == n
    # the loader hook never calls int() on the whole token
    doc = json.loads('{"v": %s, "w": -%s, "s": 42, "b": 9007199254740991}' % (dec, dec), parse_int=V.parse_int_token)
    assert doc["v"] == enc and doc["w"] == "-" + enc and doc["s"] == 42 and doc["b"] == 2 ** 53 - 1
    assert json.loads('{"v": 9007199254740993}', parse_int=V.parse_int_token)["v"] == "0x20000000000001"
    assert json.loads('{"v": -9007199254740993}', parse_int=V.parse_int_token)["v"] == "-0x20000000000001"


def test_verilator_literals():
    assert V.encode("32'sh10") == 16 and V.encode("2'h3") == 3 and V.encode("8'd255") == 255 and V.encode("7") == 7
    assert V.encode("4'b1010") == 10 and V.encode("'h1") == 1
    wide = "17270'h" + "1" + "0" * 4313 + "57C0"                            # 4,318 hex digits, fits 17,270 bits
    assert V.encode(wide) == "17270'h1" + "0" * 4313 + "57c0"               # lossless, canonical lowercase/no underscores
    assert V.parse(V.encode(wide)).int == int("1" + "0" * 4313 + "57c0", 16)
    assert V.encode("64'hFFFF_FFFF_FFFF_FFFF") == "64'hffffffffffffffff"
    assert V.encode("64'd18446744073709551615") == "64'hffffffffffffffff"  # decimal literal re-based to hex
    assert V.fmt(V.encode(wide)) == "17270'h10000000…57c0" and V.fmt(255) == "255" and V.fmt("8'hff") == "8'hff"
    assert V.fmt(2 ** 60) == "0x1000000000000000" and V.fmt(2 ** 200) == "0x10000000…0000"


def test_signed_and_width_rules():
    assert V.equal("32'shfffffffb", -5) and V.equal(-5, "32'shfffffffb")
    assert not V.equal("32'shfffffffb", "32'hfffffffb")                        # signedness differs, value differs
    assert V.parse("32'shfffffffb").int == -5 and V.parse("32'hfffffffb").int == 4294967291
    assert not V.equal("32'h1", "64'h1")                                        # both widths known and different
    assert V.equal("64'h20000000000001", "9007199254740993") and V.equal("64'h20000000000001", 9007199254740993)
    assert V.equal("8'h1", 1) and V.equal("8'sh1", 1)                           # unknown width/sign on one side


def test_unknown_bits():
    assert V.encode("4'bxxxx") == "4'bxxxx" and V.encode("8'hx") == "8'bxxxxxxxx" and V.encode("4'b1x") == "4'b001x"
    assert V.equal("4'bxxxx", "4'bxxxx") and V.equal("8'hx", "8'bxxxxxxxx")
    assert not V.equal("4'bxxxx", "4'bxxzz") and not V.equal("8'b0000_000x", "8'h00") and not V.equal("8'h00", "8'b0000_000x")
    assert V.parse("4'b1x").int is None and V.encode("'z") == "'bz"
    assert V.encode('"abc"') == '"abc"' and V.equal('"abc"', '"abc"') and not V.equal('"abc"', '"abd"')


def test_json_safe_and_roundtrip():
    doc = {"a": [1, 2 ** 60, {"b": -(2 ** 70)}], "c": "x", "d": 2 ** 53 - 1}
    safe = V.json_safe(doc)
    assert safe == {"a": [1, "0x1000000000000000", {"b": "-0x400000000000000000"}], "c": "x", "d": 2 ** 53 - 1}
    back = json.loads(json.dumps(safe), parse_int=V.parse_int_token)
    assert back == safe and V.parse(back["a"][1]).int == 2 ** 60
