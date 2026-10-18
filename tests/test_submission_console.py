from fastapi.testclient import TestClient

from fluxos.api import create_app


def test_console_assets_and_real_kernel_probe_without_credentials(tmp_path,monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    client=TestClient(create_app(tmp_path))
    assert client.get('/').json()['console']=='/ui/'
    assert 'Command center' in client.get('/ui/').text
    assert client.get('/ui/app.js').status_code==200
    assert client.get('/ui/styles.css').status_code==200
    response=client.post('/api/protocol-test').json()
    assert response['result']=='PASS'
    assert response['baseline']['lost_update'] is True
    assert response['flux']['worker_b']=='STALE_REJECTED'
    assert response['flux']['lost_update'] is False
    assert client.get('/ui/',headers={'Origin':'https://example.invalid'}).status_code==403


def test_provider_configuration_is_app_local_and_never_echoes_key(tmp_path,monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    first=TestClient(create_app(tmp_path/'first'))
    second=TestClient(create_app(tmp_path/'second'))
    secret='UNIT_TEST_ONLY_NOT_A_CREDENTIAL'
    reply=first.post('/api/provider/configure',json={'api_key':secret,'models':['gemma-4-31b-it']})
    assert reply.status_code==200 and secret not in reply.text
    assert first.get('/api/health').json()['model']=='gemma-4-31b-it'
    assert first.get('/api/health').json()['gemma_key_present']
    assert not second.get('/api/health').json()['gemma_key_present']
    assert first.post('/api/provider/configure',json={'api_key':secret,'models':[]}).status_code==422
    assert first.post('/api/provider/configure',json={'api_key':secret,'models':['models/invalid']}).status_code==422
    assert all(secret not in p.read_text(errors='ignore') for p in tmp_path.rglob('*') if p.is_file())


def test_chat_fallback_reports_model_and_sanitizes_errors(tmp_path,monkeypatch):
    import fluxos.api as api
    calls=[]
    class MockClient:
        def __init__(self,*,key,model):self.model=model;calls.append(model)
        def generate(self,*args):
            if self.model=='unavailable':raise RuntimeError('PRIVATE_DIAGNOSTIC')
            return {'parts':[{'text':'private thought','thought':True},{'text':'READY'}]}
    monkeypatch.setattr(api,'GemmaClient',MockClient)
    client=TestClient(create_app(tmp_path))
    client.post('/api/provider/configure',json={'api_key':'UNIT_TEST_ONLY','models':['unavailable','gemma-4-31b-it']})
    reply=client.post('/api/chat',json={'message':'Hello'}).json()
    assert reply=={'model':'gemma-4-31b-it','reply':'READY','fallback_used':True}
    assert calls==['unavailable','gemma-4-31b-it']
    client.post('/api/provider/configure',json={'api_key':'UNIT_TEST_ONLY','models':['unavailable']})
    failure=client.post('/api/chat',json={'message':'Hello'})
    assert failure.status_code==502 and 'PRIVATE_DIAGNOSTIC' not in failure.text


def test_coding_run_uses_configured_primary_without_chat_fallback(tmp_path,monkeypatch):
    import fluxos.api as api
    calls=[]
    class MockClient:
        def __init__(self,*,key,model):self.model=model;calls.append(model)
        def generate(self,contents,*args):
            if len(contents)==1:return {'parts':[{'functionCall':{'name':'write_file','args':{'path':'main.py','content':'print(42)\n'}}}]}
            return {'parts':[{'text':'Ready'}]}
    monkeypatch.setattr(api,'GemmaClient',MockClient)
    client=TestClient(create_app(tmp_path))
    client.post('/api/provider/configure',json={'api_key':'UNIT_TEST_ONLY','models':['primary','secondary']})
    result=client.post('/api/gemma/run',json={'project_id':'console-test','task':'Write a Python CLI'})
    assert result.status_code==200,result.text
    assert result.json()['status']=='DRAFT'  # no operator acceptance contract
    assert calls==['primary']
