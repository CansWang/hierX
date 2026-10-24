"""Independent geometry-oracle tests; these do not impersonate the D2 compiler."""

import base64
from dataclasses import replace
import html
import json

import pytest
from playwright.sync_api import sync_playwright

from dev.d2_ports_experiment.geometry import analyze, connection_endpoints
from dev.d2_ports_experiment.model import fixture_cases
from dev.d2_ports_experiment.run import (
    HERE,
    check_navigation,
    code_urls,
    inspect_svg,
    main,
    prepare_inputs,
    servers,
)


def synthetic_svg(case, urls):
    """Known-good boundary geometry, intentionally authored independently of D2."""
    shapes = []

    def group(identity, role, body, label, position):
        identity_class = base64.urlsafe_b64encode(
            html.escape(identity).encode()
        ).decode()
        link = html.escape(urls.get(identity, ""), quote=True)
        x, y, anchor = position
        return f'<g class="{identity_class} hx-{role}"><a href="{link}">{body}<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="14">{label}</text></a></g>'

    for block, x in zip(case.blocks, (40, 300)):
        shapes.append(
            group(
                block.id,
                "block",
                f'<rect x="{x}" y="20" width="140" height="160" fill="white" stroke="black"/>',
                block.id,
                (x + 70, 45, "middle"),
            )
        )
        for port in (p for p in case.ports if p.block == block.id):
            cx = x if port.direction == "in" else x + 140
            cy = 80 if port.id.endswith("sample") else 130
            label = port.id.split(".")[-1].replace("in_", "").replace("out_", "")
            role = "input" if port.direction == "in" else "output"
            labelx = cx + 12 if port.direction == "in" else cx - 12
            anchor = "start" if port.direction == "in" else "end"
            shapes.append(
                group(
                    port.id,
                    role,
                    f'<circle cx="{cx}" cy="{cy}" r="5" fill="blue"/>',
                    label,
                    (labelx, cy + 4, anchor),
                )
            )
    for edge, cy in zip(case.connections, (80, 130)):
        identity = f"({edge.source} -> {edge.target})[0]"
        shapes.append(
            group(
                identity,
                edge.kind,
                f'<path class="connection" d="M 185 {cy} L 295 {cy}" fill="none" stroke="black"/>',
                edge.label,
                (240, cy - 8, "middle"),
            )
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" class="d2-svg" width="480" height="200" viewBox="0 0 480 200">'
        + "".join(shapes)
        + "</svg>"
    )


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def oracle(tmp_path, browser):
    case = fixture_cases()[0]
    urls = {
        item.id: "http://127.0.0.1:1/#" + item.id
        for item in [*case.blocks, *case.ports]
    }
    path = tmp_path / "oracle.svg"
    path.write_text(synthetic_svg(case, urls))
    context = browser.new_context()
    page = context.new_page()
    measured = inspect_svg(page, path.as_uri(), 1)
    assert analyze(case, measured, urls)["passed"]
    yield case, urls, page
    context.close()


@pytest.mark.parametrize("zoom", [1, 1.5])
def test_known_good_geometry_in_svg_document_at_both_zooms(oracle, zoom):
    case, urls, page = oracle
    page.evaluate("(z)=>document.documentElement.style.zoom=String(z)", zoom)
    measured = page.evaluate((HERE / "measure.js").read_text())
    result = analyze(case, measured, urls)
    assert result["passed"], result["errors"]
    assert all(p["border_distance"] < 0.01 for p in result["metrics"]["pins"].values())


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (
            "document.querySelector('[data-hx-id=\"source.in_sample\"] circle').setAttribute('cx','60')",
            "pin-not-on-boundary",
        ),
        (
            "document.querySelector('g.hx-wire path').setAttribute('d','M 185 80 L 435 80')",
            "wrong-endpoint",
        ),
        (
            "document.querySelector('[data-hx-id=\"source.in_sample\"] text').setAttribute('x','35')",
            "label-over-pin",
        ),
        (
            "document.querySelector('[data-hx-id=\"source.in_sample\"] a').setAttribute('href','http://127.0.0.1:1/wrong')",
            "missing-code-link",
        ),
        (
            "document.querySelector('[data-hx-id=\"source.in_sample\"] circle').remove()",
            "missing-pin",
        ),
    ],
)
def test_mutated_geometry_or_links_cannot_false_pass(oracle, mutation, expected):
    case, urls, page = oracle
    page.evaluate(mutation)
    result = analyze(case, page.evaluate((HERE / "measure.js").read_text()), urls)
    assert not result["passed"] and expected in {e["code"] for e in result["errors"]}


def test_missing_exposure_and_unmeasurable_marker_cannot_pass(oracle):
    case, urls, page = oracle
    case.connections[0] = replace(case.connections[0], kind="exposure")
    page.evaluate(
        "document.querySelector('g.hx-wire').classList.replace('hx-wire','hx-exposure')"
    )
    measured = page.evaluate((HERE / "measure.js").read_text())
    assert analyze(case, measured, urls)["passed"]
    page.evaluate("document.querySelector('g.hx-exposure').remove()")
    result = analyze(case, page.evaluate((HERE / "measure.js").read_text()), urls)
    assert "missing-exposure" in {e["code"] for e in result["errors"]}
    page.evaluate(
        "document.querySelector('g.hx-wire path').setAttribute('marker-end','url(#absent)')"
    )
    result = analyze(case, page.evaluate((HERE / "measure.js").read_text()), urls)
    assert not result["passed"] and "measurement-unavailable" in {
        e["code"] for e in result["errors"]
    }


def test_nested_ids_are_distinct_while_reusing_code():
    nested = fixture_cases()[1]
    assert nested.blocks[1].id != nested.blocks[2].id
    assert nested.blocks[1].code == nested.blocks[2].code
    assert connection_endpoints(
        "pipeline.(first.out_sample -> second.in_sample)[0]"
    ) == ("pipeline.first.out_sample", "pipeline.second.in_sample")
    assert connection_endpoints("(source.out_sample -&gt; sink.in_sample)[0]") == (
        "source.out_sample",
        "sink.in_sample",
    )
    with pytest.raises(ValueError):
        connection_endpoints(None)


def test_unresolved_code_links_are_explicit_and_never_fall_back():
    case = fixture_cases()[0]
    graph = {"nodes": {case.blocks[0].code.symbol: {"params": [{"name": "seed"}]}}}
    urls, errors = code_urls(case, graph, "http://127.0.0.1:1")
    assert "source" in urls and "source.in_sample" in urls
    assert "sink" not in urls and "source.in_valid" not in urls
    assert {"unresolved-code-link", "unresolved-code-member"} == {
        e["code"] for e in errors
    }


def test_real_clicks_reach_source_and_a_cancelled_link_cannot_pass(tmp_path, browser):
    """Validate click instrumentation independently of native D2 link icons."""
    from hx.model import Edge, Graph, Loc, Node, Param, TypeUse

    case = fixture_cases()[0]
    source = tmp_path / "src"
    source.mkdir()
    text = (HERE / "fixtures/rust/src/lib.rs").read_text()
    (source / "lib.rs").write_text(text)
    graph = Graph(root=str(tmp_path), lang="rs", entry=case.blocks[0].code.symbol)
    for block in case.blocks:
        function = block.code.symbol.split("::")[-1]
        names = ("seed", "enabled") if function == "produce" else ("sample", "valid")
        signature = (
            f"pub fn {function}({names[0]}: u32, {names[1]}: bool) -> (u32, bool)"
        )
        line = next(
            i for i, t in enumerate(text.splitlines(), 1) if f"fn {function}(" in t
        )
        graph.nodes[block.code.symbol] = Node(
            block.code.symbol,
            "function",
            function,
            function,
            "rs",
            Loc("src/lib.rs", line, line + 2),
            signature,
            params=[Param(names[0], "u32"), Param(names[1], "bool")],
            returns=TypeUse("(u32, bool)"),
        )
    graph.nodes[case.blocks[0].code.symbol].calls = [case.blocks[1].code.symbol]
    graph.edges = [Edge(case.blocks[0].code.symbol, case.blocks[1].code.symbol, "call")]
    graph_path = tmp_path / "graph.json"
    graph.save(str(graph_path))
    with servers(tmp_path, graph_path, tmp_path) as (static, viewer):
        urls, errors = code_urls(case, graph.to_dict(), viewer)
        assert not errors
        svg = tmp_path / "oracle.svg"
        svg.write_text(synthetic_svg(case, urls))
        context = browser.new_context()
        try:
            page = context.new_page()
            inspect_svg(page, static + "/oracle.svg", 1)
            clicks = check_navigation(context, page, case, urls)
            assert all(c["passed"] for c in clicks), [
                c for c in clicks if not c["passed"]
            ]
            single = replace(case, blocks=[], ports=[case.ports[0]], connections=[])
            page.evaluate(
                """document.querySelector('[data-hx-id="source.in_sample"] a')
                .addEventListener('click',e=>e.preventDefault())"""
            )
            clicks = check_navigation(context, page, single, urls)
            assert not clicks[0]["passed"] and "Timeout" in clicks[0]["error"]
        finally:
            context.close()


def test_fixture_link_substitution_does_not_edit_authored_inputs(tmp_path):
    before = {p.name: p.read_bytes() for p in (HERE / "fixtures").glob("*.d2")}
    urls = {
        item.id: "http://127.0.0.1:1/#" + item.id
        for case in fixture_cases()
        for item in [*case.blocks, *case.ports]
    }
    inputs = prepare_inputs(tmp_path, urls)
    assert all("__HX_CODE_" not in p.read_text() for p in inputs.glob("*.d2"))
    assert {p.name: p.read_bytes() for p in (HERE / "fixtures").glob("*.d2")} == before


def test_setup_failure_and_existing_output_are_not_layout_results(tmp_path):
    output = tmp_path / "new"
    assert main(["--d2", str(tmp_path / "missing"), "--output", str(output)]) == 2
    assert (
        json.loads((output / "setup-error.json").read_text())["error"]
        == "FileNotFoundError"
    )
    before = {p: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(SystemExit) as exc:
        main(["--d2", "missing", "--output", str(output)])
    assert exc.value.code == 2
    assert all(p.read_bytes() == data for p, data in before.items())
