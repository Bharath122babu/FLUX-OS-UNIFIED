"""Gate-zero regression tests for the unified FLUX publication mechanism.

No network or live model calls. Tests use the real code paths with mocked LLM or
Docker boundary; the local subprocess test executes a trusted launcher directly.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from fluxos.kernel import Memory,Principal,Denied,Stale,IntegrityError
from fluxos.agent import GemmaAgent,GemmaClient,Workspace,TRUSTED_TEST_LAUNCHER
from fluxos.gateway import UnifiedGate
from fluxos.api import create_app

@pytest.fixture
def core(tmp_path):
    mem=Memory(tmp_path/'state')
    actor=Principal('worker','project',1,frozenset({'reader','writer','coordinator'}))
    mem.put_fact(actor,'requirement',{'task':'update code'})
    return mem,actor

def script_model(tools):
    """A fully mocked Gemma tool-calling trace; not a live model benchmark."""
    calls=iter(tools)
    def handler(request):
        try: action=next(calls)
        except StopIteration: action=None
        parts=([{'functionCall':{'name':action[0],'args':action[1]}}]
               if action else [{'text':'Done; no claims of verification.'}])
        return httpx.Response(200,json={'candidates':[{'content':{'parts':parts}}]})
    return GemmaClient(key='mock',transport=httpx.MockTransport(handler))

def test_file_hash_source_is_provenanced_at_content_projection(core,tmp_path):
    m,a=core
    base=Workspace(tmp_path/'repo')
    base.write_file('api.py','ROUTE = "v1"\n')
    base.write_file('styles.css','h1{}')
    agent=GemmaAgent(script_model([('read_file',{'path':'api.py'}),('write_file',{'path':'frontend.py','content':'v=1'})]),m,a,base,'requirement')
    result=agent.run('make frontend',max_steps=3)
    assert result['status']=='DRAFT'
    marks=agent.obs.manifest()
    assert {'/names','/hashes/api.py'}.issubset({d['pointer'] for d in marks})
    assert '/hashes/styles.css' not in {d['pointer'] for d in marks}
    assert result['draft_snapshot'] is not None
    m.validate_manifest(a,marks)

def test_unrelated_file_content_change_preserves_precise_file_witness(core,tmp_path):
    m,a=core
    base=Workspace(tmp_path/'repo')
    base.write_file('api.py','x=1')
    base.write_file('unrelated.py','z=1')
    agent=GemmaAgent(script_model([('read_file',{'path':'api.py'})]),m,a,base,'requirement')
    agent.run('inspect source',max_steps=2)
    marks=agent.obs.manifest()
    base.write_file('unrelated.py','z=2')
    m.register_source_tree(a,agent.source_id,base.file_manifest())
    assert m.validate_manifest(a,marks)
    base.write_file('api.py','x=2')
    m.register_source_tree(a,agent.source_id,base.file_manifest())
    with pytest.raises(Stale):m.validate_manifest(a,marks)

def test_missing_file_negative_witness_invalidates_when_path_appears(core,tmp_path):
    m,a=core
    base=Workspace(tmp_path/'repo')
    ag=GemmaAgent(script_model([('read_file',{'path':'unknown.py'})]),m,a,base,'requirement')
    ag.run('look for missing input',max_steps=2)
    marks=ag.obs.manifest()
    assert '/names' in {d['pointer'] for d in marks}
    base.write_file('unknown.py','x=1')
    m.register_source_tree(a,ag.source_id,base.file_manifest())
    with pytest.raises(Stale):m.validate_manifest(a,marks)

def test_byte_changed_outside_repo_registry_is_refused(core,tmp_path):
    m,a=core
    base=Workspace(tmp_path/'repo');base.write_file('api.py','value=1')
    client=script_model([('read_file',{'path':'api.py'}),('write_file',{'path':'out.py','content':'ok=1'})])
    agent=GemmaAgent(client,m,a,base,'requirement')
    original=agent._tool
    count={'n':0}
    def changed(name,args):
        count['n']+=1
        val=original(name,args)
        if count['n']==1:
            base.write_file('api.py','value=99')
        return val
    agent._tool=changed
    result=agent.run('build module',max_steps=3)
    assert result['status']=='STALE_REJECTED'
    assert result['draft_snapshot'] is None

def test_second_worker_cannot_overwrite_artifact(core):
    m,a=core
    b=Principal('other','project',1,frozenset({'reader','writer','coordinator'}))
    m.put_artifact(a,'shared',{'by':'a'},[])
    with pytest.raises(Denied):m.put_artifact(b,'shared',{'by':'b'},[])
    publisher=Principal('reviewer','project',1,frozenset({'reader','writer','publisher'}))
    assert m.put_artifact(publisher,'shared',{'by':'reviewer'},[])==2

def test_agent_result_requires_fenced_job(core):
    m,a=core
    with pytest.raises(Denied):m.put_artifact(a,'result:any',{'independent_acceptance':False},[])
    jid=m.create_job(a.scope,a.name,'goal',actor=a)
    epoch=m.set_job(jid,'RUNNING',actor=a)
    assert m.put_artifact(a,'result:any',{'independent_acceptance':False},[],job_id=jid,job_generation=epoch)==1
    m.set_job(jid,'FAILED',actor=a)
    with pytest.raises(Stale):m.put_artifact(a,'result:any',{},[],job_id=jid,job_generation=epoch)

def test_graph_handles_corrupt_published_snapshot(core,tmp_path):
    m,a=core
    src=tmp_path/'.fluxos-published'/'snap';src.mkdir(parents=True)
    (src/'good.py').write_text('good=1')
    jid=m.create_job(a.scope,a.name,'goal',actor=a);epoch=m.set_job(jid,'RUNNING',actor=a)
    m.put_artifact(a,'result:'+jid,{'snapshot':str(src),'file_hashes':Workspace(src).file_manifest(),
                   'independent_acceptance':True},[],job_id=jid,job_generation=epoch)
    (src/'good.py').write_text('tampered')
    assert m.status(a,'result:'+jid)=='INTEGRITY_FAILED'
    assert m.graph('project')['nodes'][0]['status']=='INTEGRITY_FAILED'

def test_old_fake_unittest_stdout_no_longer_passes(core,tmp_path,monkeypatch):
    import fluxos.agent as agent
    monkeypatch.setattr(agent.shutil,'which',lambda _: '/usr/bin/docker')
    def fake(*a,**kw):
        return SimpleNamespace(returncode=0,stdout='Ran 1 test in 0.001s\nOK\n',stderr='')
    monkeypatch.setattr(agent.subprocess,'run',fake)
    result=Workspace(tmp_path/'code').run_tests()
    assert result['status']!='PASS'

def test_trusted_launcher_isolation_and_mount_options(core,tmp_path,monkeypatch):
    import fluxos.agent as agent
    w=Workspace(tmp_path/'code');w.write_file('unittest.py','print("MALICIOUS")')
    suite=tmp_path/'acceptance';suite.mkdir();(suite/'test_hello.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_one(self): self.assertEqual(1+1,2)\n')
    seen=[]
    monkeypatch.setattr(agent.shutil,'which',lambda _: '/usr/bin/docker')
    def mock(cmd,**kw):
        seen.append(cmd)
        return SimpleNamespace(returncode=0,stdout='FLUX_TEST_REPORT:{"loaded":1,"run":1,"errors":0,"failures":0,"skipped":0,"passed":true}\n',stderr='Ran 1 test in 0.001s\nOK\n')
    monkeypatch.setattr(agent.subprocess,'run',mock)
    assert w.run_tests(suite)['status']=='PASS'
    cmd=seen[0]
    assert 'python' in cmd and '-I' in cmd and '/runner/launcher.py' in cmd
    assert '--network' in cmd and 'none' in cmd
    assert '--read-only' in cmd
    assert 'PYTHONPATH=/work' not in cmd
    assert any('/acceptance,readonly' in c for c in cmd)

def test_trusted_runner_unittest_shadow_local_subprocess(core,tmp_path):
    """Run the launcher with isolated Python, using physical files and no Docker.

    This verifies stdlib module shadowing defense but not Docker security.
    """
    work=tmp_path/'work';work.mkdir()
    (work/'unittest.py').write_text('print("FAKE UNITTTEST")\n')
    (work/'sitecustomize.py').write_text('print("FAKE SITECUSTOMIZE")\n')
    (work/'answer.py').write_text('VALUE=7\n')
    acc=tmp_path/'acceptance';acc.mkdir()
    (acc/'test_answer.py').write_text('import unittest\nimport answer\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(answer.VALUE, 7)\n')
    launcher=tmp_path/'runner';launcher.mkdir()
    script=launcher/'launcher.py'
    script.write_text(TRUSTED_TEST_LAUNCHER.replace("'/work'",repr(str(work))))
    p=subprocess.run([sys.executable,'-I','-B',str(script),str(acc)],
                     cwd=work,capture_output=True,text=True,timeout=10)
    assert p.returncode==0,p.stdout+p.stderr
    assert 'FAKE UNITTTEST' not in p.stdout
    assert 'FAKE SITECUSTOMIZE' not in p.stdout
    assert '"run": 1' in p.stdout

def test_dev_suite_failure_disqualifies_acceptance_success(core,tmp_path,monkeypatch):
    import fluxos.agent as agent
    mem,actor=core
    suite=tmp_path/'acceptance';suite.mkdir();(suite/'test_check.py').write_text('pass')
    def fake_run(self,acceptance_dir=None):
        return ({'status':'PASS','test_count':2} if acceptance_dir is not None
                else {'status':'FAIL','test_count':1})
    monkeypatch.setattr(agent.Workspace,'run_tests',fake_run)
    a=GemmaAgent(script_model([('write_file',{'path':'hi.py','content':'x=1'})]),mem,actor,
                  Workspace(tmp_path/'repo'),'requirement',acceptance_dir=suite)
    out=a.run('make a module',max_steps=3)
    assert out['status']=='DRAFT'
    assert out['published_snapshot'] is None

def test_api_rejects_cross_port_local_origin(tmp_path):
    app=TestClient(create_app(tmp_path/'home'))
    assert app.post('/api/demo/reset',headers={'Origin':'http://localhost:9999'}).status_code==403
    assert app.post('/api/demo/reset',headers={'Origin':'http://testserver'}).status_code==200
    assert app.post('/api/demo/reset',headers={'Host':'attacker.invalid'}).status_code==403

def test_manifest_tree_change_only_affects_read_components(core,tmp_path):
    m,a=core
    ws=Workspace(tmp_path/'repo')
    ws.write_file('api.py','v=1')
    ws.write_file('styles.css','color=1')
    name='repo:test:tree'
    m.register_source_tree(a,name,ws.file_manifest())
    obs=m.observe(a);obs.fact(name,'/names');obs.fact(name,'/hashes/api.py')
    m.put_artifact(a,'frontend',{'render':1},obs.manifest())
    styles=m.observe(a);styles.fact(name,'/hashes/styles.css')
    m.put_artifact(a,'styles',{'render':2},styles.manifest())
    ws.write_file('api.py','v=2');m.register_source_tree(a,name,ws.file_manifest())
    assert m.status(a,'frontend')=='STALE'
    assert m.status(a,'styles')=='DECLARED_CURRENT'

def test_legacy_deterministic_demo_still_works(tmp_path):
    from fluxos.demo import bootstrap, mutate, repair
    home=tmp_path/'demo'
    b=bootstrap(home);d=mutate(home,'student_id');r=repair(home)
    assert b['statuses']['styles']=='DECLARED_CURRENT'
    assert d['statuses']['frontend']=='STALE'
    assert r['statuses']['frontend']=='DECLARED_CURRENT'

def test_unified_demo_causal_contract_recovery(tmp_path):
    from fluxos.unified_demo import run
    result=run(tmp_path/'fresh')
    assert result['before']=={'frontend':'DECLARED_CURRENT','styles':'DECLARED_CURRENT'}
    assert result['after_contract_change']=={'frontend':'STALE','styles':'DECLARED_CURRENT'}
    assert result['after_repair']=={'frontend':'DECLARED_CURRENT','styles':'DECLARED_CURRENT'}
    assert result['model_calls']==0
