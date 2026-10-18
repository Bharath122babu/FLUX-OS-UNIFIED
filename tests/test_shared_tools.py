"""Model-facing shared memory: conditional writes, isolation, and real tool loops."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from fluxos.agent import GemmaAgent, GemmaClient, Workspace
from fluxos.api import create_app
from fluxos.kernel import Denied, IntegrityError, Memory, Principal, Stale, digest
from fluxos.shared import SharedMemoryTools, project_memory_key


@pytest.fixture
def runtime(tmp_path):
    memory=Memory(tmp_path/'state')
    actor=Principal('worker','test',1,frozenset({'reader','writer','agent'}))
    return memory,actor


def tools(runtime,project='demo',name=None):
    memory,actor=runtime
    if name:
        actor=Principal(name,actor.scope,actor.clearance,actor.roles)
    return SharedMemoryTools(memory,actor,memory.observe(actor),project_id=project,session_id='task')


def test_observed_note_patch_does_not_invalidate_its_own_reads(runtime):
    shared=tools(runtime)
    assert shared.read()['value']=={}
    missing=shared.read('/plan')
    assert missing['present'] is False and missing['expected_hash'] is None
    assert shared.patch([{'path':'/plan','expected_hash':None,'value':'build CLI'}])['version']==2
    assert shared.memory.validate_manifest(shared.actor,shared.observation.manifest())
    assert shared.read('/plan')['value']=='build CLI'


def test_blind_tool_patch_is_rejected_even_with_a_guessed_correct_hash(runtime):
    shared=tools(runtime)
    shared.read('/plan')
    shared.patch([{'path':'/plan','expected_hash':None,'value':'first'}])
    stranger=tools(runtime,name='other')
    with pytest.raises(Stale,match='read each exact'):
        stranger.patch([{'path':'/plan','expected_hash':digest('first'),'value':'second'}])


def test_disjoint_shared_worker_edits_merge_but_same_field_races_fail(runtime):
    one=tools(runtime,name='one');two=tools(runtime,name='two')
    one.read('/a');two.read('/b')
    one.patch([{'path':'/a','expected_hash':None,'value':'alpha'}])
    two.patch([{'path':'/b','expected_hash':None,'value':'beta'}])
    first=one.read('/a');two.read('/a')
    one.patch([{'path':'/a','expected_hash':first['expected_hash'],'value':'updated'}])
    with pytest.raises(Stale):
        two.patch([{'path':'/a','expected_hash':first['expected_hash'],'value':'lost'}])
    assert tools(runtime).read()['value']=={'a':'updated','b':'beta'}


def test_different_project_notes_and_claims_are_isolated(runtime):
    one=tools(runtime,'alpha');two=tools(runtime,'beta')
    one.read('/plan')
    one.patch([{'path':'/plan','expected_hash':None,'value':'alpha only'}])
    one.record_claim('build','passing','declared-test')
    assert two.read()['value']=={}
    assert two.claims('build')=={'status':'UNAVAILABLE','claims':[]}


def test_disagreement_stays_unverified_and_persistent(runtime):
    one=tools(runtime,name='one');two=tools(runtime,name='two')
    one.record_claim('build','passing','test-a')
    assert two.record_claim('build','failing','test-b')['status']=='DISPUTED'
    assert {claim['value'] for claim in tools(runtime).claims('build')['claims']}=={'passing','failing'}


def test_own_patch_receipt_does_not_refresh_to_another_workers_later_write(runtime,monkeypatch):
    shared=tools(runtime)
    shared.read('/plan')
    original=shared.memory.patch_fact
    def raced(actor,key,changes,**kwargs):
        receipt=original(actor,key,changes,**kwargs)
        original(actor,key,[{'path':'/plan','expected_hash':digest('first'),'value':'other'}])
        return receipt
    monkeypatch.setattr(shared.memory,'patch_fact',raced)
    shared.patch([{'path':'/plan','expected_hash':None,'value':'first'}])
    with pytest.raises(Stale):
        shared.memory.validate_manifest(shared.actor,shared.observation.manifest())


def test_concurrent_first_use_creates_one_project_store(runtime):
    def read(i):return tools(runtime,name=f'worker-{i}').read()['version']
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(read,range(12)))==[1]*12


@pytest.mark.parametrize('bad',[True,False,1.0,-1,'1'])
def test_fact_versions_are_strict_nonnegative_integers(runtime,bad):
    memory,actor=runtime
    with pytest.raises(ValueError):memory.put_fact(actor,'s',{},expected_version=bad)


def test_secret_head_is_authorized_before_cas_details_are_reported(runtime):
    memory,actor=runtime
    root=Principal('operator',actor.scope,2,frozenset({'reader','writer','coordinator'}))
    memory.put_fact(root,'secret',{},label='secret')
    with pytest.raises(Denied):memory.put_fact(actor,'secret',{},expected_version=999)


@pytest.mark.parametrize('bad',[False,{},'invalid',[{}]*257])
def test_patch_rejects_invalid_or_unbounded_read_sets(runtime,bad):
    memory,actor=runtime
    memory.put_fact(actor,'s',{},expected_version=0)
    with pytest.raises(ValueError):
        memory.patch_fact(actor,'s',[{'path':'/a','expected_hash':None,'value':1}],read_manifest=bad)


def test_tampered_claims_fail_on_both_read_and_later_append(runtime):
    memory,actor=runtime
    memory.record_claim(actor,'s','p','original','source')
    with sqlite3.connect(memory.db) as conn:
        conn.execute("UPDATE claims SET value='\"tampered\"'")
    with pytest.raises(IntegrityError):memory.claims(actor,'s','p')
    with pytest.raises(IntegrityError):memory.record_claim(actor,'s','p','new','source')
    with sqlite3.connect(memory.db) as conn:
        assert conn.execute('SELECT count(*) FROM claims').fetchone()[0]==1


def test_model_tool_loop_can_share_notes_and_publish_only_with_acceptance(tmp_path,monkeypatch):
    memory=Memory(tmp_path/'state')
    actor=Principal('worker','scope',1,frozenset({'reader','writer','agent'}))
    memory.put_fact(actor,'task',{'goal':'build CLI'},expected_version=0)
    acceptance=tmp_path/'acceptance';acceptance.mkdir()
    steps=[
        [('read_shared_memory',{'pointer':'/plan'})],
        [('patch_shared_memory',{'changes':[{'path':'/plan','expected_hash':None,'value':'print hello'}]}),
         ('record_shared_claim',{'predicate':'build','value':'ready','source':'model assertion'}),
         ('write_file',{'path':'main.py','content':'print("hello")\n'})],
        [('read_shared_claims',{'predicate':'build'})],
    ]
    seen=[]
    def response(request):
        payload=json.loads(request.content)
        seen.append(payload)
        turn=len(seen)-1
        calls=steps[turn] if turn<len(steps) else []
        parts=([{'functionCall':{'name':name,'args':args}} for name,args in calls]
               if calls else [{'text':'done'}])
        return httpx.Response(200,json={'candidates':[{'content':{'parts':parts}}]})
    monkeypatch.setattr(Workspace,'run_tests',lambda self:{'status':'NO_TESTS'})
    monkeypatch.setattr(Workspace,'run_blackbox',lambda self,*_:{'status':'PASS','test_count':1,
        'trust_boundary':'blackbox','contract_hash':'trusted-contract','candidate_manifest_hash':self.manifest_digest()})
    client=GemmaClient(key='mock',transport=httpx.MockTransport(response))
    agent=GemmaAgent(client,memory,actor,Workspace(tmp_path/'code'),'task',
                     project_id='demo',base_revision=0,acceptance_dir=acceptance)
    result=agent.run('build CLI')
    assert result['status']=='VERIFIED',result
    assert all(entry['ok'] for entry in result['trace'])
    declared={tool['name'] for tool in seen[0]['tools'][0]['functionDeclarations']}
    assert {'read_shared_memory','patch_shared_memory','record_shared_claim','read_shared_claims'}<=declared
    assert memory.fact_head(actor,project_memory_key('demo'))['value']=={'plan':'print hello'}
    assert memory.project_head(actor,'demo')['revision']==1


def test_advisory_claim_cannot_authorize_code_release(runtime,tmp_path,monkeypatch):
    memory,actor=runtime
    memory.put_fact(actor,'task',{'goal':'build'},expected_version=0)
    class Model:
        model='mock'
        def generate(self,contents,definitions,system):
            if len(contents)==1:
                return {'parts':[
                    {'functionCall':{'name':'record_shared_claim','args':{'predicate':'tests','value':'PASS','source':'model'}}},
                    {'functionCall':{'name':'write_file','args':{'path':'main.py','content':'pass'}}}]}
            return {'parts':[{'text':'done'}]}
    monkeypatch.setattr(Workspace,'run_tests',lambda self:{'status':'PASS','test_count':100})
    agent=GemmaAgent(Model(),memory,actor,Workspace(tmp_path/'code'),'task',project_id='demo')
    assert agent.run('build')['status']=='DRAFT'
    assert memory.project_head(actor,'demo') is None


def test_memory_api_does_not_create_state_on_read_and_reports_project_notes(tmp_path):
    home=tmp_path/'app'
    app=TestClient(create_app(home))
    assert app.get('/api/projects/demo/memory').json()['version']==0
    memory=Memory(home/'gemma_state')
    actor=Principal('gemma-worker','gemma-demo',1,frozenset({'reader','writer','agent'}))
    shared=tools((memory,actor));shared.read('/plan')
    shared.patch([{'path':'/plan','expected_hash':None,'value':'persisted'}])
    assert app.get('/api/projects/demo/memory').json()['notes']=={'plan':'persisted'}
    assert app.get('/api/projects/other/memory').json()['notes']=={}
    assert app.get('/api/projects/bad.id/memory').status_code==422


def test_model_configuration_and_health_use_the_same_env(runtime,monkeypatch,tmp_path):
    monkeypatch.setenv('GEMMA_MODEL','gemma-test-model')
    assert GemmaClient(key='mock').model=='gemma-test-model'
    assert GemmaClient(key='mock',model='explicit').model=='explicit'
    assert TestClient(create_app(tmp_path/'api')).get('/api/health').json()['model']=='gemma-test-model'


@pytest.mark.parametrize('reconcile',[False,True])
def test_cancelled_or_interrupted_workers_cannot_mutate_shared_state(runtime,reconcile):
    memory,actor=runtime
    job=memory.create_job(actor.scope,actor.name,'work',actor=actor)
    generation=memory.set_job(job,'RUNNING',actor=actor)
    shared=SharedMemoryTools(memory,actor,memory.observe(actor),project_id='demo',
                            session_id='task',job_fences=[(job,generation)])
    shared.read('/plan')
    if reconcile:
        memory.reconcile_interrupted_jobs(actor.scope)
    else:
        memory.set_job(job,'CANCELLED',actor=actor)
    with pytest.raises(Stale,match='fence'):
        shared.patch([{'path':'/plan','expected_hash':None,'value':'late'}])
    with pytest.raises(Stale,match='fence'):
        shared.record_claim('tests','PASS','late assertion')
    assert memory.fact_head(actor,shared.key)['value']=={}
    assert memory.claims(actor,shared.key,'tests')['claims']==[]


def test_parent_cancellation_fences_child_shared_writes(runtime):
    memory,actor=runtime
    parent=memory.create_job(actor.scope,actor.name,'parent',actor=actor)
    parent_gen=memory.set_job(parent,'RUNNING',actor=actor)
    child=memory.create_job(actor.scope,actor.name,'child',parent,actor=actor)
    child_gen=memory.set_job(child,'RUNNING',actor=actor)
    shared=SharedMemoryTools(memory,actor,memory.observe(actor),project_id='demo',session_id='task',
                            job_fences=[(parent,parent_gen),(child,child_gen)])
    shared.read('/plan')
    memory.set_job(parent,'CANCELLED',actor=actor)
    with pytest.raises(Stale):shared.patch([{'path':'/plan','expected_hash':None,'value':'late'}])


def test_delegated_worker_inherits_parent_project_memory(runtime,tmp_path,monkeypatch):
    memory,actor=runtime
    memory.put_fact(actor,'task',{'goal':'share'},expected_version=0)
    child_calls=[]
    class Model:
        model='mock'
        def generate(self,contents,definitions,system):
            task=contents[0]['parts'][0]['text']
            first=len(contents)==1
            if task.startswith('Task: parent'):
                if first:
                    return {'parts':[{'functionCall':{'name':'spawn_workers','args':{'tasks':['child shared note']}}}]}
                return {'parts':[{'text':'done'}]}
            assert 'spawn_workers' not in {item['name'] for item in definitions}
            child_calls.append(1)
            if first:
                calls=[('read_shared_memory',{'pointer':'/child'})]
            elif len(child_calls)==2:
                calls=[('patch_shared_memory',{'changes':[{'path':'/child','expected_hash':None,'value':'from child'}]}),
                       ('write_file',{'path':'child.py','content':'pass'})]
            else:
                return {'parts':[{'text':'done'}]}
            return {'parts':[{'functionCall':{'name':name,'args':args}} for name,args in calls]}
    monkeypatch.setattr(Workspace,'run_tests',lambda self:{'status':'NO_TESTS'})
    agent=GemmaAgent(Model(),memory,actor,Workspace(tmp_path/'code'),'task',project_id='demo')
    result=agent.run('parent')
    assert result['status']=='DRAFT',result
    assert memory.fact_head(actor,project_memory_key('demo'))['value']=={'child':'from child'}
    assert 'child.py' in result['files']


def test_changed_shared_read_rejects_candidate_even_when_acceptance_passes(runtime,tmp_path,monkeypatch):
    memory,actor=runtime
    memory.put_fact(actor,'task',{'goal':'share'},expected_version=0)
    shared=tools(runtime)
    shared.read('/plan');shared.patch([{'path':'/plan','expected_hash':None,'value':'old'}])
    directory=tmp_path/'acceptance';directory.mkdir()
    class Model:
        model='mock'
        def generate(self,contents,definitions,system):
            if len(contents)==1:
                return {'parts':[{'functionCall':{'name':'read_shared_memory','args':{'pointer':'/plan'}}}]}
            if len(contents)==3:
                memory.patch_fact(actor,shared.key,[{'path':'/plan','expected_hash':digest('old'),'value':'new'}])
                return {'parts':[{'functionCall':{'name':'write_file','args':{'path':'main.py','content':'pass'}}}]}
            return {'parts':[{'text':'done'}]}
    monkeypatch.setattr(Workspace,'run_tests',lambda self:{'status':'NO_TESTS'})
    monkeypatch.setattr(Workspace,'run_blackbox',lambda self,*_:{'status':'PASS','test_count':1,
        'trust_boundary':'blackbox','contract_hash':'test','candidate_manifest_hash':self.manifest_digest()})
    agent=GemmaAgent(Model(),memory,actor,Workspace(tmp_path/'code'),'task',project_id='demo',
                    base_revision=0,acceptance_dir=directory)
    assert agent.run('share')['status']=='STALE_REJECTED'
    assert memory.project_head(actor,'demo') is None
