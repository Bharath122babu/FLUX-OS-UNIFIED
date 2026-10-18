"""Adversarial shared-memory semantics: oracle-based, deterministic, no Gemma claims."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import random
import sqlite3

import pytest

from fluxos.kernel import Memory, Principal, Stale, Denied, digest


@pytest.fixture
def env(tmp_path):
    memory = Memory(tmp_path / 'memory')
    author = Principal('origin', 'p', 2, frozenset({'reader','writer','coordinator'}))
    return memory, author


def editor(name):
    return Principal(name, 'p', 1, frozenset({'reader','writer','agent'}))


def change(path, old_value, new_value):
    return {'path': path, 'expected_hash': digest(old_value), 'value': new_value}


def test_strict_agent_blind_overwrite_rejected(env):
    m,root = env
    m.put_fact(root,'state',{'x':0})
    with pytest.raises(Stale):
        m.put_fact(editor('agent'), 'state', {'x':99})
    assert m.fact_head(root,'state')['value']=={'x':0}


def test_version_cas_detects_race(env):
    m,root=env
    assert m.put_fact(root,'state',{'value':1})==1
    e=editor('agent')
    assert m.put_fact(e,'state',{'value':2},expected_version=1)==2
    with pytest.raises(Stale):
        m.put_fact(e,'state',{'value':3},expected_version=1)
    assert m.fact_head(root,'state')['value']=={'value':2}


def test_agent_creation_requires_expected_absent_version(env):
    m,_=env
    with pytest.raises(Stale):m.put_fact(editor('new'),'new',1)
    assert m.put_fact(editor('new'),'new',1,expected_version=0)==1


def test_20_agents_disjoint_fields_preserved_without_lost_update(env):
    m,root=env
    state={f'a{i}':0 for i in range(20)}
    m.put_fact(root,'shared',state)
    # Every actor observes BEFORE any actor writes; even stale base versions
    # should not lose independent path edits when their field witness is valid.
    inputs=[]
    for i in range(20):
        a=editor(f'agent{i}')
        obs=m.observe(a)
        assert obs.fact('shared',f'/a{i}')==0
        inputs.append((a,obs.manifest(),i))
    def commit(item):
        a,manifest,i=item
        return m.patch_fact(a,'shared',[change(f'/a{i}',0,i+1)],read_manifest=manifest)
    with ThreadPoolExecutor(max_workers=12) as pool:
        versions=list(pool.map(commit,inputs))
    assert sorted(versions)==list(range(2,22))
    assert m.fact_head(root,'shared')['value']=={f'a{i}':i+1 for i in range(20)}


def test_same_field_conflict_fails_without_overwrite(env):
    m,root=env
    m.put_fact(root,'s',{'x':0})
    assert m.patch_fact(editor('a'),'s',[change('/x',0,1)])==2
    with pytest.raises(Stale):
        m.patch_fact(editor('b'),'s',[change('/x',0,2)])
    assert m.fact_head(root,'s')['value']=={'x':1}


def test_opaque_whole_document_dependency_blocks_disjoint_merge(env):
    m,root=env
    m.put_fact(root,'s',{'x':0,'y':0})
    obs=m.observe(editor('b'))
    obs.fact('s')  # model depended on the whole object, not just y
    m.patch_fact(editor('a'),'s',[change('/x',0,1)])
    with pytest.raises(Stale):
        m.patch_fact(editor('b'),'s',[change('/y',0,2)],read_manifest=obs.manifest())
    assert m.fact_head(root,'s')['value']=={'x':1,'y':0}


def test_fine_grained_observer_survives_unrelated_writer(env):
    m,root=env
    m.put_fact(root,'s',{'x':0,'y':0})
    obs=m.observe(editor('b'))
    obs.fact('s','/y')
    m.patch_fact(editor('a'),'s',[change('/x',0,1)])
    assert m.patch_fact(editor('b'),'s',[change('/y',0,2)],read_manifest=obs.manifest())==3
    assert m.fact_head(root,'s')['value']=={'x':1,'y':2}


def test_patch_atomicity_if_one_preimage_invalid(env):
    m,root=env
    m.put_fact(root,'s',{'x':0,'y':0})
    with pytest.raises(Stale):
        m.patch_fact(editor('b'),'s',[change('/x',0,1),change('/y',99,1)])
    assert m.fact_head(root,'s')['version']==1
    assert m.fact_head(root,'s')['value']=={'x':0,'y':0}


def test_patch_overlap_forbidden(env):
    m,root=env
    m.put_fact(root,'s',{'x':{'y':1}})
    with pytest.raises(ValueError):
        m.patch_fact(editor('b'),'s',[
            change('/x',{'y':1},{'y':2}),change('/x/y',1,4)])


def test_patch_missing_field_cas(env):
    m,root=env
    m.put_fact(root,'s',{})
    new={'path':'/new','expected_hash':None,'value':3}
    m.patch_fact(editor('a'),'s',[new])
    with pytest.raises(Stale): m.patch_fact(editor('b'),'s',[new])
    assert m.fact_head(root,'s')['value']=={'new':3}


def test_security_patch_respects_classification(env):
    m,root=env
    m.put_fact(root,'secret',{'x':1},label='secret')
    with pytest.raises(Denied):m.patch_fact(editor('low'),'secret',[change('/x',1,2)])
    assert m.fact_head(root,'secret')['value']['x']==1


def test_patch_preserves_original_authority_but_logs_actual_editor(env):
    m,root=env
    m.put_fact(root,'s',{'x':0,'y':0})
    witness=m.observe(editor('reader'))
    witness.fact('s','/x')
    m.patch_fact(editor('alice'),'s',[change('/y',0,1)])
    assert m.validate_manifest(editor('reader'),witness.manifest())
    events=m.timeline()
    assert any(e.get('kind')=='fact.patched' and e.get('editor')=='alice' for e in events)


def test_claim_disagreement_flagged_without_pretending_truth(env):
    m,_=env
    a=editor('a');b=editor('b')
    one=m.record_claim(a,'release','safe',True,'test-suite-a')
    two=m.record_claim(b,'release','safe',False,'test-suite-b')
    assert one['status']=='UNCONTESTED'
    assert two['status']=='DISPUTED'
    out=m.claims(a,'release','safe')
    assert out['status']=='DISPUTED'
    assert {c['value'] for c in out['claims']}=={True,False}
    assert len({c['id'] for c in out['claims']})==2


def test_claims_with_same_value_remain_evidence_distinct(env):
    m,_=env
    a=editor('a')
    m.record_claim(a,'build','status','passing','test1')
    m.record_claim(a,'build','status','passing','test2')
    out=m.claims(a,'build','status')
    assert out['status']=='UNCONTESTED' and len(out['claims'])==2


def test_secret_claim_does_not_leak_conflict_through_status(env):
    m,root=env
    m.record_claim(root,'s','p','secret1','private-test',label='secret')
    m.record_claim(root,'s','p','secret2','private-test2',label='secret')
    out=m.claims(editor('low'),'s','p')
    assert out=={'status':'UNAVAILABLE','claims':[]}


def test_project_history_filters_secret_artifact_metadata(env,tmp_path):
    # Existing accepted fixture, then change its label in the database to
    # model a formerly published secret revision. Authoritative object remains.
    from fluxos.agent import Workspace
    from fluxos.gateway import UnifiedGate
    m,root=env
    j=m.create_job('p','origin','build',actor=root)
    gen=m.set_job(j,'RUNNING',actor=root)
    w=Workspace(tmp_path/'candidate');w.write_file('app.py','print(5)')
    gate=UnifiedGate(m,root)
    outcome=gate.publish(candidate=w,baseline=None,base_manifest={},observation=m.observe(root),
        developer={},acceptance={},model='mock',calls=1,output_id='result:'+j,
        job_id=j,generation=gen,project_id='vault',base_revision=0,
        trusted_acceptance=lambda sealed:{'status':'PASS','test_count':1,'trust_boundary':'blackbox',
            'contract_hash':'trusted-operator','candidate_manifest_hash':sealed.manifest_digest()})
    assert outcome.decision=='COMMIT'
    with sqlite3.connect(m.db) as conn:
        conn.execute("UPDATE artifacts SET level=2 WHERE scope='p' AND id=?",('result:'+j,))
    assert len(m.project_history(root,'vault'))==1
    assert m.project_history(editor('low'),'vault')==[]


def test_recovery_fences_off_in_flight_job(env):
    m,root=env
    j=m.create_job('p','origin','build',actor=root)
    gen=m.set_job(j,'RUNNING',actor=root)
    assert gen==1
    # Coordinator exclusive restart reconciliation, no optimistic replay.
    recovered=Memory(m.home)
    assert recovered.reconcile_interrupted_jobs('p')==[j]
    assert recovered.get_job(j)['state']=='INTERRUPTED'
    assert recovered.get_job(j)['generation']==2
    with pytest.raises(Stale):
        recovered.put_artifact(root,'result:'+j,{'anything':True},[],job_id=j,job_generation=gen)
    assert recovered.reconcile_interrupted_jobs('p')==[]


def test_generated_conflict_properties_multiple_seeds(env):
    m,root=env
    rng=random.Random(87126)
    for seed in range(40):
        n=rng.randrange(4,24)
        key=f'random-{seed}'
        state={f'k{i}':0 for i in range(n)}
        m.put_fact(root,key,state)
        selected=list(range(n));rng.shuffle(selected)
        for i in selected:
            x=rng.randrange(1,100000)
            m.patch_fact(editor(f'random-{i}'),key,[change(f'/k{i}',0,x)])
            state[f'k{i}']=x
        assert m.fact_head(root,key)['value']==state


def test_low_clearance_claim_write_does_not_reveal_secret_dispute(env):
    m,root=env
    m.record_claim(root,'s','p','classified','root-evidence',label='secret')
    response=m.record_claim(editor('low'),'s','p','different','public-evidence')
    assert response['status']=='UNCONTESTED'
    visible=m.claims(editor('low'),'s','p')
    assert visible['status']=='UNCONTESTED'
    assert len(visible['claims'])==1
    assert m.claims(root,'s','p')['status']=='DISPUTED'


def test_ordinary_writer_requires_cas_even_if_not_tagged_agent(env):
    m,root=env
    plain=Principal('plain','p',1,frozenset({'reader','writer'}))
    with pytest.raises(Stale):m.put_fact(plain,'new',0)
    assert m.put_fact(plain,'new',0,expected_version=0)==1
    with pytest.raises(Stale):m.put_fact(plain,'new',1)
    assert m.put_fact(plain,'new',1,expected_version=1)==2


def test_negative_json_field_witness_invalidates_on_addition(env):
    m,root=env
    m.put_fact(root,'state',{'known':1})
    watcher=editor('reader')
    observed=m.observe(watcher)
    assert observed.absent_fact('state','/unseen')
    assert m.validate_manifest(watcher,observed.manifest())
    assert m.patch_fact(editor('writer'),'state',[
        {'path':'/unseen','expected_hash':None,'value':'new'}])==2
    with pytest.raises(Stale):m.validate_manifest(watcher,observed.manifest())

def test_negative_field_absence_survives_unrelated_changes(env):
    m,root=env
    m.put_fact(root,'state',{'known':1})
    watcher=editor('reader')
    observed=m.observe(watcher)
    observed.absent_fact('state','/unseen')
    m.patch_fact(editor('writer'),'state',[change('/known',1,2)])
    assert m.validate_manifest(watcher,observed.manifest())

def test_missing_field_patch_with_valid_negative_witness(env):
    m,root=env
    m.put_fact(root,'state',{'known':1})
    writer=editor('writer')
    obs=m.observe(writer);obs.absent_fact('state','/new')
    m.patch_fact(editor('other'),'state',[change('/known',1,2)])
    m.patch_fact(writer,'state',[{'path':'/new','expected_hash':None,'value':4}],read_manifest=obs.manifest())
    assert m.fact_head(root,'state')['value']=={'known':2,'new':4}
