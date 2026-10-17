"""Rust source boundaries and real rust-analyzer trait identities."""
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from hx import ids, graphio, project
from hx.api import split_entry, extract
from hx.frontends.base import EntryNotFound
from hx.frontends.lsp_fe import LspFrontend
from hx.rustsyntax import impl_name
from conftest import require_tool


def test_rust_argument_boundaries():
    text = '(a < b, move |x: (u8, u8), y| x.0 + y, f::<A, B>(), r##"x, )"##, a >> 2)'
    assert ids.paren_args(text, 'rs') == ['a < b', 'move |x: (u8, u8), y| x.0 + y', 'f::<A, B>()', 'r##"x, )"##', 'a >> 2']
    assert ids.body_hash('fn f() { /* a /* b */ c */ ok(); }', 'rs') == ids.body_hash('fn f() { /* changed /* x */ y */ ok(); }', 'rs')
    assert impl_name('impl<T> Convert<Vec<T>> for Item<T> where T: Send') == '<Item<T> as Convert<Vec<T>>>'
    assert impl_name('impl <T> Convert < Vec < T > > for Item < T >') == '<Item<T> as Convert<Vec<T>>>'
    assert split_entry('src/lib.rs:<Item as Convert<String>>::convert') == ('src/lib.rs', '<Item as Convert<String>>::convert')
    assert split_entry(r'C:\src\lib.rs:Item::new') == (r'C:\src\lib.rs', 'Item::new')
    assert ids.paren_args('f(|| -> Result<A, B> { Ok(a) }, c)', 'rs') == ['|| -> Result<A, B> {Ok(a)}', 'c']


def test_lsp_unicode_and_long_calls():
    fe = LspFrontend('/tmp', server='rust')
    fe.client = SimpleNamespace(position_encoding='utf-16')
    uri = 'file:///tmp/x.rs'
    line = 'let _ = "😀"; call(' + '\n' * 40 + '|a, b| a + b, 1);'
    fe.src_cache[uri] = line.splitlines()
    col = fe._column(fe.src_cache[uri][0], len('let _ = "😀"; call'), to_wire=True)
    assert fe._call_args(uri, {'end': {'line': 0, 'character': col}}) == ['|a, b| a + b', '1']
    assert fe._text(uri, {'start': {'line': 0, 'character': 9}, 'end': {'line': 0, 'character': 11}}) == '😀'
    fe.client = None


def test_real_rust_trait_entries(tmp_path):
    ra = require_tool('rust-analyzer', '~/.cargo/bin/rust-analyzer')
    root = tmp_path / 'rust'
    shutil.copytree(Path(__file__).parent / 'fixtures/rust_hardening', root)
    kw = dict(root=str(root), lang='rust', lsp_cmd=[ra], lsp_timeout=120, depth=1)
    a = extract('src/lib.rs:<Item as Convert<&str>>::convert', **kw)
    b = extract('src/lib.rs:<Item as Convert<String>>::convert', **kw)
    assert a.entry != b.entry and '#' not in a.entry + b.entry
    assert '<Item as Convert<&str>>::convert' in a.entry
    source = root / 'src/lib.rs'
    source.write_text('/* line drift /* nested comment */ */\n\n' + source.read_text())
    moved = extract('src/lib.rs:<Item as Convert<&str>>::convert', **kw)
    from hx.diff import diff_graphs
    assert not diff_graphs(a.to_dict(), moved.to_dict())['summary']['any']
    with pytest.raises(EntryNotFound, match='ambiguous'):
        extract('src/lib.rs:convert', **kw)
    g = extract('src/lib.rs:entry', **kw)
    assert any(e.args == ['3', 'move |a, b| {a + b}'] for e in g.edges)
    assert g.meta['index']['requests_by_method']['textDocument/hover'] > 0
    macro = extract('src/lib.rs:macro_entry', **kw)
    assert any('macro/generated' in u.reason for u in macro.unresolved)


def test_hx4_rust_migration_report():
    doc = {'schema': 'hx/3', 'lang': 'rs', 'nodes': {'rs:a.rs::Item::convert': {}}, 'meta': {}}
    up, rep = graphio.upgrade(doc)
    assert up['schema'] == 'hx/4' and rep.pending and rep.from_schema == 'hx/3'


def test_macro_call_hierarchy_items_do_not_alias_names_or_fabricate_ids():
    fe = LspFrontend('/tmp', server='rust')
    fe._symbol_at = lambda *_args: None
    rng = {'start': {'line': 4, 'character': 0}, 'end': {'line': 4, 'character': 10}}
    item = {'uri': 'file:///tmp/a.rs', 'kind': 6, 'name': 'next', 'range': rng, 'selectionRange': rng}
    assert fe._key(item) == fe._key({**item, 'kind': 12})
    a = fe._register(item)
    b = fe._register({**item, 'name': 'nth'})
    assert a != b and fe.stable_id(a) is None and fe.stable_id(b) is None
    assert 'macro/generated' in fe.declaration(a).reason


def test_rust_attribute_callers_use_the_declarations_selection_and_body():
    fe = LspFrontend('/tmp', server='rust')
    uri = 'file:///tmp/a.rs'
    fe.src_cache[uri] = ['#[tokio::test]', 'async fn target() { work(); }']
    rng = {'start': {'line': 0, 'character': 0}, 'end': {'line': 1, 'character': 29}}
    sel = {'start': {'line': 1, 'character': 9}, 'end': {'line': 1, 'character': 15}}
    sym = {'name': 'target', 'kind': 12, 'range': rng, 'selectionRange': sel, 'path': []}
    fe.symbols_cache[uri] = [sym]
    fe._open = lambda _path: uri
    fe._req = lambda *_args, **_kw: {'contents': {'value': '```rust\n#[tokio::main] async fn main() { example(); }\n```'}}
    item = {'uri': uri, 'kind': 12, 'name': 'target', 'range': rng,
            'selectionRange': {'start': {'line': 0, 'character': 2}, 'end': {'line': 0, 'character': 13}}}
    key = fe._register(item)
    assert key == fe._register({**item, 'selectionRange': sel})
    canonical = fe.items[key]
    assert canonical['selectionRange'] == sel and fe._full_range(canonical) == rng
    assert fe._hover_sig(canonical)[0] == 'fn target()'


def test_rust_annotation_migration_with_line_drift(tmp_path):
    from hx import annotations
    old_id, new_id = 'rs:a.rs::Item::convert', 'rs:a.rs::<Item as Convert<String>>::convert'
    base = dict(kind='method', lang='rs', name='convert', signature='fn convert(&self, value: String) -> usize', body_hash='sha1:a')
    old = {'nodes': {old_id: dict(base, loc={'file': 'a.rs', 'line': 3, 'end_line': 5})}}
    new = {'nodes': {new_id: dict(base, loc={'file': 'a.rs', 'line': 8, 'end_line': 10})}}
    mapped, ambiguous, unmatched = project.map_node_ids(old, new, '/r')
    assert mapped == {old_id: new_id} and not ambiguous and not unmatched
    path = tmp_path / 'annotations.json'
    annotations.save(str(path), {'schema': 'hx-ann/1', 'nodes': {old_id: {'note': 'keep', 'verified_body_hash': 'sha1:a'}}})
    original = path.read_bytes()
    annotations.migrate_file(str(path), mapped, from_schema='hx/3', backup_suffix='.bak-hx3')
    assert annotations.load(str(path))['nodes'][new_id]['note'] == 'keep'
    assert Path(str(path) + '.bak-hx3').read_bytes() == original
    new['nodes'][new_id]['body_hash'] = 'sha1:b'
    assert project._invalidated_ids(old, new, mapped) == [new_id]
