"""Kernel benchmarks A/B/C/E with explicit oracles, denominators, and limits."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import random
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from .common import context, provenance, record, utcnow
from .metrics import percentile, ratio
from ..agent import Workspace
from ..gateway import UnifiedGate
from ..kernel import Denied, IntegrityError, Principal, Stale, digest


def _reject(suite,category,call,expected,*,seed=0,unchanged=None,metric=None):
    start=perf_counter()
    try:
        call()
        detected=False;error=None
    except expected as exc:
        detected=True;error=type(exc).__name__
    except Exception as exc:
        return record(suite,category,seed=seed,passed=False,status='UNEXPECTED_ERROR',
            expected_rejection=True,detected=False,false_accept=False,error=type(exc).__name__,metric=metric,
            latency_ms=1000*(perf_counter()-start))
    intact=unchanged() if unchanged else True
    return record(suite,category,seed=seed,passed=detected and intact,
        expected_rejection=True,detected=detected,false_accept=not detected,error=error,
        atomicity_violation=not intact,metric=metric,latency_ms=1000*(perf_counter()-start))


def safety(home,seeds):
    rows=[]
    for seed in seeds:
        memory,root,worker=context(Path(home)/str(seed),'safety')
        memory.put_fact(root,'shared',{'x':0,'y':0})
        memory.put_fact(worker,'shared',{'x':1,'y':0},expected_version=1)
        rows.append(_reject('A','stale_expected_version',lambda:memory.put_fact(worker,'shared',{'x':2},expected_version=1),Stale,
            seed=seed,metric='stale_acceptance'))
        rows.append(_reject('A','stale_field_preimage',lambda:memory.patch_fact(worker,'shared',[
            {'path':'/x','expected_hash':digest(0),'value':2}]),Stale,seed=seed,metric='stale_acceptance'))
        before=memory.fact_head(root,'shared')
        rows.append(_reject('A','failed_multifield_patch',lambda:memory.patch_fact(worker,'shared',[
            {'path':'/x','expected_hash':digest(1),'value':2},{'path':'/y','expected_hash':digest(99),'value':2}]),Stale,
            seed=seed,metric='atomicity',unchanged=lambda:memory.fact_head(root,'shared')==before))
        rows.append(_reject('A','overlapping_patch',lambda:memory.patch_fact(worker,'shared',[
            {'path':'/x','expected_hash':digest(1),'value':{}},{'path':'/x/a','expected_hash':None,'value':2}]),ValueError,
            seed=seed,metric='atomicity',unchanged=lambda:memory.fact_head(root,'shared')==before))
        observation=memory.observe(worker);observation.fact('shared','/x')
        memory.patch_fact(worker,'shared',[{'path':'/x','expected_hash':digest(1),'value':3}])
        rows.append(_reject('A','stale_recorded_read',lambda:memory.put_artifact(worker,'stale-output',{},observation.manifest()),Stale,
            seed=seed,metric='stale_acceptance'))
        reader=Principal('reader','safety',1,frozenset({'reader'}))
        rows.append(_reject('A','unauthorized_publication',lambda:memory.put_artifact(reader,'denied',{},[]),Denied,
            seed=seed,metric='unauthorized_publication'))
        job=memory.create_job('safety',worker.name,'obsolete worker',actor=worker)
        generation=memory.set_job(job,'RUNNING',actor=worker)
        memory.reconcile_interrupted_jobs('safety')
        rows.append(_reject('A','old_generation_publication',lambda:memory.put_artifact(worker,'result:'+job,{},[],job_id=job,job_generation=generation),Stale,
            seed=seed,metric='old_generation_publication'))
        memory.put_fact(root,'independent',{'a':0,'b':0})
        observations=[]
        for key in ('a','b'):
            observation=memory.observe(worker);observation.fact('independent','/'+key)
            observations.append((key,observation.manifest()))
        for key,manifest in observations:
            memory.patch_fact(worker,'independent',[{'path':'/'+key,'expected_hash':digest(0),'value':1}],read_manifest=manifest)
        actual=memory.fact_head(root,'independent')['value']
        preserved=sum(actual.get(key)==1 for key in ('a','b'))
        rows.append(record('A','valid_disjoint_edits',seed=seed,hostile=False,passed=preserved==2,
            metric='lost_update',scheduled_valid_writes=2,preserved_writes=preserved))
    return rows


def _build_graph(memory,worker,graph):
    for name,inputs in graph.items():
        observed=memory.observe(worker)
        values=[]
        for kind,source,pointer in inputs:
            values.append(observed.fact(source,pointer) if kind=='fact' else observed.artifact(source))
        memory.put_artifact(worker,name,{'input_digest':digest(values)},observed.manifest())


def _graph_oracle(graph,changed):
    stale=set()
    for name,inputs in graph.items():
        if any((kind=='fact' and (source,pointer) in changed) or
               (kind=='artifact' and source in stale) for kind,source,pointer in inputs):
            stale.add(name)
    return stale


def _classify_graph(memory,worker,graph,expected,seed,scenario):
    rows=[]
    repair=set()
    for name in graph:
        actual=memory.status(worker,name)=='STALE'
        if actual:repair.add(name)
        reused=False
        if not actual:
            memory.artifact(worker,name)
            reused=True
        rows.append(record('B',scenario,seed=seed,hostile=False,passed=actual==(name in expected),
            artifact=name,classification_population=True,should_be_stale=name in expected,
            observed_stale=actual,eligible_reuse=name not in expected,reused=reused,
            recomputed=actual,full_restart_units=1))
    # Perform the selective repair, not just a prediction of potential reuse.
    for name,inputs in graph.items():
        if name in repair:
            _build_graph(memory,worker,{name:inputs})
    intact=all(memory.status(worker,name)=='DECLARED_CURRENT' for name in graph)
    rows.append(record('B',scenario+'_after_repair',seed=seed,hostile=False,passed=intact,
                       repaired_units=len(repair),preserved_units=len(graph)-len(repair)))
    return rows


def reuse(home,seeds,nodes=24):
    rows=[]
    for scenario,field in [('api_contract_change','api'),('unrelated_stylesheet_change','styles')]:
        memory,root,worker=context(Path(home)/scenario,'reuse')
        memory.put_fact(root,'requirements',{'api':1,'styles':1})
        graph={'frontend':[('fact','requirements','/api')],
               'styles':[('fact','requirements','/styles')],
               'integration':[('artifact','frontend','')]}
        _build_graph(memory,worker,graph)
        memory.patch_fact(worker,'requirements',[{'path':'/'+field,'expected_hash':digest(1),'value':2}])
        expected=_graph_oracle(graph,{('requirements','/'+field)})
        rows.extend(_classify_graph(memory,worker,graph,expected,0,scenario))
    memory,root,worker=context(Path(home)/'missing','reuse')
    memory.put_fact(root,'config',{'known':1})
    observed=memory.observe(worker);observed.absent_fact('config','/optional')
    memory.put_artifact(worker,'absent-field',{},observed.manifest())
    memory.patch_fact(worker,'config',[{'path':'/optional','expected_hash':None,'value':True}])
    rows.append(record('B','negative_field_appears',hostile=False,
        passed=memory.status(worker,'absent-field')=='STALE',classification_population=True,
        should_be_stale=True,observed_stale=memory.status(worker,'absent-field')=='STALE',
        eligible_reuse=False,reused=False,recomputed=True,full_restart_units=1))
    source='repo:missing-file:tree'
    memory.register_source_tree(worker,source,{'existing.py':'1'*64})
    observed=memory.observe(worker);observed.fact(source,'/names')
    memory.put_artifact(worker,'missing-file',{},observed.manifest())
    memory.register_source_tree(worker,source,{'existing.py':'1'*64,'required.py':'2'*64})
    rows.append(record('B','previously_missing_file_added',hostile=False,
        passed=memory.status(worker,'missing-file')=='STALE',classification_population=True,
        should_be_stale=True,observed_stale=memory.status(worker,'missing-file')=='STALE',
        eligible_reuse=False,reused=False,recomputed=True,full_restart_units=1))
    memory.put_fact(root,'restore',{'value':1})
    observed=memory.observe(worker);observed.fact('restore','/value')
    memory.put_artifact(worker,'restore-output',{},observed.manifest())
    memory.put_fact(root,'restore',{'value':2});memory.put_fact(root,'restore',{'value':1})
    rows.append(record('B','exact_content_restore',hostile=False,
        passed=memory.status(worker,'restore-output')=='STALE',
        observation=memory.status(worker,'restore-output'),
        rule='Invalidation is sticky until an explicit new artifact publication; restoration does not resurrect an invalidated revision.'))
    memory.put_artifact(worker,'omitted-dependency',{'computed_from':'config/known'},[])
    memory.patch_fact(worker,'config',[{'path':'/known','expected_hash':digest(1),'value':2}])
    rows.append(record('B','unmediated_dependency_omission',hostile=False,passed=None,status='BOUNDARY_LIMITATION',
        observation=memory.status(worker,'omitted-dependency'),
        rule='The kernel cannot prove an in-process caller declared every real read. Mediated model file tools record reads; arbitrary hidden I/O remains outside the guarantee.'))
    for seed in seeds:
        memory,root,worker=context(Path(home)/('graph-'+str(seed)),'reuse')
        memory.put_fact(root,'inputs',{f'f{i}':1 for i in range(6)})
        rng=random.Random(seed)
        graph={}
        for i in range(nodes):
            inputs=[('fact','inputs',f'/f{0 if i==0 else rng.randrange(6)}')]
            parents=rng.sample(list(graph),min(len(graph),rng.randrange(3)))
            inputs.extend(('artifact',parent,'') for parent in parents)
            graph[f'node-{i}']=inputs
        _build_graph(memory,worker,graph)
        memory.patch_fact(worker,'inputs',[{'path':'/f0','expected_hash':digest(1),'value':2}])
        expected=_graph_oracle(graph,{('inputs','/f0')})
        rows.extend(_classify_graph(memory,worker,graph,expected,seed,'generated_dag'))
    return rows


def concurrency(home,seeds,writers):
    rows=[];groups=[]
    for seed in seeds:
        for count in writers:
            for scenario in ('disjoint','same_field','nested_transitive'):
                memory,root,worker=context(Path(home)/f'{seed}-{count}-{scenario}','concurrency')
                actors=[Principal(f'worker-{i}','concurrency',1,worker.roles) for i in range(count)]
                memory.put_fact(root,'shared',{'fields':{f'k{i}':0 for i in range(count)},'untouched':1})
                if scenario=='nested_transitive':
                    graph={}
                    for i in range(count):
                        graph[f'leaf-{i}']=[('fact','shared',f'/fields/k{i}')]
                        graph[f'downstream-{i}']=[('artifact',f'leaf-{i}','')]
                    graph['unrelated']=[('fact','shared','/untouched')]
                    _build_graph(memory,worker,graph)
                inputs=[]
                for i,actor in enumerate(actors):
                    pointer='/fields/k0' if scenario=='same_field' else f'/fields/k{i}'
                    observation=memory.observe(actor);observation.fact('shared',pointer)
                    inputs.append((i,actor,pointer,observation.manifest()))
                random.Random(seed).shuffle(inputs)
                def commit(item):
                    i,actor,pointer,manifest=item
                    start=perf_counter()
                    try:
                        version=memory.patch_fact(actor,'shared',[{'path':pointer,'expected_hash':digest(0),'value':i+1}],read_manifest=manifest)
                        outcome='COMMITTED';error=None
                    except Stale:
                        outcome='CONFLICT_REJECTED';version=None;error=None
                    except Exception as exc:
                        outcome='ERROR';version=None;error=type(exc).__name__
                    return {'writer':i,'outcome':outcome,'version':version,'error':error,
                            'latency_ms':1000*(perf_counter()-start)}
                start=perf_counter()
                with ThreadPoolExecutor(max_workers=count) as pool:
                    observed=list(pool.map(commit,inputs))
                elapsed=perf_counter()-start
                commits=sum(item['outcome']=='COMMITTED' for item in observed)
                conflicts=sum(item['outcome']=='CONFLICT_REJECTED' for item in observed)
                errors=sum(item['outcome']=='ERROR' for item in observed)
                final=memory.fact_head(root,'shared')['value']
                expected_commits=1 if scenario=='same_field' else count
                preserved=sum(final['fields'].get('k'+str(i))==i+1 for i in range(count)) if scenario!='same_field' else None
                invariant=commits==expected_commits and errors==0
                if scenario!='same_field':invariant=invariant and preserved==count
                elif commits==1:
                    winner=next(item['writer'] for item in observed if item['outcome']=='COMMITTED')
                    invariant=invariant and final['fields']=={f'k{i}':winner+1 if i==0 else 0 for i in range(count)}
                if scenario=='nested_transitive':
                    invariant=invariant and all(memory.status(worker,f'{prefix}-{i}')=='STALE' for prefix in ('leaf','downstream') for i in range(count))
                    invariant=invariant and memory.status(worker,'unrelated')=='DECLARED_CURRENT'
                group_id=f'{seed}:{count}:{scenario}'
                groups.append({'id':group_id,'seed':seed,'writers':count,'scenario':scenario,
                    'attempts':count,'committed':commits,'conflicts_rejected':conflicts,'errors':errors,
                    'scheduled_valid_writes':count if scenario!='same_field' else 0,
                    'preserved_writes':preserved if preserved is not None else 0,
                    'wall_seconds':elapsed,'throughput_commits_per_second':commits/elapsed,
                    'p50_ms':percentile([r['latency_ms'] for r in observed],.5),
                    'p95_ms':percentile([r['latency_ms'] for r in observed],.95),
                    'retries':0,'passed':bool(invariant)})
                for item in observed:
                    rows.append(record('C',scenario,seed=seed,hostile=False,passed=bool(invariant),
                                       group_id=group_id,writers=count,**item))
    return rows,groups


def adversarial(home,seeds,crashes=True):
    rows=[]
    for seed in seeds:
        memory,root,worker=context(Path(home)/str(seed),'adversarial')
        memory.put_fact(root,'input',{'x':1})
        observed=memory.observe(worker);observed.fact('input','/x')
        forged=[{**d,'expected_hash':'0'*64} for d in observed.manifest()]
        rows.append(_reject('E','forged_read_hash',lambda:memory.put_artifact(worker,'forged',{},forged),Stale,seed=seed))
        memory.record_claim(root,'secret','status','private','operator',label='secret')
        low=Principal('low','adversarial',0,frozenset({'reader','writer'}))
        visible=memory.claims(low,'secret','status')
        rows.append(record('E','confidential_claim_metadata',seed=seed,
                           passed=visible=={'status':'UNAVAILABLE','claims':[]},
                           expected_rejection=True,detected=visible=={'status':'UNAVAILABLE','claims':[]},
                           false_accept=visible!={'status':'UNAVAILABLE','claims':[]}))
        job=memory.create_job('adversarial',worker.name,'cancel',actor=worker)
        generation=memory.set_job(job,'RUNNING',actor=worker)
        memory.set_job(job,'CANCELLED',actor=worker)
        rows.append(_reject('E','cancelled_worker_shared_mutation',lambda:memory.patch_fact(worker,'input',[
            {'path':'/x','expected_hash':digest(1),'value':2}],job_fences=[(job,generation)]),Stale,seed=seed))
        for attack in ('forged_pass','tampered_seal'):
            candidate=Workspace(Path(home)/str(seed)/('candidate-'+attack))
            candidate.write_file('main.py','print(42)\n')
            jid=memory.create_job('adversarial',worker.name,attack,actor=worker)
            epoch=memory.set_job(jid,'RUNNING',actor=worker)
            def tamper(sealed):
                evidence={'status':'PASS','test_count':1,'trust_boundary':'blackbox',
                    'contract_hash':'SYNTHETIC_FAULT_ORACLE','candidate_manifest_hash':sealed.manifest_digest()}
                path=sealed.path/'main.py';path.chmod(0o644);path.write_text('print(0)',encoding='utf8')
                return evidence
            outcome=UnifiedGate(memory,worker).publish(candidate=candidate,baseline=None,base_manifest={},
                observation=memory.observe(worker),developer={'status':'PASS','test_count':999},
                acceptance={'status':'PASS','test_count':999},model='SYNTHETIC_FAULT_ORACLE',calls=0,
                output_id='result:'+jid,job_id=jid,generation=epoch,project_id=attack,base_revision=0,
                trusted_acceptance=tamper if attack=='tampered_seal' else None)
            expected='DRAFT' if attack=='forged_pass' else 'COMMIT_REJECTED'
            safe=outcome.status==expected and memory.project_head(worker,attack) is None
            rows.append(record('E',attack,seed=seed,passed=safe,expected_rejection=True,
                detected=safe,false_accept=outcome.status=='VERIFIED',observation=outcome.status,
                oracle='Synthetic trusted callback; no claim of live Docker validation.'))
    if crashes:
        for phase,code in [('after_seal',73),('before_db_commit',74),('after_db_commit',75),('after_effect',76)]:
            path=(Path(home)/('crash-'+phase)).resolve();path.mkdir(parents=True)
            outcome=subprocess.run([sys.executable,'-m','fluxos.evaluation.crash_worker','--home',str(path),'--phase',phase],
                capture_output=True,text=True,timeout=30)
            memory,root,worker=context(path,'crash')
            head=memory.project_head(worker,'crash')
            history=memory.project_history(worker,'crash')
            jobs=memory.jobs('crash')
            recovered=memory.reconcile_interrupted_jobs('crash')
            consistent=(head is not None and len(history)==1) if phase=='after_db_commit' else head is None and not history
            if phase=='after_effect':
                consistent=consistent and (path/'effect_receipt.txt').read_text()=='effect performed once'
                consistent=consistent and len(recovered)==1 and memory.reconcile_interrupted_jobs('crash')==[]
            safe=outcome.returncode==code and consistent and len(jobs)==1
            rows.append(record('E','crash_'+phase,passed=safe,hostile=True,
                expected_exit_code=code,observed_exit_code=outcome.returncode,consistent_head=consistent,
                retained_project_revisions=len(history),quarantined_jobs=len(recovered),
                orphan_snapshots=sum(1 for folder in ('.fluxos-sealed','.fluxos-published') for _ in path.glob(folder+'/*')) if head is None else 0,
                external_effect_outcome='UNCERTAIN_NOT_REPLAYED' if phase=='after_effect' else None,
                oracle='Real process termination; synthetic acceptance and local effect receipt only.',
                unexpected_error=outcome.stderr[-1000:] if outcome.returncode!=code else None))
    return rows


def summarize(rows,groups):
    metrics={}
    for name in ('stale_acceptance','unauthorized_publication','atomicity','old_generation_publication'):
        selected=[r for r in rows if r.get('metric')==name]
        numerator=sum(r.get('atomicity_violation',False) if name=='atomicity' else r.get('false_accept',False) for r in selected)
        metrics[('atomicity_violation' if name=='atomicity' else name)+'_rate']=ratio(numerator,len(selected))
    valid=[r for r in rows if r.get('metric')=='lost_update']
    writes=sum(r['scheduled_valid_writes'] for r in valid)+sum(g['scheduled_valid_writes'] for g in groups)
    preserved=sum(r['preserved_writes'] for r in valid)+sum(g['preserved_writes'] for g in groups)
    metrics['lost_update_rate']=ratio(writes-preserved,writes)
    classified=[r for r in rows if r.get('classification_population')]
    genuinely_stale=[r for r in classified if r['should_be_stale']]
    valid_artifacts=[r for r in classified if not r['should_be_stale']]
    metrics['invalidation_recall']=ratio(sum(r['observed_stale'] for r in genuinely_stale),len(genuinely_stale))
    metrics['false_invalidation_rate']=ratio(sum(r['observed_stale'] for r in valid_artifacts),len(valid_artifacts))
    metrics['reuse_rate']=ratio(sum(r['reused'] for r in valid_artifacts),len(valid_artifacts))
    metrics['recomputation_reduction']=ratio(sum(not r['recomputed'] for r in classified),len(classified))
    security=[r for r in rows if r['suite']=='E' and r.get('expected_rejection')]
    metrics['attack_detection_rate']=ratio(sum(r['detected'] for r in security),len(security))
    metrics['attack_false_accept_rate']=ratio(sum(r['false_accept'] for r in security),len(security))
    checked=[r for r in rows if r['passed'] is not None]
    metrics['invariant_checks']=ratio(sum(bool(r['passed']) for r in checked),len(checked))
    return {'metrics':metrics,'hard_safety_gate_passed':all(r['passed'] for r in checked),
            'unexpected_errors':sum(r.get('status')=='UNEXPECTED_ERROR' or r.get('outcome')=='ERROR' for r in rows),
            'limitations':[r for r in rows if r['status']=='BOUNDARY_LIMITATION'],
            'evidence_kind':'DETERMINISTIC_KERNEL_EXPERIMENTS_ZERO_MODEL_CALLS'}


def run(*,seeds=(11,29,47),writers=(1,2,5,10,20,50),nodes=24,crashes=True):
    if not seeds or not writers or any(type(n) is not int or not 1<=n<=128 for n in writers):
        raise ValueError('provide seeds and writer counts in 1..128')
    if not 2<=nodes<=128:raise ValueError('graph nodes must be in 2..128')
    started=utcnow();clock=perf_counter()
    with TemporaryDirectory(prefix='fluxos-evaluation-') as home:
        home=Path(home)
        rows=safety(home/'A',seeds)+reuse(home/'B',seeds,nodes)
        concurrent,groups=concurrency(home/'C',seeds,writers)
        rows+=concurrent+adversarial(home/'E',seeds,crashes)
    summary=summarize(rows,groups)
    return {'schema_version':1,'kind':'deterministic','started_at':started,'finished_at':utcnow(),
        'wall_seconds':perf_counter()-clock,'config':{'seeds':list(seeds),'writers':list(writers),'graph_nodes':nodes,'crash_tests':crashes},
        'provenance':provenance(),'rows':rows,'concurrency_groups':groups,'summary':summary,
        'real_model_calls':0,'live_ai_performance':None}
