"""Native Xyce structure and independent optional oracle acceptance."""
import json
import shutil
from pathlib import Path

import pytest

from conftest import require_vendor_tool
from hx.api import extract
from hx.netlist.profiles import XYCE, XYCE_INVENTORY
from hx.netlist.xyce import check_external

FIX = Path(__file__).parent / 'fixtures/xyce'


def project(tmp_path):
    root = tmp_path / 'xyce'
    shutil.copytree(FIX, root, ignore=shutil.ignore_patterns('.hx'))
    return root


def test_xyce_native_hierarchy_and_blocks(tmp_path):
    root = project(tmp_path)
    g = extract('analog.cir:.', root=str(root), depth=None, dialect='xyce').to_dict()
    assert not g['circuit']['diagnostics']
    assert g['circuit']['terminals']['sp:analog.cir::xdut.r1'][0]['canonical'] == 'vdd'
    assert set(g['circuit']['models']) == {'/dm'}
    assert any(d['name'] == '.func' for d in g['circuit']['directives'])
    assert not any(n['name'] in ('1', '2') for n in g['nodes'].values())


def test_xyce_named_and_digital_identities(tmp_path):
    root = project(tmp_path)
    g = extract('mixed.cir:.', root=str(root), depth=None, dialect='xyce').to_dict()
    assert len(g['circuit']['terminals']['sp:mixed.cir::yadc!output_probe']) == 2
    assert g['nodes']['sp:mixed.cir::ydac!input_driver']['attrs']['family'] == 'YDAC'
    g = extract('digital.cir:.', root=str(root), depth=None, dialect='xyce').to_dict()
    assert [r['as_written'] for r in g['circuit']['terminals']['sp:digital.cir::ugate']] == ['vdd', '0', 'a', 'b', 'out1']
    assert [r['as_written'] for r in g['circuit']['terminals']['sp:digital.cir::yand!legacy_gate']] == ['0', 'vdd', '0', 'a', 'b', 'out2']
    assert not g['circuit']['diagnostics']


def test_xyce_coupling_and_inventory(tmp_path):
    root = project(tmp_path)
    g = extract('coupling.cir:.', root=str(root), depth=None, dialect='xyce').to_dict()
    assert len(g['nodes']['sp:coupling.cir::k1']['attrs']['controls']) == 3
    assert len(g['circuit']['terminals']['sp:coupling.cir::yacc!motion']) == 3
    assert len(XYCE_INVENTORY['families']) == 64
    assert sum(len(v) for v in XYCE_INVENTORY['families'].values()) == 117
    assert {'U', 'YADC', 'YDAC', 'YACC', 'YGENEXT', 'YPDE', 'YMEMRISTOR'} <= XYCE.families.keys()


@pytest.mark.vendor_tool('xyce')
@pytest.mark.parametrize('name', ['analog.cir', 'mixed.cir', 'digital.cir', 'coupling.cir', 'modern.cir'])
def test_live_xyce(tmp_path, name):
    exe = require_vendor_tool('xyce')
    root = project(tmp_path)
    before = {p: p.read_bytes() for p in root.iterdir() if p.is_file()}
    report = check_external(name + ':.', root=str(root), exe=exe)
    assert report['status'] == 'agree', report
    assert report['checked'] == ['original-deck syntax', 'device-family counts', 'topology acceptance', 'exposed net names']
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.vendor_tool('xdm')
def test_xdm_never_promotes_lossy_success_to_agreement(tmp_path):
    exe = require_vendor_tool('xdm')
    root = project(tmp_path)
    report = check_external('mixed.cir:.', root=str(root), oracle='xdm', exe=exe)
    assert report['status'] == 'unavailable' and 'XDM coverage unavailable' in report['reason']


def test_unknown_and_malformed_xyce_are_preserved(tmp_path):
    root = project(tmp_path)
    (root / 'bad.cir').write_text('Bad structure\nYFUTURE d1 a b foo=1\nM1 a b mm\n.model mm NMOS LEVEL=1\n.end\n')
    g = extract('bad.cir:.', root=str(root), dialect='xyce', depth=None).to_dict()
    assert g['nodes']['sp:bad.cir::yfuture!d1']['attrs']['tokens']
    assert {'unknown-device-family', 'terminal-count-mismatch'} <= {d['code'] for d in g['circuit']['diagnostics']}
    (root / 'data.cir').write_text('Incomplete data\n.data table time value\n+ 0 1\n')
    g = extract('data.cir:.', root=str(root), dialect='xyce', depth=None).to_dict()
    assert any('.data never closed' in d['message'] for d in g['circuit']['diagnostics'])


def test_acceptance_runner_failure_propagates(tmp_path):
    import subprocess
    import sys
    out = tmp_path / 'failure'
    run = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'dev/scripts/hardening_coverage.py'),
                          '--suite', 'xyce', '--out', str(out), '--fail-stage', 'xyce-toolchain'],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 1
    result = json.loads((out / 'coverage.json').read_text())
    assert result['stages'][0]['exit'] == 1 and 'injected stage failure' in result['stages'][0]['error']
