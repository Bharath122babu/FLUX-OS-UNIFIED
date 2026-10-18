"""Regression tests for the October 17 adversarial audit and nearby boundary cases."""
from pathlib import Path
import json
import httpx
import pytest
from fluxos.kernel import Memory,Principal,Denied,Stale,IntegrityError
from fluxos.agent import Workspace,GemmaAgent,GemmaClient

@pytest.fixture
def setup(tmp_path):
    m=Memory(tmp_path/'db')
    admin=Principal('admin','team',2,frozenset({'reader','writer','declassifier'}))
    dev=Principal('dev','team',1,frozenset({'reader','writer'}))
    return m,admin,dev

def test_classification_escalation_blocks_same_value_derived_read(setup):
    m,admin,dev=setup
    m.put_fact(dev,'scope',{'key':'same'},'internal')
    obs=m.observe(dev);obs.fact('scope')
    m.put_artifact(dev,'derived',{'key':'same'},obs.manifest())
    m.put_fact(admin,'scope',{'key':'same'},'secret')
    assert m.status(dev,'derived')=='STALE'
    with pytest.raises(Stale):m.artifact(dev,'derived')
    with pytest.raises(Denied):m.observe(dev).fact('scope')
    assert m.graph('team')['nodes'][0]['status']=='STALE'

def test_author_change_same_value_invalidates(setup):
    m,admin,dev=setup
    m.put_fact(dev,'x',1)
    o=m.observe(dev);o.fact('x')
    m.put_artifact(dev,'dependent',{},o.manifest())
    m.put_fact(admin,'x',1)
    assert m.status(dev,'dependent')=='STALE'

def test_fact_projection_equivalence_still_reuses(setup):
    m,_,dev=setup
    m.put_fact(dev,'x',{'keep':7,'change':1})
    o=m.observe(dev);o.fact('x','/keep')
    m.put_artifact(dev,'dependent',{'keep':7},o.manifest())
    m.put_fact(dev,'x',{'keep':7,'change':999})
    assert m.status(dev,'dependent')=='DECLARED_CURRENT'

def test_transitive_graph_status_matches_effective_when_hashes_coincide(setup):
    m,_,dev=setup
    m.put_fact(dev,'req',0)
    o=m.observe(dev);o.fact('req');m.put_artifact(dev,'a',{'v':1},o.manifest())
    o=m.observe(dev);o.artifact('a');m.put_artifact(dev,'b',{'v':2},o.manifest())
    o=m.observe(dev);o.artifact('b');m.put_artifact(dev,'c',{'v':3},o.manifest())
    m.put_fact(dev,'req',1)
    # repair a to payload exactly equal to previously stored b payload
    o=m.observe(dev);o.fact('req');m.put_artifact(dev,'a',{'v':2},o.manifest())
    for name in ('b','c'):
        assert m.status(dev,name)=='STALE'
        assert next(n for n in m.graph('team')['nodes'] if n['id']==name)['status']=='STALE'

def test_diamond_graph_validation_no_repeated_explosion(setup):
    m,_,dev=setup
    m.put_artifact(dev,'base',{'id':1},[])
    for ix in range(9):
        a,b=f'L{ix}',f'R{ix}'
        sources=['base'] if ix==0 else [f'L{ix-1}',f'R{ix-1}']
        for target in (a,b):
            o=m.observe(dev)
            for s in sources:o.artifact(s)
            m.put_artifact(dev,target,{'layer':ix},o.manifest())
    assert m.status(dev,'L8')=='DECLARED_CURRENT'
    m.put_artifact(dev,'base',{'id':2},[])
    assert m.status(dev,'L8')=='STALE'

def test_pre_migration_authority_witness_is_not_trusted(setup):
    m,_,dev=setup
    m.put_fact(dev,'x',1)
    o=m.observe(dev);o.fact('x')
    witness=o.manifest()
    del witness[0]['expected_authority']
    with pytest.raises(Stale):m.put_artifact(dev,'should_fail',{},witness)

def test_job_transition_cas_and_owner_fence(setup):
    m,admin,dev=setup
    job=m.create_job('team','dev','task',actor=dev)
    epoch=m.set_job(job,'RUNNING',actor=dev,expected_state='PENDING',expected_generation=0)
    assert epoch==1
    with pytest.raises(Stale):m.set_job(job,'RUNNING',actor=dev,expected_generation=0)
    with pytest.raises(Denied):m.set_job(job,'COMPLETED',actor=admin)
    with pytest.raises(Stale):m.put_artifact(dev,'result',{},[],job_id=job,job_generation=0)
    m.put_artifact(dev,'result',{},[],job_id=job,job_generation=1)
    m.set_job(job,'CANCELLED',actor=dev,expected_generation=1)
    with pytest.raises(Stale):m.put_artifact(dev,'result',{},[],job_id=job,job_generation=1)
    with pytest.raises(Stale):m.set_job(job,'COMPLETED',actor=dev)

def _client_for_mock(response, on_request=None):
    counter={'n':0}
    def handle(request):
        counter['n']+=1
        if on_request:on_request(counter['n'])
        if counter['n']==1:
            parts=[{'functionCall':{'name':'write_file','args':{'path':'out.py','content':'result=1'}}}]
        else:parts=[{'text':'complete'}]
        return httpx.Response(200,json={'candidates':[{'content':{'parts':parts}}]})
    return GemmaClient(key='mock',transport=httpx.MockTransport(handle))

def test_rejected_candidate_does_not_leak_any_file(setup,tmp_path):
    m,_,dev=setup
    m.put_fact(dev,'task',{'goal':'old'})
    base=tmp_path/'code'
    def mutate(n):
        if n==1:m.put_fact(dev,'task',{'goal':'new'})
    a=GemmaAgent(_client_for_mock(None,mutate),m,dev,Workspace(base),'task')
    out=a.run('build code')
    assert out['status']=='STALE_REJECTED'
    assert out['published_snapshot'] is None
    assert list(base.iterdir())==[]
    assert list(tmp_path.glob('.fluxos-published/*'))==[]

def test_unverified_draft_is_hash_identified_and_base_untouched(setup,tmp_path):
    m,_,dev=setup
    m.put_fact(dev,'task',{'goal':'write code'})
    base=tmp_path/'code'
    out=GemmaAgent(_client_for_mock(None),m,dev,Workspace(base),'task').run('build code')
    assert out['status']=='DRAFT'
    assert out['published_snapshot'] is None
    snap=out['draft_snapshot']
    assert snap is not None and (Path(snap['path'])/'out.py').read_text()=='result=1'
    assert not (base/'out.py').exists()
    with pytest.raises(KeyError):m.artifact(dev,'result:latest')

def test_byte_exact_snapshot_larger_than_model_read_limit(tmp_path):
    root=Workspace(tmp_path/'src')
    text='0123456789'*1200
    root.write_file('long.py',text)
    dest=Workspace(tmp_path/'child')
    assert root.read_file('long.py')==text[:8192]
    assert root.snapshot_to(dest)==dest.file_manifest()
    assert (dest.path/'long.py').read_text()==text

def test_workspace_rejects_symlink_in_snapshot(tmp_path,create_symlink):
    source=Workspace(tmp_path/'src')
    source.write_file('good.py','x=1')
    create_symlink(source.path/'symlink.py',source.path/'good.py')
    with pytest.raises(ValueError):source.snapshot_to(Workspace(tmp_path/'other'))

def test_acceptance_suite_isolated_and_required_for_publication(setup,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import fluxos.agent as ag
    m,_,dev=setup
    m.put_fact(dev,'task',{'goal':'write code'})
    suite=tmp_path/'acceptance';suite.mkdir()
    (suite/'test_requirement.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_output(self): pass\n')
    calls=[]
    monkeypatch.setattr(ag.shutil,'which',lambda _: '/usr/bin/docker')
    def fake_run(cmd,**kwargs):
        calls.append(cmd)
        assert '--network' in cmd and 'none' in cmd
        return SimpleNamespace(returncode=0,stdout='FLUX_TEST_REPORT:{"loaded":1,"run":1,"errors":0,"failures":0,"skipped":0,"passed":true}\n',stderr='Ran 1 test in 0.001s\n\nOK\n')
    monkeypatch.setattr(ag.subprocess,'run',fake_run)
    agent=GemmaAgent(_client_for_mock(None),m,dev,Workspace(tmp_path/'code'),'task',acceptance_dir=suite)
    output=agent.run('build code')
    assert output['status']=='DRAFT'
    assert output['published_snapshot'] is None
    assert output['draft_snapshot'] is not None
    # A legacy unittest PASS cannot authorize a release: the candidate shares
    # interpreter control with the unittest framework.
    with pytest.raises(KeyError):m.artifact(dev,'result:latest')
    assert any('/acceptance' in str(arg) for cmd in calls for arg in cmd) is False

def test_empty_discovered_tests_are_not_pass(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import fluxos.agent as ag
    monkeypatch.setattr(ag.shutil,'which',lambda _:'/usr/bin/docker')
    monkeypatch.setattr(ag.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout='',stderr='Ran 0 tests in 0.001s\nOK'))
    result=Workspace(tmp_path).run_tests()
    assert result['status']=='NO_TESTS'
    assert result['test_count']==0

def test_cancelled_job_cannot_publish_even_with_acceptance(setup,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import fluxos.agent as ag
    m,_,dev=setup
    job=m.create_job('team','dev','build',actor=dev)
    m.put_fact(dev,'task',{'goal':'build'})
    m.set_job(job,'RUNNING',actor=dev)
    suite=tmp_path/'acceptance';suite.mkdir();(suite/'cases.json').write_text('''{"entry":"out.py","cases":[{"stdin":"","stdout":""}]}''')
    monkeypatch.setattr(ag.shutil,'which',lambda _: '/usr/bin/docker')
    monkeypatch.setattr(ag.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout='FLUX_TEST_REPORT:{"loaded":1,"run":1,"errors":0,"failures":0,"skipped":0,"passed":true}\n',stderr='Ran 1 test in 0.001s\nOK'))
    monkeypatch.setattr(ag.Workspace,'run_blackbox',lambda self, *_:{'status':'PASS','test_count':1,
        'trust_boundary':'blackbox','contract_hash':'test-contract',
        'candidate_manifest_hash':self.manifest_digest()})
    calls={'n':0}
    def cancel(_):
        calls['n']+=1
        if calls['n']==1:m.set_job(job,'CANCELLED',actor=dev)
    model=_client_for_mock(None,cancel)
    out=GemmaAgent(model,m,dev,Workspace(tmp_path/'code'),'task',root_job=job,acceptance_dir=suite,project_id='campus',base_revision=0).run('build')
    assert out['status']=='STALE_REJECTED'
    assert out['published_snapshot'] is None
    with pytest.raises(KeyError):m.artifact(dev,'result:'+job)

def test_parallel_delegation_preserves_large_unedited_source(setup,tmp_path):
    m,_,dev=setup
    m.put_fact(dev,'task',{'goal':'parallel'})
    w=Workspace(tmp_path/'code')
    initial='hello world\n'*1100
    w.write_file('big.py',initial)
    def mock(req):
        body=json.loads(req.content)
        txt=body['contents'][0]['parts'][0]['text']
        first=len(body['contents'])==1
        if txt.startswith('Task: parent'):
            parts=[{'functionCall':{'name':'spawn_workers','args':{'tasks':['Independent alpha implementation']}}}] if first else [{'text':'done'}]
        else:
            parts=[{'functionCall':{'name':'write_file','args':{'path':'alpha.py','content':'x=1'}}}] if first else [{'text':'done'}]
        return httpx.Response(200,json={'candidates':[{'content':{'parts':parts}}]})
    client=GemmaClient(key='mock',transport=httpx.MockTransport(mock))
    out=GemmaAgent(client,m,dev,w,'task').run('parent',max_steps=3)
    assert out['status']=='DRAFT'
    assert (w.path/'big.py').read_text()==initial
    draft=Path(out['draft_snapshot']['path'])
    assert (draft/'big.py').read_text()==initial
    assert (draft/'alpha.py').read_text()=='x=1'

def test_local_api_rejects_untrusted_origin(tmp_path):
    from fastapi.testclient import TestClient
    from fluxos.api import create_app
    c=TestClient(create_app(tmp_path/'home'))
    assert c.get('/api/health',headers={'Origin':'https://evil.example'}).status_code==403
    assert c.get('/api/health',headers={'Origin':'http://testserver'}).status_code==200


def test_old_format_database_migrates_deps_and_jobs(tmp_path):
    import sqlite3
    dbdir=tmp_path/'state';dbdir.mkdir()
    with sqlite3.connect(dbdir/'state.sqlite3') as c:
        c.execute('CREATE TABLE deps(scope TEXT,child_id TEXT,child_version INTEGER,kind TEXT,source TEXT,pointer TEXT,expected_hash TEXT,expected_version INTEGER)')
        c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,scope TEXT,task TEXT,state TEXT,parent_id TEXT,owner TEXT,created REAL)')
    m=Memory(dbdir)
    with sqlite3.connect(m.db) as c:
        d={r[1] for r in c.execute('PRAGMA table_info(deps)')}
        j={r[1] for r in c.execute('PRAGMA table_info(jobs)')}
    assert 'expected_authority' in d and 'generation' in j

def test_observation_cannot_launder_changed_source_by_rereading(setup):
    m,_,dev=setup
    m.put_fact(dev,'task',{'goal':'old'})
    obs=m.observe(dev)
    assert obs.fact('task')['goal']=='old'
    m.put_fact(dev,'task',{'goal':'new'})
    with pytest.raises(Stale):obs.fact('task')
    with pytest.raises(Stale):m.put_artifact(dev,'result',{},obs.manifest())

def test_observation_cannot_launder_replaced_artifact(setup):
    m,_,dev=setup
    m.put_artifact(dev,'a',{'v':1},[])
    obs=m.observe(dev)
    obs.artifact('a')
    m.put_artifact(dev,'a',{'v':2},[])
    with pytest.raises(Stale):obs.artifact('a')
