"""Calls into overloaded stub declarations: typeshed builtins and a local stub package (review: overload fan-out)."""
import fakelib

from .dma import DmaChan


def use_overloads(ch: DmaChan) -> str:
    busy = getattr(ch, "busy", False)
    a = fakelib.A()
    b = fakelib.B()
    first = a.get(1)
    second = a.get("x")
    third = a.get(2.0)
    other = b.get(1)
    top = fakelib.fetch(1)
    return ",".join([str(busy), str(first), str(second), str(third), str(other), str(top)])
