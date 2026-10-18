"""v0.4 reusable project state, optimistic publication, safe acceptance tests."""
from __future__ import annotations
import concurrent.futures
import io
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from fluxos.agent import Workspace, GemmaClient
from fluxos.api import create_app
from fluxos.gateway import UnifiedGate
from fluxos.kernel import Memory, Principal, Stale, IntegrityError

@pytest.fixture
def setup(tmp_path):
    mem=Memory(tmp_path/'state')
    actor=Principal('worker','gemma-demo',1,frozenset({'reader','writer'}))
    return mem,actor,tmp_path

def publish(setup,project='campus',base=0,name='main.py',value='print(42)\n'):
    mem,actor,root=setup
    job=mem.create_job(actor.scope,actor.name,'build project',actor=actor)
    epoch=mem.set_job(job,'RUNNING',actor=actor)
    work=Workspace(root/('workspace-'+job))
    work.write_file(name,value)
    gate=UnifiedGate(mem,actor)
    return gate.publish(candidate=work,baseline=None,base_manifest={},observation=mem.observe(actor),
        developer={'status':'NO_TESTS'},acceptance={'status':'PASS','test_count':1,
        'trust_boundary':'blackbox','contract_hash':'abcd',
        'candidate_manifest_hash':work.manifest_digest()},
        model='mock',calls=1,output_id='result:'+job,job_id=job,generation=epoch,
        project_id=project,base_revision=base,
        trusted_acceptance=lambda sealed:{'status':'PASS','test_count':1,'trust_boundary':'blackbox',
            'contract_hash':'test-contract','candidate_manifest_hash':sealed.manifest_digest()})

def test_new_project_head_is_none(setup):
    mem,actor,_=setup
    assert mem.project_head(actor,'new') is None
    assert mem.project_history(actor,'new')==[]

def test_committed_project_is_reopenable(setup):
    result=publish(setup)
    assert result.status=='VERIFIED'
    mem,actor,_=setup
    head=mem.project_head(actor,'campus')
    assert head['revision']==1
    assert head['files']==result.published_snapshot['file_hashes']
    assert (Path(head['snapshot_path'])/'main.py').read_text()=='print(42)\n'
    assert len(mem.project_history(actor,'campus'))==1

def test_stale_project_commit_does_not_replace_head(setup):
    assert publish(setup).decision=='COMMIT'
    loser=publish(setup,base=0,value='print(99)\n')
    assert loser.decision=='REPAIR' and loser.status=='STALE_REJECTED'
    mem,actor,_=setup
    assert mem.project_head(actor,'campus')['revision']==1
    assert (Path(mem.project_head(actor,'campus')['snapshot_path'])/'main.py').read_text()=='print(42)\n'

def test_next_project_revision_advances(setup):
    assert publish(setup).status=='VERIFIED'
    assert publish(setup,base=1,value='print(99)\n').status=='VERIFIED'
    mem,actor,_=setup
    assert mem.project_head(actor,'campus')['revision']==2
    assert [x['revision'] for x in mem.project_history(actor,'campus')]==[1,2]

def test_concurrent_project_publications_have_single_winner(setup):
    mem,actor,root=setup
    def attempt(i):
        return publish(setup,base=0,name=f'candidate{i}.py',value=f'x={i}')
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(attempt,range(6)))
    assert sum(x.decision=='COMMIT' for x in results)==1
    assert sum(x.decision=='REPAIR' for x in results)==5
    assert mem.project_head(actor,'campus')['revision']==1

def test_untrusted_acceptance_claim_not_enough_for_project(setup):
    mem,actor,root=setup
    j=mem.create_job(actor.scope,actor.name,'build',actor=actor)
    epoch=mem.set_job(j,'RUNNING',actor=actor)
    w=Workspace(root/'candidate');w.write_file('app.py','print(1)')
    g=UnifiedGate(mem,actor).publish(candidate=w,baseline=None,base_manifest={},
        observation=mem.observe(actor),developer={'status':'NO_TESTS'},
        acceptance={'status':'PASS','test_count':3},model='mock',calls=1,
        output_id='result:'+j,job_id=j,generation=epoch,project_id='campus',base_revision=0)
    assert g.decision=='CONTINUE_PRIVATE' and g.status=='DRAFT'
    assert mem.project_head(actor,'campus') is None

def test_project_head_detects_snapshot_tampering(setup):
    assert publish(setup).decision=='COMMIT'
    mem,actor,_=setup
    head=mem.project_head(actor,'campus')
    (Path(head['snapshot_path'])/'main.py').write_text('tampered')
    with pytest.raises(IntegrityError):mem.project_head(actor,'campus')

def test_api_project_export_contains_accepted_revision(setup):
    assert publish(setup).decision=='COMMIT'
    mem,actor,root=setup
    # Use the same database layout as the server's gemma_state.
    app=TestClient(create_app(root/'server'))
    # Seed in server's own canonical store instead of manually changing DB paths.
    project_mem=Memory(root/'server'/'gemma_state')
    job=project_mem.create_job('gemma-demo','gemma-worker','task',actor=Principal('gemma-worker','gemma-demo',1,frozenset({'reader','writer'})))
    person=Principal('gemma-worker','gemma-demo',1,frozenset({'reader','writer'}))
    epoch=project_mem.set_job(job,'RUNNING',actor=person)
    w=Workspace(root/'server'/'gemma_workspace'/job)
    w.write_file('src/app.py','print("hello")\n')
    output=UnifiedGate(project_mem,person).publish(candidate=w,baseline=None,base_manifest={},
        observation=project_mem.observe(person),developer={'status':'NO_TESTS'},
        acceptance={'status':'PASS','test_count':1,'trust_boundary':'blackbox',
        'contract_hash':'abcd','candidate_manifest_hash':w.manifest_digest()},model='mock',calls=1,
        output_id='result:'+job,job_id=job,generation=epoch,project_id='campus',base_revision=0,
        trusted_acceptance=lambda sealed:{'status':'PASS','test_count':1,'trust_boundary':'blackbox',
            'contract_hash':'test-contract','candidate_manifest_hash':sealed.manifest_digest()})
    assert output.status=='VERIFIED'
    response=app.get('/api/projects/campus')
    assert response.status_code==200
    assert response.json()['head']['revision']==1
    assert 'snapshot_path' not in response.json()['head']
    import zipfile
    download=app.get('/api/projects/campus/export')
    assert download.status_code==200
    with zipfile.ZipFile(io.BytesIO(download.content)) as z:
        assert z.namelist()==['src/app.py']
        assert z.read('src/app.py')==b'print("hello")\n'

def test_blackbox_runner_requires_external_contract(tmp_path):
    w=Workspace(tmp_path/'work');w.write_file('main.py','print(42)')
    directory=tmp_path/'acceptance';directory.mkdir()
    assert w.run_blackbox(directory)['status']=='NOT_CONFIGURED'

def test_blackbox_runner_compares_exit_and_stdout(tmp_path,monkeypatch):
    import fluxos.agent as mod
    w=Workspace(tmp_path/'work');w.write_file('main.py','print(42)')
    directory=tmp_path/'acceptance';directory.mkdir()
    (directory/'cases.json').write_text(json.dumps({'entry':'main.py','cases':[
        {'stdin':'', 'stdout':'42\n', 'exit_code':0}]}))
    monkeypatch.setattr(mod.shutil,'which',lambda name:'/usr/bin/docker')
    seen=[]
    def mocked(cmd,**kwargs):
        seen.append(cmd)
        return SimpleNamespace(returncode=0,stdout='42\n',stderr='')
    monkeypatch.setattr(mod.subprocess,'run',mocked)
    ok=w.run_blackbox(directory)
    assert ok['status']=='PASS' and ok['trust_boundary']=='blackbox'
    assert ok['candidate_manifest_hash']==w.manifest_digest()
    assert '--network' in seen[0] and 'none' in seen[0]
    assert '--read-only' in seen[0]
    assert not any('/acceptance' in arg for arg in seen[0])
    (directory/'cases.json').write_text(json.dumps({'entry':'main.py','cases':[{'stdin':'','stdout':'WRONG\n'}]}))
    assert w.run_blackbox(directory)['status']=='FAIL'

def test_api_second_run_uses_accepted_project_as_context(tmp_path,monkeypatch):
    import fluxos.api as api
    import fluxos.agent as agent
    home=tmp_path/'app'
    (home/'acceptance'/'demo').mkdir(parents=True)
    (home/'acceptance'/'demo'/'cases.json').write_text(json.dumps({'entry':'app.py','cases':[{'stdin':'','stdout':'ok\n'}]}))
    calls=[]
    class FakeGemma:
        model='gemma-mock'
        def __init__(self):pass
        def generate(self,contents,tools,system):
            first=contents[0]['parts'][0]['text']
            calls.append(first)
            if len(contents)==1:
                return {'parts':[{'functionCall':{'name':'write_file','args':{
                    'path':'app.py','content':'print("ok")\n'}}}]}
            return {'parts':[{'text':'Wrote app.py'}]}
    monkeypatch.setattr(api,'GemmaClient',FakeGemma)
    monkeypatch.setattr(agent.Workspace,'run_tests',lambda self,*args,**kwargs:{'status':'NO_TESTS'})
    monkeypatch.setattr(agent.Workspace,'run_blackbox',lambda self,*args,**kwargs:{
        'status':'PASS','test_count':1,'trust_boundary':'blackbox','contract_hash':'mock',
        'candidate_manifest_hash':self.manifest_digest()})
    app=TestClient(create_app(home))
    one=app.post('/api/gemma/run',json={'task':'Make a Python print program','project_id':'demo'})
    assert one.status_code==200,one.text
    assert one.json()['status']=='VERIFIED'
    two=app.post('/api/gemma/run',json={'task':'Improve the Python print program','project_id':'demo'})
    assert two.status_code==200,two.text
    assert two.json()['status']=='VERIFIED'
    assert two.json()['project_base_revision']==1
    assert 'app.py' in calls[2]
    project=app.get('/api/projects/demo').json()
    assert project['head']['revision']==2
