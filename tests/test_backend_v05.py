"""Independent regression probes for the consolidated backend release.

Sandbox execution is mocked here; real Docker validation is separately required.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from fluxos.agent import Workspace, GemmaClient, GemmaAgent
from fluxos.gateway import UnifiedGate
from fluxos.kernel import Memory, Principal, IntegrityError


@pytest.fixture
def runtime(tmp_path):
    memory=Memory(tmp_path/'db')
    actor=Principal('agent','project',1,frozenset({'reader','writer'}))
    job=memory.create_job(actor.scope,actor.name,'task',actor=actor)
    generation=memory.set_job(job,'RUNNING',actor=actor)
    candidate=Workspace(tmp_path/'working')
    candidate.write_file('app.py','print("safe")\n')
    return memory,actor,job,generation,candidate


def evaluate(sealed):
    return {'status':'PASS','test_count':2,'trust_boundary':'blackbox',
            'contract_hash':'trusted-suite',
            'candidate_manifest_hash':sealed.manifest_digest()}


def publish(runtime,**kwargs):
    memory,actor,job,generation,candidate=runtime
    args=dict(candidate=candidate,baseline=None,base_manifest={},
              observation=memory.observe(actor),developer={'status':'FAIL'},
              acceptance={'status':'PASS','test_count':999,'candidate_manifest_hash':candidate.manifest_digest()},
              model='mock',calls=1,output_id='result:'+job,job_id=job,generation=generation,
              project_id='demo',base_revision=0)
    args.update(kwargs)
    return UnifiedGate(memory,actor).publish(**args)


def test_forged_acceptance_dictionary_is_not_a_release_authorization(runtime):
    out=publish(runtime)
    assert out.status=='DRAFT' and out.published_snapshot is None
    memory,actor,*_=runtime
    assert memory.project_head(actor,'demo') is None


def test_trusted_acceptance_evaluates_seal_and_commits_exact_evaluated_bytes(runtime):
    memory,actor,job,generation,candidate=runtime
    def checker(sealed):
        assert (sealed.path/'app.py').read_text()=='print("safe")\n'
        candidate.write_file('app.py','print("malicious")\n')
        return evaluate(sealed)
    out=publish(runtime,trusted_acceptance=checker)
    assert out.status=='VERIFIED',out.reason
    head=memory.project_head(actor,'demo')
    assert (Path(head['snapshot_path'])/'app.py').read_text()=='print("safe")\n'
    assert candidate.read_file('app.py')=='print("malicious")\n'
    assert out.verification['candidate_manifest_hash']==memory.artifact(actor,'result:'+job)['accepted_candidate_hash']


def test_sealed_snapshot_mutation_between_test_and_commit_is_detected(runtime):
    memory,actor,*_=runtime
    def evil(sealed):
        record=evaluate(sealed)
        path=sealed.path/'app.py'
        path.chmod(0o644)
        path.write_text('print("changed")\n')
        return record
    out=publish(runtime,trusted_acceptance=evil)
    assert out.status=='COMMIT_REJECTED' and out.decision=='REJECT'
    assert memory.project_head(actor,'demo') is None


def test_mutation_during_kernel_commit_is_detected(runtime,monkeypatch):
    memory,actor,*_=runtime
    original=memory.put_artifact
    def racing(*args,**kwargs):
        snap=Path(args[2]['snapshot'])/'app.py'
        snap.chmod(0o644)
        snap.write_text('print("bad")\n')
        return original(*args,**kwargs)
    monkeypatch.setattr(memory,'put_artifact',racing)
    out=publish(runtime,trusted_acceptance=evaluate)
    assert out.status=='COMMIT_REJECTED'
    assert memory.project_head(actor,'demo') is None


def test_contract_change_after_evaluation_rejected(runtime,tmp_path):
    contract=tmp_path/'cases.json';contract.write_text('{"entry":"app.py"}')
    original_hash=hashlib.sha256(contract.read_bytes()).hexdigest()
    def evaluator(sealed):
        contract.write_text('{"entry":"evil.py"}')
        return {**evaluate(sealed),'contract_hash':original_hash,'contract_path':str(contract)}
    out=publish(runtime,trusted_acceptance=evaluator)
    assert out.status=='STALE_REJECTED'


def test_harmless_developer_test_failure_does_not_override_independent_acceptance(runtime):
    out=publish(runtime,trusted_acceptance=evaluate)
    assert out.status=='VERIFIED'  # developer tests are untrusted diagnostics
    assert out.verification['status']=='PASS'


def test_patch_preimage_failure_keeps_all_original_files(tmp_path):
    w=Workspace(tmp_path/'work')
    w.write_file('a.py','a=1')
    w.write_file('b.py','b=2')
    expected=w.file_manifest()
    with pytest.raises(ValueError,match='preimage'):
        w.apply_changes([{'op':'write','path':'a.py','expected_sha256':expected['a.py'],'content':'a=3'},
                         {'op':'delete','path':'b.py','expected_sha256':'0'*64}])
    assert w.file_manifest()==expected


def test_patch_create_edit_move_and_delete(tmp_path):
    w=Workspace(tmp_path/'work')
    w.write_file('a.py','x=1\n')
    sha=w.file_manifest()['a.py']
    result=w.apply_changes([{'op':'edit','path':'a.py','expected_sha256':sha,'old':'x=1','new':'x=2'},
                            {'op':'write','path':'b.py','content':'y=2'}])
    assert sorted(w.list_files())==['a.py','b.py']
    assert (w.path/'a.py').read_text()=='x=2\n'
    hashes=w.file_manifest()
    w.apply_changes([{'op':'move','path':'b.py','to':'sub/b.py','expected_sha256':hashes['b.py']},
                     {'op':'delete','path':'a.py','expected_sha256':hashes['a.py']}])
    assert w.list_files()==['sub/b.py']
    assert result['changed']==['a.py','b.py']


def test_paginated_source_read_handles_large_files(tmp_path):
    w=Workspace(tmp_path/'code')
    content=''.join(f'line_{n:05d}\n' for n in range(11000))
    w.write_file('big.py',content)
    v=w.read_file_range('big.py',start=5000,count=100)
    assert v['total_lines']==11000 and v['text'].startswith('line_04999\n')
    assert v['has_more'] and len(v['sha256'])==64
    with pytest.raises(ValueError):w.read_file_range('big.py',start=0)


def test_command_declines_without_docker_and_never_uses_host(monkeypatch,tmp_path):
    import fluxos.executor as exe
    monkeypatch.setattr(exe.shutil,'which',lambda _:None)
    w=Workspace(tmp_path/'code')
    result=w.execute_command(['python','-c','print(2)'])
    assert result['status']=='UNAVAILABLE'
    with pytest.raises(ValueError):w.execute_command(['python'],timeout=60)


def test_docker_command_has_confinement_and_timeout_cleanup(monkeypatch,tmp_path):
    import fluxos.executor as exe
    monkeypatch.setattr(exe.shutil,'which',lambda _:'/usr/bin/docker')
    recorded=[]
    def runner(cmd,**kwargs):
        recorded.append(cmd)
        if cmd[1]=='run':raise subprocess.TimeoutExpired(cmd,kwargs['timeout'])
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(exe.subprocess,'run',runner)
    w=Workspace(tmp_path/'code')
    result=w.execute_command(['python','-c','print("ok")'])
    assert result['status']=='TIMEOUT'
    cmd=recorded[0]
    assert '--network' in cmd and cmd[cmd.index('--network')+1]=='none'
    assert '--cap-drop' in cmd and 'ALL' in cmd
    assert '--mount' in cmd and cmd[-1].startswith('print')
    assert recorded[1][:3]==['docker','rm','-f']


def test_docker_command_output_bounded(monkeypatch,tmp_path):
    import fluxos.executor as exe
    monkeypatch.setattr(exe.shutil,'which',lambda _:'/usr/bin/docker')
    monkeypatch.setattr(exe.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout='A'*18000,stderr=''))
    w=Workspace(tmp_path/'code')
    result=w.execute_command(['node','-e','console.log(1)'],runtime='node')
    assert result['status']=='COMPLETED' and result['truncated'] and len(result['stdout'])==12000


def test_mediated_command_witnesses_entire_input_tree(runtime):
    memory,actor,job,generation,base=runtime
    memory.put_fact(actor,'task',{'goal':'compile'})
    client=GemmaClient(key='fake',transport=httpx.MockTransport(
        lambda req:httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'done'}]}}]})))
    agent=GemmaAgent(client,memory,actor,base,'task')
    agent.source_manifest=base.file_manifest()
    agent.source_id='repo:tracked:tree'
    memory.register_source_tree(actor,agent.source_id,agent.source_manifest)
    agent._tool('read_file_range',{'path':'app.py','start':1})
    assert '/hashes/app.py' in [x['pointer'] for x in agent.obs.manifest()]
    from fluxos.agent import Workspace as W
    original=W.execute_command
    W.execute_command=lambda self,*args,**kwargs:{'status':'UNAVAILABLE'}
    try:
        agent._tool('execute_command',{'argv':['python','-V']})
    finally:
        W.execute_command=original
    assert '/names' in [x['pointer'] for x in agent.obs.manifest()]


def test_gemma_retries_transient_errors_only():
    attempts=[]
    def handle(req):
        attempts.append(1)
        if len(attempts)<3:return httpx.Response(503)
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'ok'}]}}]})
    client=GemmaClient(key='fake',transport=httpx.MockTransport(handle))
    response=client.generate([{'role':'user','parts':[{'text':'hi'}]}],[],system='system')
    assert response['parts'][0]['text']=='ok' and len(attempts)==3


def test_nonretryable_model_error_ends_immediately():
    attempts=[]
    def handle(req):
        attempts.append(1)
        return httpx.Response(401)
    client=GemmaClient(key='fake',transport=httpx.MockTransport(handle))
    with pytest.raises(httpx.HTTPStatusError):
        client.generate([{'role':'user','parts':[{'text':'hi'}]}],[],system='system')
    assert len(attempts)==1


def test_job_journal_persists_tool_results_and_gate_outcome(tmp_path):
    mem=Memory(tmp_path/'kernel')
    actor=Principal('a','s',1,frozenset({'reader','writer'}))
    mem.put_fact(actor,'task',{'goal':'simple'})
    job=mem.create_job('s','a','do simple',actor=actor)
    mem.set_job(job,'RUNNING',actor=actor)
    seen=[]
    def handle(req):
        data=json.loads(req.content)
        if len(data['contents'])==1:
            parts=[{'functionCall':{'id':'turn-1','name':'write_file','args':{'path':'app.py','content':'print(1)'}}}]
        else:parts=[{'text':'done'}]
        seen.append(1)
        return httpx.Response(200,json={'candidates':[{'content':{'parts':parts}}]})
    agent=GemmaAgent(GemmaClient(key='fake',transport=httpx.MockTransport(handle)),
                     mem,actor,Workspace(tmp_path/'code'),'task',root_job=job)
    result=agent.run('write python',max_steps=3)
    assert result['status']=='DRAFT'
    events=mem.execution_history(job)
    assert {'model.request','model.response','tool.settled','gate.outcome'}<=set(e['kind'] for e in events)
    assert next(e['details']['call_id'] for e in events if e['kind']=='tool.settled')=='turn-1'


def test_project_acceptance_contract_is_project_scoped(tmp_path,monkeypatch):
    import fluxos.api as api
    import fluxos.agent as agent
    home=tmp_path/'app'
    folder=home/'acceptance'/'alpha';folder.mkdir(parents=True)
    (folder/'cases.json').write_text('{"entry":"app.py","cases":[{"stdin":"","stdout":"ok\\n"}]}')
    class FakeModel:
        model='mock'
        def generate(self,contents,tools,system):
            if len(contents)==1:
                return {'parts':[{'functionCall':{'name':'write_file','args':{'path':'app.py','content':'print("ok")'}}}]}
            return {'parts':[{'text':'done'}]}
    monkeypatch.setattr(api,'GemmaClient',FakeModel)
    monkeypatch.setattr(agent.Workspace,'run_tests',lambda self,*args,**kw:{'status':'NO_TESTS'})
    monkeypatch.setattr(agent.Workspace,'run_blackbox',lambda self,*args,**kw:evaluate(self))
    app=TestClient(api.create_app(home))
    yes=app.post('/api/gemma/run',json={'task':'write python CLI','project_id':'alpha'})
    assert yes.status_code==200 and yes.json()['status']=='VERIFIED',yes.text
    no=app.post('/api/gemma/run',json={'task':'write python CLI','project_id':'beta'})
    assert no.status_code==200 and no.json()['status']=='DRAFT',no.text
    job=yes.json()['job_id']
    journal=app.get('/api/jobs/'+job+'/events')
    assert journal.status_code==200 and journal.json()['events']


def test_child_agent_delete_is_preserved_in_private_merge(tmp_path):
    mem=Memory(tmp_path/'state')
    actor=Principal('a','scope',1,frozenset({'reader','writer'}))
    mem.put_fact(actor,'task',{'goal':'remove deprecated code'})
    base=Workspace(tmp_path/'project')
    base.write_file('deprecated.py','old=1')
    base.write_file('keep.py','stable=1')
    def model(req):
        data=json.loads(req.content)
        first=len(data['contents'])==1
        task=data['contents'][0]['parts'][0]['text']
        if 'Task: main' in task:
            parts=[{'functionCall':{'name':'spawn_workers','args':{'tasks':['Delete the deprecated.py old source']}}}] if first else [{'text':'done'}]
        elif first:
            h=hashlib.sha256(b'old=1').hexdigest()
            parts=[{'functionCall':{'name':'apply_changes','args':{'changes':[
                {'op':'delete','path':'deprecated.py','expected_sha256':h}]}}}]
        else:
            parts=[{'text':'completed deletion'}]
        return httpx.Response(200,json={'candidates':[{'content':{'parts':parts}}]})
    agent=GemmaAgent(GemmaClient(key='mock',transport=httpx.MockTransport(model)),
                     mem,actor,base,'task')
    out=agent.run('main delete',max_steps=3)
    assert out['status']=='DRAFT'
    draft=Path(out['draft_snapshot']['path'])
    assert not (draft/'deprecated.py').exists()
    assert (draft/'keep.py').read_text()=='stable=1'
    assert (base.path/'deprecated.py').exists()  # no leak to accepted/base files
