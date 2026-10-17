import json
from pathlib import Path
import shutil

import pytest

from hx.api import extract
from hx.cli import main
from hx.netlist.query import get_net, uses, QueryError

SHARED = Path(__file__).parent / 'fixtures/viewer/circuit-query.json'


def test_shared_guarded_connections():
    g = json.loads(SHARED.read_text())
    q = get_net(g, 'out')
    assert sorted(r['node'] for r in q['results']) == g['expected']['all']
    assert q['aliases'] == g['expected']['aliases']
    q = get_net(g, 'x.p', node='r2')
    assert sorted(r['node'] for r in q['results']) == g['expected']['guarded']
    assert get_net(g, 'out', limit=1)['truncated']
    with pytest.raises(QueryError, match='limit'):
        get_net(g, 'out', limit=0)
    assert uses(g, 'amp', kind='definition')['results'][0]['node'] == 'x'
    assert not uses(g, '/dm', kind='model')['results'][0]['expanded']
    with pytest.raises(QueryError, match='no circuit'):
        get_net({}, 'out')
    for n in g['nodes'].values():
        n.get('attrs', {}).pop('guard_constraints', None)
    assert 'legacy graph lacks' in get_net(g, 'out')['boundaries']['guard_context']


def test_saved_graph_cli_queries(tmp_path, capsys):
    root = tmp_path / 'xyce'
    shutil.copytree(Path(__file__).parent / 'fixtures/xyce', root)
    g = extract('analog.cir:.', root=str(root), dialect='xyce', depth=None)
    path = root / 'graph.json'; g.save(str(path))
    assert main(['netlist', 'net', 'out', '--graph', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['total'] >= 5
    assert main(['netlist', 'uses', '/dm', '--kind', 'model', '--graph', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['results'][0]['node'].endswith('xdut.d1')


def test_mcp_queries_are_read_only(tmp_path):
    import asyncio
    from mcp.client import Client
    from hx.mcp_server import build_server
    root = tmp_path / 'xyce'
    shutil.copytree(Path(__file__).parent / 'fixtures/xyce', root, ignore=shutil.ignore_patterns('.hx'))
    g = extract('analog.cir:.', root=str(root), dialect='xyce', depth=None)
    path = root / '.hx/graph.json'; g.save(str(path))
    server = build_server(str(root))
    before = {p: p.read_bytes() for p in (root / '.hx').rglob('*') if p.is_file()}
    async def go():
        async with Client(server) as client:
            net = await client.call_tool('get_net', {'net': 'out'})
            uses = await client.call_tool('netlist_uses', {'target': '/dm', 'kind': 'model'})
            return '\n'.join(x.text for result in (net, uses) for x in result.content if x.type == 'text')
    result = asyncio.run(go())
    assert 'canonical: out' in result and 'xdut.d1' in result and 'selected graph only' in result
    assert all(p.read_bytes() == data for p, data in before.items())
