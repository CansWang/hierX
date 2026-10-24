"""D2 interpretation, navigation boundaries and upstream bridge failures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from hx.architecture import ArchitectureError, load_architecture
from hx.architecture.bridge import compile_d2
from hx.architecture.presentation import payload
from hx.tools import find_tool
from conftest import require_tool

FIXTURES = Path(__file__).parent / "fixtures/architecture"


@pytest.fixture
def d2_bridge():
    return require_tool(find_tool("d2_bridge") or "hx-d2-bridge")


def design(tmp_path, text):
    path = tmp_path / "design.d2"
    path.write_text(text)
    return str(path)


def test_upstream_imports_reused_instances_and_source_hashes(d2_bridge):
    doc = load_architecture(str(FIXTURES / "nested.d2"), bridge=d2_bridge)
    assert doc.valid and len(doc.blocks) == 3 and len(doc.ports) == 12
    assert len(doc.connections) == 6
    assert {e["kind"] for e in doc.connections} == {"wire", "exposure"}
    assert doc.bindings["pipeline.first"] == doc.bindings["pipeline.second"]
    assert {b["id"] for b in doc.blocks} == {"pipeline", "pipeline.first", "pipeline.second"}
    for entry in doc.inputs:
        assert entry["sha256"] == hashlib.sha256((FIXTURES / entry["file"]).read_bytes()).hexdigest()
    assert {p["sources"][0]["file"] for p in doc.ports} == {"nested.d2", "worker.d2"}
    ref=doc.ports[0]['sources'][0]
    assert (ref['end_line'],ref['end_column']) > (ref['line'],ref['column'])


def test_minimal_profile_needs_no_class_definitions_and_keeps_quoted_keys(tmp_path, d2_bridge):
    path = design(tmp_path, '"producer.one": {"out.value": u32 {class: hx-output}}\nsink: {sample: u32 {class: hx-input}}\n"producer.one"."out.value" -> sink.sample: transfer\n')
    doc = load_architecture(path, bridge=d2_bridge)
    assert doc.valid
    assert doc.ports[0]["path"] == ["producer.one", "out.value"]
    assert doc.connections[0]["source"] == doc.ports[0]["id"]
    assert not doc.diagnostics


@pytest.mark.parametrize("text,code", [
    ('', 'empty-architecture'),
    ('a -> b', 'invalid-endpoints'),
    ('a: {p: {class: hx-input}}\nb: {p: {class: hx-input}}\na.p -> b.p', 'invalid-endpoints'),
    ('a: {p: {class: hx-input}; b: {p: {class: hx-input}};p -> b.p}', 'invalid-endpoints'),
    ('a: {p: {class: hx-input}}\nb: {p: {class: hx-output}}\na.p <-> b.p', 'unsupported-arrow'),
    ('p: {class: hx-input}', 'invalid-port-owner'),
    ('a: {class: hx-bundle}', 'unsupported-hx-role'),
    ('a: {p: {class: [hx-input;hx-output]}}', 'unsupported-hx-role'),
    ('a: {link: "https://example.com"}', 'unsupported-code-link'),
    ('layers: {one: {a}}', 'unsupported-d2-boards'),
    ('a: {', 'd2-compile'),
    ('a: @missing', 'd2-compile'),
])
def test_profile_diagnostics(tmp_path, d2_bridge, text, code):
    doc = load_architecture(design(tmp_path, text), bridge=d2_bridge)
    assert not doc.valid
    assert code in {d["code"] for d in doc.diagnostics}


def test_unconnected_ports_and_descriptive_types_are_allowed(tmp_path, d2_bridge):
    doc = load_architecture(design(tmp_path, 'a: {p: "any type" {class: hx-input}}'), bridge=d2_bridge)
    assert doc.valid and not doc.connections


def test_presentation_attributes_are_reported(tmp_path, d2_bridge):
    doc = load_architecture(design(tmp_path, 'a: {shape: circle;style.fill: red;width: 100}'), bridge=d2_bridge)
    assert doc.valid and {d["code"] for d in doc.diagnostics} == {"d2-presentation-ignored"}


def test_import_cycles_and_symlink_escape_are_rejected(tmp_path, d2_bridge):
    path = design(tmp_path, '...@cycle')
    (tmp_path / "cycle.d2").write_text('...@design')
    assert not load_architecture(path, bridge=d2_bridge).valid
    external = tmp_path.parent / (tmp_path.name + '-outside.d2')
    external.write_text('secret')
    try:
        (tmp_path / "escape.d2").symlink_to(external)
        Path(path).write_text('...@escape')
        doc = load_architecture(path, bridge=d2_bridge)
        assert not doc.valid and 'escapes project root' in str(doc.diagnostics)
        assert 'secret' not in str(doc.blocks)
    finally:
        external.unlink()


def test_parent_import_allowed_with_explicit_root(tmp_path, d2_bridge):
    child = tmp_path / 'sub'; child.mkdir()
    (tmp_path/'shared.d2').write_text('worker')
    path = design(child, '...@../shared')
    assert not load_architecture(path, bridge=d2_bridge).valid
    doc = load_architecture(path, root=str(tmp_path), bridge=d2_bridge)
    assert doc.valid and doc.blocks[0]['id'] == 'worker'


def test_exact_code_binding_and_viewer_urls_are_separate(tmp_path, d2_bridge):
    from hx.model import Graph, Loc, Node
    graph = Graph(root=str(tmp_path), lang='rs', entry='rs:lib.rs::a')
    graph.nodes[graph.entry] = Node(graph.entry, 'function', 'a', 'a', 'rs', Loc('lib.rs', 1), 'fn a()')
    gp = tmp_path/'graph.json'; graph.save(str(gp))
    path = design(tmp_path, 'a: {link: "hx:rs:lib.rs::a"}\nb: {link: "hx:rs:lib.rs::missing"}')
    before = gp.read_bytes()
    doc = load_architecture(path, graph=str(gp), bridge=d2_bridge)
    assert doc.valid and doc.bindings['a']['status']=='resolved' and doc.bindings['b']['status']=='unresolved'
    assert payload(doc)['code_urls'] == {}
    urls = payload(doc, 'http://localhost:8765/')['code_urls']
    assert list(urls)==['a'] and 'sel=rs%3Alib.rs%3A%3Aa' in urls['a']
    assert gp.read_bytes()==before and not (tmp_path/'annotations.json').exists()
    with pytest.raises(ArchitectureError, match='absolute http'):
        payload(doc, 'javascript:alert(1)')
    graph.schema = 'future/99'
    raw = json.loads(before); raw['schema'] = 'hx/99'; gp.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='unsupported graph schema'):
        load_architecture(path, graph=str(gp), bridge=d2_bridge)


@pytest.mark.parametrize('body,match', [
    ('print("garbage")', 'invalid output'),
    ('print("{}")', 'incompatible protocol'),
    ('import time;time.sleep(1)', 'D2 bridge'),
    ('import sys;sys.stderr.write("compiler unavailable");sys.exit(9)', 'exit 9'),
])
def test_fake_bridge_failures_are_named(tmp_path, body, match):
    fake=tmp_path/'fake';fake.write_text('#!'+sys.executable+'\n'+body+'\n');fake.chmod(0o755)
    with pytest.raises(ArchitectureError, match=match):
        compile_d2(design(tmp_path,'a'), bridge=str(fake), timeout=.05 if 'sleep' in body else 5)


def test_explicit_missing_or_unexecutable_helper_has_no_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv('HX_TOOL_D2_BRIDGE', '/valid-but-irrelevant')
    path = design(tmp_path,'a')
    with pytest.raises(ArchitectureError, match='not found'):
        compile_d2(path, bridge=str(tmp_path/'missing'))
    fake=tmp_path/'not-executable';fake.write_text('hello')
    with pytest.raises(ArchitectureError, match='D2 bridge'):
        compile_d2(path, bridge=str(fake))


def test_schema_and_cli_round_trip_outside_checkout(tmp_path, d2_bridge):
    import jsonschema
    from hx.cli import main
    doc = load_architecture(str(FIXTURES/'nested.d2'), bridge=d2_bridge)
    schema=json.loads((Path(__file__).parents[1]/'hx/schema/hx-arch-1.schema.json').read_text())
    jsonschema.validate(doc.to_dict(),schema)
    assert main(['arch','inspect',str(FIXTURES/'flat.d2'),'--d2-bridge',d2_bridge])==0
    output=tmp_path/'diagram.html'
    assert main(['arch','export',str(FIXTURES/'flat.d2'),'--d2-bridge',d2_bridge,'-o',str(output)])==0
    text=output.read_text()
    assert 'hx-arch/1' in text and 'hx-elk-license' in text and '/static/' not in text
    assert main(['arch','inspect',design(tmp_path,'a -> b'),'--d2-bridge',d2_bridge])==1
    assert main(['arch','inspect',str(tmp_path/'missing'),'--d2-bridge',d2_bridge])==2


def test_export_cannot_overwrite_inputs_or_hardlinks(tmp_path, d2_bridge):
    from hx.cli import main
    path=design(tmp_path,'a')
    alias=tmp_path/'alias.html';os.link(path,alias)
    for output in [path,str(alias)]:
        assert main(['arch','export',path,'--d2-bridge',d2_bridge,'-o',output])==2
        assert Path(path).read_text()=='a'


def test_architecture_http_refresh_and_failure_clear_current_model(tmp_path, d2_bridge):
    from fastapi.testclient import TestClient
    from hx.architecture.serve import create_architecture_app
    path=design(tmp_path,'a')
    with TestClient(create_architecture_app(path,bridge=d2_bridge)) as client:
        assert client.get('/architecture').status_code==200
        assert client.get('/api/architecture').json()['blocks'][0]['id']=='a'
        Path(path).write_text('b')
        assert client.get('/api/architecture').json()['blocks'][0]['id']=='b'
        Path(path).write_text('a: {')
        assert not client.get('/api/architecture').json()['valid']
        Path(path).unlink()
        assert client.get('/api/architecture').status_code==400


def test_protocol_validation_survives_optimized_python(tmp_path):
    from hx.architecture.bridge import D2_COMMIT, D2_VERSION
    data={'protocol':'future/99','d2_version':D2_VERSION,'d2_commit':D2_COMMIT,'ok':True,
          'objects':[],'edges':[],'inputs':[],'diagnostics':[],'boards':False,'presentation':False}
    fake=tmp_path/'fake';fake.write_text('#!'+sys.executable+'\nprint('+repr(json.dumps(data))+')\n');fake.chmod(0o755)
    proc=subprocess.run([sys.executable,'-O','-m','hx.cli','arch','inspect',design(tmp_path,'a'),'--d2-bridge',str(fake)],text=True,capture_output=True)
    assert proc.returncode==2 and 'incompatible protocol' in proc.stderr and 'Traceback' not in proc.stderr
