"""Hermetic SDK installation and bridge setup failure/reuse checks."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

SCRIPT = Path(__file__).parents[1] / "dev/scripts/setup_d2_bridge.py"
spec = importlib.util.spec_from_file_location("hx_d2_setup", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def fake_go(path, version="1.27.3", failure=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    helper_version = {'protocol':'hx-d2-bridge/1','d2_version':'v0.9.0',
                      'd2_commit':'d5a51743b6d5c00f1ec6f8340003f5d5a6ba4eda'}
    code = f'''#!{sys.executable}
import json,os,pathlib,sys
if sys.argv[1]=='version':
 print('go version go{version} linux/amd64')
 sys.exit(0)
assert os.environ['GOTOOLCHAIN']=='local'
if {failure!r}:sys.exit(7)
path=pathlib.Path(sys.argv[sys.argv.index('-o')+1])
path.write_text('#!{sys.executable}\\nprint('+repr(json.dumps({helper_version!r}))+')\\n')
path.chmod(0o755)
'''
    path.write_text(code)
    path.chmod(0o755)
    return path


@pytest.mark.parametrize('release,expected',[
    ('1.26.10',(1,26,10)),('1.27.0',(1,27,0)),('1.28.1',(1,28,1)),('1.27rc1',None),
])
def test_version_detection_uses_local_compiler(tmp_path,release,expected):
    assert setup.version(fake_go(tmp_path/'go',release))==expected


def test_existing_compatible_go_needs_no_sdk(tmp_path,monkeypatch):
    go=fake_go(tmp_path/'bin/go','1.28.1')
    monkeypatch.setattr(setup.shutil,'which',lambda _:str(go))
    assert setup.resolve_go(tmp_path/'sdk')==go
    assert not (tmp_path/'sdk').exists()


def test_existing_local_sdk_is_reused_when_path_has_old_go(tmp_path,monkeypatch):
    old=fake_go(tmp_path/'bin/go','1.26.10')
    cached=fake_go(tmp_path/'sdk/bin/go')
    monkeypatch.setattr(setup.shutil,'which',lambda _:str(old))
    assert setup.resolve_go(tmp_path/'sdk',False)==cached


def test_no_bootstrap_and_invalid_existing_directory_are_named(tmp_path,monkeypatch):
    monkeypatch.setattr(setup.shutil,'which',lambda _:None)
    with pytest.raises(setup.SetupError,match='--no-bootstrap'):
        setup.resolve_go(tmp_path/'sdk',False)
    (tmp_path/'sdk').mkdir()
    with pytest.raises(setup.SetupError,match='exists but has no working'):
        setup.resolve_go(tmp_path/'sdk')


@pytest.mark.parametrize('system,machine,platform_name',[
    ('Linux','x86_64','linux-amd64'),('Linux','aarch64','linux-arm64'),
    ('Darwin','arm64','darwin-arm64'),('Darwin','x86_64','darwin-amd64'),
])
def test_pinned_platform_assets(monkeypatch,system,machine,platform_name):
    monkeypatch.setattr(setup.platform,'system',lambda:system)
    monkeypatch.setattr(setup.platform,'machine',lambda:machine)
    name,digest=setup.asset()
    assert name=='go1.27.3.'+platform_name+'.tar.gz' and len(digest)==64


def test_unsupported_platform_has_manual_install_hint(monkeypatch):
    monkeypatch.setattr(setup.platform,'system',lambda:'Linux')
    monkeypatch.setattr(setup.platform,'machine',lambda:'unsupported')
    with pytest.raises(setup.SetupError,match='install Go 1.27'):
        setup.asset()


def test_old_go_bootstraps_verified_sdk_and_retains_it(tmp_path,monkeypatch):
    old=fake_go(tmp_path/'old/go','1.26.10')
    fresh=fake_go(tmp_path/'source/go')
    archive=tmp_path/'sdk.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:tar.add(fresh,arcname='go/bin/go')
    raw=archive.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(setup.shutil,'which',lambda _:str(old))
    monkeypatch.setattr(setup,'asset',lambda:('go-test.tar.gz',digest))
    def download(url,target):target.write_bytes(raw);return digest
    monkeypatch.setattr(setup,'download',download)
    result=setup.resolve_go(tmp_path/'sdk')
    assert result==tmp_path/'sdk/bin/go' and setup.version(result)==(1,27,3)
    assert not list(tmp_path.glob('.hx-go-*'))
    # The next run reuses that SDK and cannot hit the downloader.
    monkeypatch.setattr(setup,'download',lambda *_:pytest.fail('SDK downloaded twice'))
    assert setup.resolve_go(tmp_path/'sdk')==result


def test_bad_checksum_installs_nothing_and_cleans_staging(tmp_path,monkeypatch):
    monkeypatch.setattr(setup.shutil,'which',lambda _:None)
    monkeypatch.setattr(setup,'asset',lambda:('go-test.tar.gz','a'*64))
    monkeypatch.setattr(setup,'download',lambda *_:'b'*64)
    with pytest.raises(setup.SetupError,match='SHA-256 mismatch'):
        setup.resolve_go(tmp_path/'sdk')
    assert not (tmp_path/'sdk').exists() and not list(tmp_path.glob('.hx-go-*'))


@pytest.mark.parametrize('name,link',[('go/../../escape',False),('go/link',True)])
def test_archive_paths_and_links_cannot_escape_staging(tmp_path,name,link):
    archive=tmp_path/'unsafe.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        entry=tarfile.TarInfo(name)
        if link:entry.type=tarfile.SYMTYPE;entry.linkname='/outside'
        else:entry.size=1
        tar.addfile(entry,None if link else io.BytesIO(b'x'))
    with pytest.raises(setup.SetupError,match='Unsafe Go SDK archive entry'):
        setup.extract_sdk(archive,tmp_path/'staging')
    assert not (tmp_path/'staging').exists()


def test_build_failure_keeps_existing_helper_and_success_replaces_it(tmp_path):
    destination=tmp_path/'tools/hx-d2-bridge';destination.parent.mkdir()
    destination.write_text('existing helper')
    with pytest.raises(subprocess.CalledProcessError):
        setup.build(fake_go(tmp_path/'bad/go',failure=True),destination)
    assert destination.read_text()=='existing helper'
    data=json.loads(setup.build(fake_go(tmp_path/'good/go'),destination))
    assert data['protocol']=='hx-d2-bridge/1' and os.access(destination,os.X_OK)
    assert not list(destination.parent.glob('.hx-d2-build-*'))


def test_shell_wrapper_retains_destination_argument_and_reports_selected_go(tmp_path):
    go=fake_go(tmp_path/'bin/go')
    output=tmp_path/'custom/helper'
    result=subprocess.run(['bash',str(SCRIPT.with_suffix('.sh')),'--no-bootstrap',str(output)],
                          env={**os.environ,'PYTHON':sys.executable,'PATH':str(go.parent)+os.pathsep+os.environ['PATH']},
                          text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert 'Using Go 1.27.3' in result.stderr and output.is_file()
    assert json.loads(result.stdout)['protocol']=='hx-d2-bridge/1'
