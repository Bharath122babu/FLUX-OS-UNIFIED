from __future__ import annotations
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from fluxos.kernel import Memory,Principal,Denied,Stale,IntegrityError,projection

@pytest.fixture
def mem(tmp_path):return Memory(tmp_path)

@pytest.fixture
def root():return Principal('owner','p',2,frozenset({'reader','writer','declassifier'}))

@pytest.fixture
def worker():return Principal('worker','p',1,frozenset({'reader','writer'}))

def test_point_read_and_commit(mem,worker):
    mem.put_fact(worker,'x',{'a':2,'b':4})
    o=mem.observe(worker)
    assert o.fact('x','/a')==2
    mem.put_artifact(worker,'r',{'answer':2},o.manifest())
    assert mem.status(worker,'r')=='DECLARED_CURRENT'
    assert mem.artifact(worker,'r')=={'answer':2}

def test_projection_independent_update_preserves(mem,worker):
    mem.put_fact(worker,'x',{'a':2,'b':4})
    o=mem.observe(worker);o.fact('x','/a')
    mem.put_artifact(worker,'r',{'answer':2},o.manifest())
    mem.put_fact(worker,'x',{'a':2,'b':999})
    assert mem.status(worker,'r')=='DECLARED_CURRENT'

def test_relevant_change_stales(mem,worker):
    mem.put_fact(worker,'x',{'a':2})
    o=mem.observe(worker);o.fact('x','/a')
    mem.put_artifact(worker,'r',2,o.manifest())
    mem.put_fact(worker,'x',{'a':3})
    assert mem.status(worker,'r')=='STALE'
    with pytest.raises(Stale):mem.artifact(worker,'r')

def test_transitive_repair(mem,worker):
    mem.put_fact(worker,'x',1)
    o=mem.observe(worker);o.fact('x')
    mem.put_artifact(worker,'a',2,o.manifest())
    o=mem.observe(worker);o.artifact('a')
    mem.put_artifact(worker,'b',3,o.manifest())
    mem.put_fact(worker,'x',2)
    assert mem.status(worker,'a')=='STALE'
    assert mem.status(worker,'b')=='STALE'
    o=mem.observe(worker);o.fact('x')
    mem.put_artifact(worker,'a',4,o.manifest())
    o=mem.observe(worker);o.artifact('a')
    mem.put_artifact(worker,'b',5,o.manifest())
    assert mem.status(worker,'b')=='DECLARED_CURRENT'

def test_reject_stale_commit(mem,worker):
    mem.put_fact(worker,'x',1)
    o=mem.observe(worker);o.fact('x')
    mem.put_fact(worker,'x',2)
    with pytest.raises(Stale):mem.put_artifact(worker,'a',1,o.manifest())
    assert mem.graph('p')['nodes']==[]

def test_old_secret_cannot_be_overwritten(mem,root,worker):
    mem.put_fact(root,'protected','secret',label='secret')
    with pytest.raises(Denied):mem.put_fact(worker,'protected','overwrite',label='internal')
    with pytest.raises(Denied):mem.observe(worker).fact('protected')

def test_cross_scope_cannot_read(mem,worker):
    mem.put_fact(worker,'x',1)
    outsider=Principal('outside','other',2,frozenset({'reader','writer'}))
    with pytest.raises(KeyError):mem.observe(outsider).fact('x')

def test_artifact_downgrade_rejected(mem,root,worker):
    mem.put_artifact(root,'secret_artifact',{'secret':True},[],label='secret')
    with pytest.raises(Denied):mem.put_artifact(worker,'secret_artifact',{},[],label='internal')

def test_output_cannot_downgrade_dep(mem,root):
    actor=Principal('strong','p',2,frozenset({'reader','writer'}))
    mem.put_fact(root,'x',2,label='secret')
    o=mem.observe(actor);o.fact('x')
    with pytest.raises(Denied):mem.put_artifact(actor,'leak',2,o.manifest(),label='public')

def test_integrity_status_verifies_own_blob(mem,worker):
    mem.put_artifact(worker,'a',{'ok':1},[])
    with sqlite3.connect(mem.db) as c:
        c.execute("UPDATE artifacts SET payload='{}' WHERE id='a'")
    assert mem.status(worker,'a')=='INTEGRITY_FAILED'
    with pytest.raises(IntegrityError):mem.artifact(worker,'a')

def test_manifest_max(mem,worker):
    with pytest.raises(Denied):mem.put_artifact(worker,'a',{},[{}]*257)

def test_atomic_cas_consistency(mem,worker):
    mem.put_fact(worker,'x',{'n':1})
    o=mem.observe(worker);o.fact('x','/n')
    mem.put_fact(worker,'x',{'n':2})
    with pytest.raises(Stale):mem.put_artifact(worker,'a',{},o.manifest())
    assert not mem.graph('p')['nodes']

def test_cycle_detected_before_commit(mem,worker):
    mem.put_artifact(worker,'a',1,[])
    o=mem.observe(worker);o.artifact('a')
    mem.put_artifact(worker,'b',2,o.manifest())
    o=mem.observe(worker);o.artifact('b')
    with pytest.raises(Stale):
        mem.put_artifact(worker,'a',3,o.manifest())
    assert mem.status(worker,'a')=='DECLARED_CURRENT'
    assert mem.status(worker,'b')=='DECLARED_CURRENT'

def test_parallel_nonconflicting_writes(mem,worker):
    with ThreadPoolExecutor(max_workers=6) as pool:
        versions=list(pool.map(lambda n:mem.put_fact(worker,f'x-{n}',n),range(30)))
    assert len(versions)==30 and all(v==1 for v in versions)

def test_security_declassification_by_role(mem,root):
    mem.put_fact(root,'x','hidden',label='secret')
    mem.put_fact(root,'x','released',label='public')
    assert mem.observe(root).fact('x')=='released'

def test_invalid_json_pointer(mem,worker):
    mem.put_fact(worker,'x',{'a':1})
    with pytest.raises(ValueError):mem.observe(worker).fact('x','a')
