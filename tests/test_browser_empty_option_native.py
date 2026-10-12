import json
import os
import re
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('COW_BROWSER_NATIVE_TEST') != '1', reason='opt-in installed browser test')

@pytest.fixture(scope='module')
def owned_browser(tmp_path_factory):
    from agent.tools.browser.browser_env import detect_system_chrome
    from agent.tools.browser.browser_tool import BrowserTool
    pytest.importorskip('playwright.sync_api')
    if detect_system_chrome() is None:
        pytest.skip('no installed system Chrome/Edge')
    tmp_path=tmp_path_factory.mktemp('cow-empty-option')
    page=tmp_path/'options.html'
    page.write_text('<html><body><select id="choice" onchange="window.events=(window.events||0)+1"><option value="">No selection</option><option selected value="new">New</option></select></body></html>')
    previous=BrowserTool._shared_service;BrowserTool._shared_service=None
    tool=BrowserTool({'cwd':str(tmp_path),'user_data_dir':str(tmp_path/'profile'),'headless':True,'idle_timeout':0,'startup_timeout':20,'engine':'system-chrome'})
    try:
        nav=tool.execute({'action':'navigate','url':page.as_uri(),'timeout':15000})
        assert nav.status=='success',nav.result
        match=re.search(r'\[(\d+)\] select\b',nav.result);assert match,nav.result
        yield tool,int(match.group(1))
    finally:
        if tool._service is not None:tool._service.close()
        BrowserTool._shared_service=previous

@pytest.mark.parametrize('value,target,expected_status', [('', 'selector','success'),('', 'ref','success'),('new','selector','success'),(None,'selector','error'),(1,'selector','error')])
def test_public_browser_selection(owned_browser,value,target,expected_status):
    tool,ref=owned_browser
    tool.execute({'action':'evaluate','script':'() => { document.querySelector("select").value="new"; window.events=0; }'})
    args={'action':'select',target:'#choice' if target=='selector' else ref,'timeout':500}
    if value is not None:args['value']=value
    result=tool.execute(args)
    state=tool._get_service().evaluate('() => ({value:document.querySelector("select").value,events:window.events})')['result']
    print(json.dumps({'args':args,'status':result.status,'state':state}))
    assert result.status==expected_status,result.result
    if expected_status=='success':assert state['value']==value and state['events']==1
    else:assert state['value']=='new' and state['events']==0
