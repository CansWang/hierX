"""Numeric values that may be wider than JSON (and JavaScript) can carry.

Representation rule (schema hx/2):
  |v| <  2**53   -> JSON number
  |v| >= 2**53   -> lossless string: `<width>'<s>h<hex>` when the width is known (Verilator values, any base,
                    re-based to hex), `0x<hex>` / `-0x<hex>` when it is not (legacy numbers, plain ints)
  x/z literals   -> normalized bit pattern `<width>'b<0/1/x/z…>` (no integer value)
Hexadecimal is used for the wide forms because it is the one int<->str conversion CPython never limits; decimal
conversion of thousands of digits raises ValueError under the default 4,300-digit limit, which is exactly how a
17,270-bit CVA6 parameter broke extraction, every reader and the viewer (Infinity). Nothing here touches
`sys.set_int_max_str_digits`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Union

SAFE_MAX = 2 ** 53                     # JavaScript's exactly-representable integer bound (exclusive)
_CHUNK = 4000                          # below CPython's default int<->str limit
_LITERAL = re.compile(r"^\s*(\d+)?\s*'\s*([sS]?)\s*([bBoOdDhH])\s*([0-9a-fA-F_xXzZ?]+)\s*$")
_DECIMAL = re.compile(r"^\s*-?\d+\s*$")
_HEX = re.compile(r"^\s*(-?)0[xX]([0-9a-fA-F_]+)\s*$")
_UNBASED = re.compile(r"^\s*'([01xXzZ?])\s*$")
_BASE = {"b": 2, "o": 8, "d": 10, "h": 16}
_BITS_PER_DIGIT = {2: 1, 8: 3, 16: 4}


@dataclass(frozen=True)
class Value:
    int: Optional[int]            # resolved value (negative when a signed literal has its top bit set)
    width: Optional[int]          # bit width when the literal carried one
    signed: Optional[bool]        # True/False for literals, None when unknown
    bits: Optional[str]           # unresolved pattern or opaque text when `int` is None

    @property
    def resolved(self) -> bool:
        return self.int is not None


def int_from_decimal(s: str) -> int:
    """Exact int from a decimal string of any length without the 4,300-digit limit: left-to-right chunks of
    at most 4,000 digits, `v = v * 10**len(chunk) + int(chunk)` (a short trailing chunk is handled correctly)."""
    s = s.strip().replace("_", "")
    neg = s.startswith("-")
    if neg or s.startswith("+"):
        s = s[1:]
    if not s.isdigit():
        raise ValueError(f"not a decimal integer: {s[:20]!r}")
    v = 0
    for i in range(0, len(s), _CHUNK):
        chunk = s[i:i + _CHUNK]
        v = v * 10 ** len(chunk) + int(chunk)
    return -v if neg else v


def _hex(mag: int) -> str:
    return format(mag, "x")           # power-of-two base: never limited


def parse(v: Any) -> Value:
    """Interpret a stored value (JSON number, canonical string, or a Verilator/SystemVerilog literal)."""
    if v is None:
        return Value(None, None, None, None)
    if isinstance(v, bool):
        return Value(int(v), None, None, None)
    if isinstance(v, int):
        return Value(v, None, None, None)
    if not isinstance(v, str):
        return Value(None, None, None, str(v))
    s = v.strip()
    m = _HEX.match(s)
    if m:
        mag = int(m.group(2).replace("_", ""), 16)
        return Value(-mag if m.group(1) else mag, None, None, None)
    if _DECIMAL.match(s):
        return Value(int_from_decimal(s), None, None, None)
    m = _UNBASED.match(s)
    if m:                                           # '0 '1 'x 'z : unsized, unbased fill literals
        c = m.group(1).lower().replace("?", "z")
        return Value(int(c), None, None, None) if c in "01" else Value(None, None, None, f"'b{c}")
    m = _LITERAL.match(s)
    if not m:
        return Value(None, None, None, s)          # opaque text (string parameter, expression)
    width = int(m.group(1)) if m.group(1) else None
    signed = bool(m.group(2))
    base = _BASE[m.group(3).lower()]
    digits = m.group(4).replace("_", "").lower().replace("?", "z")
    if any(c in "xz" for c in digits):
        if base == 10:
            return Value(None, width, signed, s.replace("_", ""))
        n = _BITS_PER_DIGIT[base]
        bits = "".join(c * n if c in "xz" else format(int(c, base), f"0{n}b") for c in digits)
        if width is not None:
            if len(bits) > width:
                bits = bits[-width:]
            elif len(bits) < width:
                pad = bits[0] if bits and bits[0] in "xz" else "0"
                bits = pad * (width - len(bits)) + bits
        return Value(None, width, signed, f"{width if width is not None else ''}'{'s' if signed else ''}b{bits}")
    n = int_from_decimal(digits) if base == 10 else int(digits, base)
    if width is not None:
        n &= (1 << width) - 1
        if signed and width > 0 and (n >> (width - 1)) & 1:
            n -= 1 << width
    return Value(n, width, signed, None)


def canonical(val: Value) -> str:
    """Canonical wide string for a resolved value (callers decide that it does not fit a JSON number)."""
    n = val.int
    if val.width is not None:
        mag = n & ((1 << val.width) - 1)
        return f"{val.width}'{'s' if val.signed else ''}h{_hex(mag)}"
    return ("-" if n < 0 else "") + "0x" + _hex(abs(n))


def encode(x: Any) -> Union[int, str, None]:
    """Serialized form of a value: JSON number when |v| < 2**53, else the canonical string; x/z and opaque
    text are kept as normalized strings."""
    if x is None:
        return None
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, int):
        return x if abs(x) < SAFE_MAX else canonical(Value(x, None, None, None))
    val = parse(x)
    if val.int is not None:
        return val.int if abs(val.int) < SAFE_MAX else canonical(val)
    return val.bits


def equal(a: Any, b: Any) -> bool:
    """Numeric equality across representations: ints compare by value, widths and signedness only when both
    sides know them; unresolved (x/z) and opaque values compare by normalized text; mixed -> False."""
    va, vb = parse(a), parse(b)
    if va.int is not None and vb.int is not None:
        if va.int != vb.int:
            return False
        if va.width is not None and vb.width is not None and va.width != vb.width:
            return False
        if va.signed is not None and vb.signed is not None and va.signed != vb.signed:
            return False
        return True
    if va.int is None and vb.int is None:
        return va.bits == vb.bits and va.bits is not None
    return False


def fmt(x: Any, limit: int = 24) -> str:
    """Compact display: numbers as is; long strings as `17270'h10000000…57c0` (head 8, tail 4 hex digits)."""
    if x is None:
        return "?"
    if isinstance(x, int) and not isinstance(x, bool):
        return str(x) if abs(x) < SAFE_MAX else fmt(encode(x), limit)
    s = str(x)
    if len(s) <= limit:
        return s
    m = re.match(r"^(\d*'[sS]?[bodhBODH]|-?0[xX])(.*)$", s)
    if m and len(m.group(2)) > 12:
        return f"{m.group(1)}{m.group(2)[:8]}…{m.group(2)[-4:]}"
    return s[:limit - 1] + "…"


def json_safe(obj: Any) -> Any:
    """Recursively apply `encode` to every int in a JSON-like structure (legacy documents, in-memory dicts)."""
    if isinstance(obj, bool) or obj is None or isinstance(obj, (str, float)):
        return obj
    if isinstance(obj, int):
        return obj if abs(obj) < SAFE_MAX else encode(obj)
    if isinstance(obj, list):
        return [json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    return obj


def parse_int_token(tok: str) -> Union[int, str]:
    """`json.loads(parse_int=…)` hook: tokens of up to 16 digits are converted and kept as numbers when they
    fit; anything else is converted in chunks and re-encoded as `0x…`, so a 5,000-digit legacy number loads
    without ever calling int()/str() on the whole token."""
    digits = tok[1:] if tok[:1] in "-+" else tok
    if len(digits) <= 16:
        v = int(tok)
        return v if abs(v) < SAFE_MAX else encode(v)
    return encode(int_from_decimal(tok))
