"""Independent measurements and navigation on the production SVG presenter."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from test_architecture import d2_bridge, FIXTURES
from test_e2e_viewer import browser
from dev.d2_ports_experiment.geometry import analyze
from dev.d2_ports_experiment.model import fixture_cases
from dev.d2_ports_experiment.run import check_navigation, servers
from hx.architecture import load_architecture
from hx.architecture.presentation import build_html, payload
from hx.model import Edge, Graph, Loc, Node, Param, TypeUse

MEASURE=Path(__file__).parents[1]/'dev/d2_integration_experiment/measure.js'


@pytest.fixture
def arch_graph(tmp_path):
    source=tmp_path/'src';source.mkdir()
    original=Path(__file__).parents[1]/'dev/d2_ports_experiment/fixtures/rust/src/lib.rs'
    text=original.read_text();(source/'lib.rs').write_text(text)
    graph=Graph(root=str(tmp_path),lang='rs',entry='rs:src/lib.rs::produce')
    for function in ('produce','consume','transform','run'):
        symbol='rs:src/lib.rs::'+function
        line=next(i for i,t in enumerate(text.splitlines(),1) if 'fn '+function+'(' in t)
        names=('seed','enabled') if function in {'produce','run'} else ('sample','valid')
        sig=f'pub fn {function}({names[0]}: u32, {names[1]}: bool) -> (u32, bool)'
        graph.nodes[symbol]=Node(symbol,'function',function,function,'rs',Loc('src/lib.rs',line,line+2),sig,
                                 params=[Param(names[0],'u32'),Param(names[1],'bool')],returns=TypeUse('(u32, bool)'))
    graph.nodes[graph.entry].calls=['rs:src/lib.rs::consume']
    graph.edges=[Edge(graph.entry,'rs:src/lib.rs::consume','call')]
    path=tmp_path/'graph.json';graph.save(str(path))
    return path


def test_offline_export_renders_without_fetches_and_fit_works(tmp_path,browser,d2_bridge):
    doc=load_architecture(str(FIXTURES/'nested.d2'),bridge=d2_bridge)
    path=tmp_path/'architecture.html';path.write_text(build_html(doc))
    page=browser.new_page();requests=[];page.on('request',lambda r:requests.append(r.url))
    try:
        page.goto(path.as_uri());page.wait_for_function('window.HX_ARCH_READY || window.HX_ARCH_ERROR')
        assert not page.evaluate('window.HX_ARCH_ERROR')
        assert len(page.locator('circle').all())==12
        assert not any(u.startswith(('http:','https:')) for u in requests)
        assert 'code navigation unavailable' in page.locator('#status').inner_text()
        page.locator('[data-hx-id="pipeline"] text').click()
        assert 'Block: Pipeline' in page.locator('#detail').inner_text()
        page.locator('[data-hx-id="pipeline.first.in_sample"] circle').click()
        assert 'Input port: sample: u32' in page.locator('#detail').inner_text()
        assert 'Within: pipeline.first' in page.locator('#detail').inner_text()
        initial=page.locator('svg').get_attribute('viewBox')
        page.locator('svg').dispatch_event('wheel',{'deltaY':100,'clientX':300,'clientY':300})
        assert page.locator('svg').get_attribute('viewBox')!=initial
        page.locator('#fit').click();assert page.locator('svg').get_attribute('viewBox')==initial
    finally:page.close()


@pytest.mark.parametrize('mutation,expected',[
    ("document.querySelector('[data-hx-id=\"source.in_sample\"] circle').setAttribute('cx',40)",'pin-not-on-boundary'),
    ("document.querySelector('[data-hx-id=\"source.out_sample\"]').remove()",'missing-pin'),
    ("document.querySelector('[data-hx-role=wire] path').setAttribute('d','M0,0 L10,10')",'wrong-endpoint'),
    ("document.querySelector('[data-hx-label-for=\"source.in_sample\"] text').setAttribute('x',-500)",'clipped-label'),
    ("document.querySelector('[data-hx-id=source] a').setAttribute('href','http://wrong.invalid')",'missing-code-link'),
    ("document.querySelector('[data-hx-role=wire] path').setAttribute('marker-end','url(#unknown)')",'measurement-unavailable'),
])
def test_geometry_oracle_detects_rendered_defects(tmp_path,browser,d2_bridge,arch_graph,mutation,expected):
    doc=load_architecture(str(FIXTURES/'flat.d2'),bridge=d2_bridge,graph=str(arch_graph))
    case=fixture_cases()[0];urls=payload(doc,'http://localhost:1/')['code_urls']
    path=tmp_path/'diagram.html';path.write_text(build_html(doc,code_url='http://localhost:1/'))
    page=browser.new_page()
    try:
        page.goto(path.as_uri());page.wait_for_function('window.HX_ARCH_READY')
        assert analyze(case,page.evaluate(MEASURE.read_text()),urls)['passed']
        page.evaluate(mutation)
        result=analyze(case,page.evaluate(MEASURE.read_text()),urls)
        assert not result['passed'] and expected in {e['code'] for e in result['errors']}
    finally:page.close()


def test_real_navigation_and_cancelled_click_do_not_share_a_false_pass(tmp_path,browser,d2_bridge,arch_graph):
    case=fixture_cases()[0]
    with servers(tmp_path,arch_graph,tmp_path) as (static,viewer):
        doc=load_architecture(str(FIXTURES/'flat.d2'),bridge=d2_bridge,graph=str(arch_graph))
        urls=payload(doc,viewer+'/')['code_urls']
        (tmp_path/'diagram.html').write_text(build_html(doc,code_url=viewer+'/'))
        context=browser.new_context(viewport={'width':1800,'height':1100});page=context.new_page()
        try:
            page.goto(static+'/diagram.html');page.wait_for_function('window.HX_ARCH_READY')
            results=check_navigation(context,page,case,urls)
            assert len(results)==10 and all(r['passed'] for r in results),results
            page.evaluate("document.querySelector('[data-hx-id=source] a').addEventListener('click',e=>e.preventDefault())")
            result=check_navigation(context,page,deepcopy(type(case)('cancelled',[case.blocks[0]],[],[])),urls)
            assert not result[0]['passed']
        finally:context.close()


def test_dedicated_preview_uses_code_graph_root_and_clears_invalid_refresh(tmp_path,browser,d2_bridge,arch_graph):
    import socket
    import threading
    import time
    import uvicorn
    from hx.architecture.serve import create_architecture_app
    design_dir=tmp_path/'design';shutil.copytree(FIXTURES,design_dir)
    app=create_architecture_app(str(design_dir/'flat.d2'),graph=str(arch_graph),bridge=d2_bridge)
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
    url='http://127.0.0.1:'+str(sock.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    context=browser.new_context(viewport={'width':1800,'height':1100});page=context.new_page()
    try:
        for _ in range(200):
            if server.started:break
            time.sleep(.025)
        assert server.started
        page.goto(url+'/architecture');page.wait_for_function('window.HX_ARCH_READY')
        data=page.request.get(url+'/api/architecture').json()
        assert all(u.startswith(url+'/#') for u in data['code_urls'].values())
        results=check_navigation(context,page,fixture_cases()[0],data['code_urls'])
        assert all(r['passed'] for r in results),results
        (design_dir/'flat.d2').write_text('a: {')
        page.reload();page.wait_for_function('window.HX_ARCH_ERROR')
        assert page.locator('#canvas svg').count()==0
        assert 'd2-compile' in page.locator('#diagnostics').inner_text()
    finally:
        context.close();server.should_exit=True;thread.join(timeout=10);sock.close()
