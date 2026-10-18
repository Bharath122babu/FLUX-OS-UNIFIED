"""Finalization regressions: atomic registration, bounded workspace, and release boundary.

No claim of live Docker/Gemma testing: those integrations remain external gates.
"""
from concurrent.futures import ThreadPoolExecutor
import importlib
from types import SimpleNamespace
import pytest
from fluxos.agent import Workspace
from fluxos.gateway import UnifiedGate
from fluxos.kernel import Memory, Principal

@pytest.fixture
def runtime(tmp_path):
    mem = Memory(tmp_path/'kernel')
    actor = Principal('worker', 'scope', 1, frozenset({'reader', 'writer'}))
    return mem, actor


def test_concurrent_identical_source_registration_is_one_version(runtime):
    mem, actor = runtime
    manifest = {'api.py': '1'*64, 'style.css': '2'*64}
    with ThreadPoolExecutor(max_workers=8) as pool:
        changed = list(pool.map(lambda _: mem.register_source_tree(actor, 'repo:stable:tree', manifest), range(32)))
    assert changed.count(True) == 1
    with mem._conn() as c:
        row = c.execute("SELECT version FROM heads WHERE scope=? AND key=?", ('scope', 'repo:stable:tree')).fetchone()
    assert row['version'] == 1


def test_changed_source_registration_invalidates_witness(runtime):
    mem, actor = runtime
    assert mem.register_source_tree(actor, 'repo:stable:tree', {'api.py':'1'*64})
    obs = mem.observe(actor)
    obs.fact('repo:stable:tree', '/hashes/api.py')
    mem.put_artifact(actor, 'frontend', {'done':True}, obs.manifest())
    assert mem.register_source_tree(actor, 'repo:stable:tree', {'api.py':'2'*64})
    assert mem.status(actor, 'frontend') == 'STALE'


def test_source_registration_noop_preserves_unrelated_artifact(runtime):
    mem, actor = runtime
    hashes={'api.py':'1'*64, 'style.css':'2'*64}
    mem.register_source_tree(actor, 'repo:stable:tree', hashes)
    obs=mem.observe(actor);obs.fact('repo:stable:tree', '/hashes/style.css')
    mem.put_artifact(actor, 'styles', {'done':True}, obs.manifest())
    assert mem.register_source_tree(actor, 'repo:stable:tree', dict(reversed(list(hashes.items())))) is False
    assert mem.status(actor,'styles') == 'DECLARED_CURRENT'


def test_source_changes_preserve_unrelated_content_dependency(runtime):
    mem, actor = runtime
    mem.register_source_tree(actor, 'repo:stable:tree', {'api.py':'1'*64,'styles.css':'2'*64})
    obs=mem.observe(actor);obs.fact('repo:stable:tree','/hashes/styles.css')
    mem.put_artifact(actor,'styles',{'done':True},obs.manifest())
    mem.register_source_tree(actor, 'repo:stable:tree', {'api.py':'3'*64,'styles.css':'2'*64})
    assert mem.status(actor,'styles') == 'DECLARED_CURRENT'


def test_read_file_is_bounded_without_reading_whole_file(tmp_path,monkeypatch):
    ws=Workspace(tmp_path/'w')
    ws.write_file('big.txt','x'*128_000)
    assert ws.read_file('big.txt') == 'x'*8192


def test_symlink_source_cannot_be_sealed(runtime,tmp_path):
    mem, actor = runtime
    work=Workspace(tmp_path/'candidate')
    secret=tmp_path/'secret.py';secret.write_text('PASSWORD="secret"\n')
    (work.path/'link.py').symlink_to(secret)
    gate=UnifiedGate(mem,actor)
    result=gate.publish(candidate=work,baseline=None,base_manifest={},observation=mem.observe(actor),
                        developer={'status':'PASS'},acceptance={'status':'PASS','test_count':1},
                        model='mock',calls=1,output_id='result:demo',job_id=None,generation=None)
    assert result.decision == 'REJECT'
    assert result.published_snapshot is None
    assert not list(tmp_path.glob('.fluxos-published/*'))


def test_failed_commit_cleans_candidate_copy(runtime,tmp_path):
    mem, actor = runtime
    work=Workspace(tmp_path/'candidate')
    work.write_file('main.py', 'x=1')
    gate=UnifiedGate(mem,actor)
    out=gate.publish(candidate=work,baseline=None,base_manifest={},observation=mem.observe(actor),
                        developer={'status':'PASS'},acceptance={'status':'PASS','test_count':1},
                        model='mock',calls=1,output_id='result:demo',job_id=None,generation=None,
                        trusted_acceptance=lambda sealed:{'status':'PASS','test_count':1,'trust_boundary':'blackbox',
                            'contract_hash':'test-contract','candidate_manifest_hash':sealed.manifest_digest()})
    assert out.status == 'COMMIT_REJECTED'
    assert not list((tmp_path/'.fluxos-published').iterdir())
    assert (work.path/'main.py').read_text() == 'x=1'


def test_draft_does_not_commit_kernel_record(runtime,tmp_path):
    mem, actor = runtime
    work=Workspace(tmp_path/'candidate')
    work.write_file('main.py','x=1')
    out=UnifiedGate(mem,actor).publish(candidate=work,baseline=None,base_manifest={},
             observation=mem.observe(actor),developer={'status':'NO_TESTS'},
             acceptance={'status':'NOT_CONFIGURED'},model='mock',calls=0,
             output_id='result:demo',job_id=None,generation=None)
    assert out.decision == 'CONTINUE_PRIVATE'
    assert out.status == 'DRAFT'
    assert out.draft_snapshot is not None
    assert mem.graph('scope')['nodes'] == []


def test_timeout_forces_docker_container_cleanup(tmp_path,monkeypatch):
    import subprocess
    import fluxos.agent as code
    seen=[]
    monkeypatch.setattr(code.shutil,'which',lambda name: '/usr/bin/docker')
    def fake_run(command,**kwargs):
        seen.append(command)
        if 'run' in command:
            raise subprocess.TimeoutExpired(command,45)
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(code.subprocess,'run',fake_run)
    result=Workspace(tmp_path/'candidate').run_tests()
    assert result['status']=='TIMEOUT'
    assert seen[0][:2]==['docker','run']
    assert seen[1][:3]==['docker','rm','-f']
    assert seen[1][-1]==seen[0][seen[0].index('--name')+1]


def test_api_module_import_has_no_persistent_filesystem_side_effect(tmp_path, monkeypatch):
    import fluxos.api as api
    monkeypatch.chdir(tmp_path)
    importlib.reload(api)
    assert not (tmp_path/'.fluxos').exists()


def test_workspace_over_budget_rejected(tmp_path):
    w=Workspace(tmp_path/'large')
    for i in range(101):
        w.write_file(f'module_{i}.py','pass')
    with pytest.raises(ValueError,match='100-file'):
        w.file_manifest()


def test_snapshot_matches_original_bytes(tmp_path):
    base=Workspace(tmp_path/'base')
    src='line 1\n' + 'A'*120_000
    base.write_file('src.py',src)
    out=Workspace(tmp_path/'copy')
    assert base.snapshot_to(out)==out.file_manifest()
    assert (out.path/'src.py').read_bytes()==(base.path/'src.py').read_bytes()
