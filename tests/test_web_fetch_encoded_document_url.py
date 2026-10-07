import http.server
import threading
import pytest
import requests
from urllib.parse import urlsplit
from agent.tools.web_fetch.web_fetch import WebFetch

@pytest.fixture(scope='module')
def owned_server():
    requests_seen=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests_seen.append(self.path)
            body=b'Owned <strong>literal source</strong> &amp; text'
            self.send_response(200)
            self.send_header('Content-Type','text/plain; charset=utf-8' if '.txt' in self.path else 'text/markdown; charset=utf-8' if '.md' in self.path else 'text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',requests_seen
    finally:server.shutdown();server.server_close();thread.join(2)

@pytest.mark.parametrize('path,document', [('source.%74%78%74',True),('source%2Emd',True),('source.txt',True),('source.md?owned=1#section',True),('page.html',False),('source%3Fnotes.%74xt?owned=a%26b',True),('source%23notes.%74xt#fragment',True),('nested%2Fsource.%74xt',True),('source%253Fnotes.txt',True),('source%252Emd',False)])
def test_public_percent_encoded_document_route(owned_server,tmp_path,path,document,monkeypatch):
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
    base,requests_seen=owned_server
    url=base+'/'+path
    expected_request=urlsplit(requests.Request('GET',url).prepare().url)
    expected_target=expected_request.path+('?' +expected_request.query if expected_request.query else '')
    before=len(requests_seen)
    result=WebFetch({'cwd':str(tmp_path)}).execute({'url':url})
    assert requests_seen[before:]==[expected_target]
    print({'supplied_path':path,'actual_request':requests_seen[before:],'producer_expected':expected_target,'document_expected':document})
    assert result.status=='success',result.result
    assert ('<strong>literal source</strong>' in result.result)==document,result.result

    if document:
        files=list((tmp_path/'tmp').iterdir())
        assert len(files)==1
        assert files[0].read_bytes()==b'Owned <strong>literal source</strong> &amp; text'
    else:
        assert not (tmp_path/'tmp').exists()
