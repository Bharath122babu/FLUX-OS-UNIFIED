from __future__ import annotations
import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from fluxos.agent import Workspace,GemmaClient,ConfigError,GemmaAgent
from fluxos.api import create_app
from fluxos.kernel import Memory,Principal
from fluxos import demo
from fluxos.benchmark import benchmark

def test_workspace_roundtrip(tmp_path):
    w=Workspace(tmp_path)
    w.write_file('x/calc.py','def f(): return 3')
    assert w.read_file('x/calc.py')=='def f(): return 3'
    assert w.list_files()==['x/calc.py']

def test_workspace_traversal_blocked(tmp_path):
    w=Workspace(tmp_path)
    for s in ('../pass.py','/etc/passwd','a\\b.py'):
        with pytest.raises(ValueError):w.write_file(s,'oops')

def test_workspace_symlink_escape(tmp_path,create_symlink):
    w=Workspace(tmp_path/'work')
    create_symlink(w.path/'escape',tmp_path)
    with pytest.raises(ValueError):w.write_file('escape/out.py','bad')

def test_docker_required_not_fake(tmp_path,monkeypatch):
    import fluxos.agent as agent
    monkeypatch.setattr(agent.shutil,'which',lambda _:None)
    assert Workspace(tmp_path).run_tests()['status']=='UNAVAILABLE'

def test_no_fake_gemma_without_key(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    with pytest.raises(ConfigError):GemmaClient()

def test_native_function_call_transport(tmp_path):
    log=[]
    def fake(req):
        body=json.loads(req.content);log.append(body)
        if len(log)==1:
            data={'candidates':[{'content':{'parts':[{'functionCall':{'name':'write_file','args':{'path':'hello.py','content':'print(42)'}}}]}}]}
        else:data={'candidates':[{'content':{'parts':[{'text':'Wrote hello.py. Tests were unavailable.'}]}}]}
        return httpx.Response(200,json=data)
    client=GemmaClient(key='fake-for-mock',transport=httpx.MockTransport(fake))
    memory=Memory(tmp_path/'db');actor=Principal('worker','mock',1,frozenset({'reader','writer'}))
    memory.put_fact(actor,'task',{'goal':'write hello'})
    agent=GemmaAgent(client,memory,actor,Workspace(tmp_path/'code'),'task')
    out=agent.run('Make hello.py',max_steps=3)
    assert out['status']=='DRAFT'
    assert not (tmp_path/'code'/'hello.py').exists()  # candidate never mutates canonical checkout
    assert out['published_snapshot'] is None
    assert out['draft_snapshot'] is not None
    assert (Path(out['draft_snapshot']['path'])/'hello.py').read_text()=='print(42)'
    assert out['draft_snapshot']['file_hashes']['hello.py']
    assert len(log)==2
    assert log[1]['contents'][2]['parts'][0]['functionResponse']['name']=='write_file'
    with pytest.raises(KeyError):memory.status(actor,'result:latest')

def test_demo_survives_independent(tmp_path):
    home=tmp_path/'demo'
    before=demo.bootstrap(home)
    during=demo.mutate(home)
    assert before['statuses']=={'frontend':'DECLARED_CURRENT','integration':'DECLARED_CURRENT','styles':'DECLARED_CURRENT'}
    assert during['statuses']=={'frontend':'STALE','integration':'STALE','styles':'DECLARED_CURRENT'}
    after=demo.repair(home)
    assert set(after['statuses'].values())=={'DECLARED_CURRENT'}
    assert 'student_id' in after['files']['frontend.ts']

def test_api_flow(tmp_path):
    c=TestClient(create_app(tmp_path))
    assert c.get('/api/health').status_code==200
    assert c.get('/').status_code==200
    assert c.get('/api/demo').status_code==200
    assert c.post('/api/demo/change',json={'field':'uid'}).json()['statuses']['frontend']=='STALE'
    assert c.post('/api/demo/repair').json()['statuses']['frontend']=='DECLARED_CURRENT'
    assert c.post('/api/demo/change',json={'field':'../../etc'}).status_code==422

def test_benchmark_counts():
    r=benchmark()
    assert r['baseline_units_restarted']==3
    assert r['flux_units_repaired']==2
    assert r['all_current_after_repair'] is True
    assert r['gemma_calls']==0

def test_dynamic_parallel_agents_merge_distinct_files(tmp_path):
    import threading
    model_calls=[]
    lock=threading.Lock()
    def fake(req):
        body=json.loads(req.content)
        contents=body['contents']
        first=contents[0]['parts'][0]['text']
        if 'Task: parent' in first:
            if len(contents)==1:
                parts=[{'functionCall':{'name':'spawn_workers','args':{'tasks':['Implement the independent alpha module','Implement the independent beta module']}}}]
            else:parts=[{'text':'Delegation complete. Tests must be independently checked.'}]
        else:
            name='alpha.py' if 'alpha' in first else 'beta.py'
            if len(contents)==1:parts=[{'functionCall':{'name':'write_file','args':{'path':name,'content':'answer = 42\n'}}}]
            else:parts=[{'text':'Completed child task'}]
        with lock:model_calls.append(first[:50])
        return httpx.Response(200,json={'candidates':[{'content':{'parts':parts}}]})
    memory=Memory(tmp_path/'db');actor=Principal('worker','mock',1,frozenset({'reader','writer'}))
    memory.put_fact(actor,'task',{'goal':'parallel'})
    agent=GemmaAgent(GemmaClient(key='test',transport=httpx.MockTransport(fake)),memory,actor,Workspace(tmp_path/'code'),'task')
    result=agent.run('parent',max_steps=3)
    assert sorted(result['files'])==['alpha.py','beta.py']
    assert len(memory.jobs('mock'))==2
    assert {x['state'] for x in memory.jobs('mock')}=={'COMPLETED'}
    assert len(model_calls)==6


def test_api_rejects_missing_gemma_key(tmp_path,monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    client=TestClient(create_app(tmp_path))
    r=client.post('/api/gemma/run',json={'task':'Write a simple hello world program'})
    assert r.status_code==422
    assert 'GEMINI_API_KEY' in r.text

def test_requirement_change_during_model_run_rejects_authoritative_result(tmp_path):
    actor=Principal('runner','mock',1,frozenset({'reader','writer'}))
    mem=Memory(tmp_path/'db');mem.put_fact(actor,'req',{'goal':'make one module'})
    calls=0
    def mutate_on_call(req):
        nonlocal calls
        calls+=1
        if calls==1:
            mem.put_fact(actor,'req',{'goal':'different module'})
            return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'functionCall':{'name':'write_file','args':{'path':'old.py','content':'x=1'}}}]}}]})
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'Done'}]}}]})
    agent=GemmaAgent(GemmaClient(key='mock',transport=httpx.MockTransport(mutate_on_call)),mem,actor,Workspace(tmp_path/'code'),'req')
    result=agent.run('build module')
    assert result['status']=='STALE_REJECTED'
    assert not (tmp_path/'code'/'old.py').exists()
    assert result['published_snapshot'] is None
    assert mem.graph('mock')['nodes']==[]

def test_gemma_multimodal_request_is_wired(tmp_path):
    seen=[]
    def fake(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'No code requested'}]}}]})
    mem=Memory(tmp_path/'db');actor=Principal('agent','demo',1,frozenset({'reader','writer'}))
    mem.put_fact(actor,'req',{'goal':'look at diagram'})
    a=GemmaAgent(GemmaClient(key='mock',transport=httpx.MockTransport(fake)),mem,actor,Workspace(tmp_path/'work'),'req')
    a.run('Interpret diagram',image=(b'\x89PNG\r\n','image/png'))
    part=seen[0]['contents'][0]['parts'][1]
    assert part['inlineData']['mimeType']=='image/png'
    assert part['inlineData']['data'].startswith('iVBOR')
