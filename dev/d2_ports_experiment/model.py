"""Private descriptive model and independent fixture expectations.

D2 owns the authored topology. These records are a test oracle, not another
architecture input format. Reusing a code symbol across diagram instances is
allowed; there are no ownership, type compatibility or behavior verdicts.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CodeRef:
    symbol: str
    member: str = "function"


@dataclass(frozen=True)
class Block:
    id: str
    parent: str | None
    code: CodeRef


@dataclass(frozen=True)
class Port:
    id: str
    block: str
    direction: str
    code: CodeRef


@dataclass(frozen=True)
class Connection:
    source: str
    target: str
    label: str
    kind: str = "wire"


@dataclass
class Case:
    name: str
    blocks: list[Block]
    ports: list[Port]
    connections: list[Connection]

    def to_dict(self):
        return asdict(self)


def code(function, member="function"):
    return CodeRef(f"rs:src/lib.rs::{function}", member)


def fixture_cases():
    def block(name, function):
        parent = name.rpartition(".")[0] or None
        return Block(name, parent, code(function))

    def ports(name, function, extra=False):
        first, second = (
            ("seed", "enabled")
            if function in {"produce", "run"}
            else ("sample", "valid")
        )
        specs = [
            ("in_sample", "in", f"parameter:{first}"),
            ("in_valid", "in", f"parameter:{second}"),
            ("out_sample", "out", "return:0"),
            ("out_valid", "out", "return:1"),
        ]
        if extra:
            specs += [
                ("in_extra", "in", f"parameter:{first}"),
                ("out_extra", "out", "return:0"),
            ]
        return [
            Port(f"{name}.{suffix}", name, direction, code(function, member))
            for suffix, direction, member in specs
        ]

    flat = Case(
        "flat",
        [block("source", "produce"), block("sink", "consume")],
        ports("source", "produce") + ports("sink", "consume"),
        [
            Connection("source.out_sample", "sink.in_sample", "data"),
            Connection("source.out_valid", "sink.in_valid", "status"),
        ],
    )
    nested = Case(
        "nested",
        [
            block("pipeline", "run"),
            block("pipeline.first", "transform"),
            block("pipeline.second", "transform"),
        ],
        ports("pipeline", "run")
        + ports("pipeline.first", "transform")
        + ports("pipeline.second", "transform"),
        [
            Connection(
                "pipeline.in_sample",
                "pipeline.first.in_sample",
                "input data",
                "exposure",
            ),
            Connection(
                "pipeline.in_valid",
                "pipeline.first.in_valid",
                "input status",
                "exposure",
            ),
            Connection(
                "pipeline.first.out_sample", "pipeline.second.in_sample", "data"
            ),
            Connection(
                "pipeline.first.out_valid", "pipeline.second.in_valid", "status"
            ),
            Connection(
                "pipeline.second.out_sample",
                "pipeline.out_sample",
                "output data",
                "exposure",
            ),
            Connection(
                "pipeline.second.out_valid",
                "pipeline.out_valid",
                "output status",
                "exposure",
            ),
        ],
    )
    stress = Case(
        "stress",
        [
            block("source", "produce"),
            block("sink", "consume"),
            block("observer", "consume"),
        ],
        ports("source", "produce", extra=True)
        + ports("sink", "consume")
        + ports("observer", "consume"),
        [
            Connection("source.out_sample", "sink.in_sample", "sample data"),
            Connection("source.out_valid", "sink.in_valid", "validity flag"),
            Connection("source.out_sample", "observer.in_sample", "sample data copy"),
        ],
    )
    return [flat, nested, stress]
