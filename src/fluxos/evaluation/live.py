"""Randomized paired runner with private unit and full-project Docker acceptance."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
from time import perf_counter
import uuid

from .agent import EvaluationAgent
from . import PROTOCOL_VERSION
from .budget import BudgetExceeded, Limits, MeteredGemma
from .common import context, provenance, utcnow, write_json
from .metrics import summarize_live
from .tasks import catalog, contracts, fixtures, unit_goal, affected_units
from ..agent import MODEL, Workspace
from ..gateway import UnifiedGate
from ..kernel import Stale, digest


ARMS={
    'B0':'Common tools and sealed acceptance; last-write-wins notes; full component restart after input changes; no causal witnesses.',
    'B1':'B0 with whole-record optimistic CAS and conflict rejection.',
    'F0':'FLUX causal observations and selective component reuse; no delegation.',
    'F1':'F0 with optional production bounded child delegation (all calls share the task budget).',
}

REFERENCE_ENGINE='''import json, pathlib, re, sys
data=json.load(sys.stdin)
base=pathlib.Path(__file__).resolve().parent
spec=json.loads((base/"engine_spec.json").read_text())
op=spec["operation"]
if op=="sum": value=sum(data["values"])
elif op=="mean": value=sum(data["values"])/len(data["values"]) if data["values"] else 0
elif op=="deduplicate": value=list(dict.fromkeys(data["values"]))
elif op=="word_counts":
    words=(data["text"].lower() if spec.get("lowercase") else data["text"]).split()
    value={word:words.count(word) for word in set(words)}
elif op=="sort_records": value=sorted(data["records"],key=lambda row:row[spec["sort_key"]],reverse=spec.get("reverse",False))
elif op=="inventory_total": value=sum(item["price"]*item["quantity"] for item in data["items"])
elif op=="slug": value=re.sub("[^a-z0-9]+","-",data["text"].strip().lower()).strip("-")
elif op=="select_fields": value={field:data.get(field) for field in spec["fields"]}
else: raise ValueError(op)
if isinstance(value,(int,float)) and not isinstance(value,bool):
    value*=spec.get("factor",1)
    bonus=base/"bonus.json"
    if bonus.exists(): value+=json.loads(bonus.read_text())["bonus"]
print(json.dumps({spec.get("result_key","result"):value},sort_keys=True,separators=(",",":"),ensure_ascii=False))
'''
REFERENCE_FORMAT='''import json, pathlib, sys
data=json.load(sys.stdin)
spec=json.loads(pathlib.Path(__file__).with_name("formatter_spec.json").read_text())
value=data[spec.get("result_key","result")]
if spec["mode"]=="fixed": print(f"{value:.{spec.get('decimals',2)}f}")
else:
    encoded=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    print(spec["label"]+"="+encoded if spec["mode"]=="labelled" else encoded)
'''


class ScriptedReference:
    """Tests orchestration with actual containers, never represents AI performance."""
    model='SCRIPTED_REFERENCE_NOT_A_MODEL'
    def __init__(self,limits):self.limits=limits;self.calls=0;self.started=perf_counter()
    def generate(self,contents,tools,system):
        if self.calls>=self.limits.model_calls:raise BudgetExceeded('scripted turn budget exhausted')
        self.calls+=1
        unit='engine.py' if 'Implement engine.py' in contents[0]['parts'][0]['text'] else 'formatter.py'
        if len(contents)==1:
            calls=[('read_file',{'path':'engine_spec.json' if unit=='engine.py' else 'formatter_spec.json'})]
        elif len(contents)==3:
            calls=[('write_file',{'path':unit,'content':REFERENCE_ENGINE if unit=='engine.py' else REFERENCE_FORMAT})]
        else:return {'parts':[{'text':'Reference implementation ready.'}]}
        return {'parts':[{'functionCall':{'name':name,'args':args}} for name,args in calls]}
    def summary(self):
        return {'model_calls':self.calls,'provider_attempts':0,'provider_retries':0,'count_tokens_requests':0,
            'total_tokens':None,'observed_known_tokens':0,'budget_charged_tokens':0,'usage_complete':False,
            'budget_exhausted':self.calls>=self.limits.model_calls,'wall_seconds':perf_counter()-self.started,
            'limits':asdict(self.limits),'requests':[]}


def readiness():
    docker=shutil.which('docker')
    result={'docker_cli':bool(docker),'daemon':False,'python_image':None,'node_image':None}
    if not docker:return result
    try:
        result['daemon']=subprocess.run([docker,'info'],capture_output=True,timeout=15).returncode==0
        if result['daemon']:
            for runtime,image in [('python','python:3.12-alpine'),('node','node:22-alpine')]:
                found=subprocess.run([docker,'image','inspect',image,'--format','{{.Id}}'],capture_output=True,text=True,timeout=10)
                result[runtime+'_image']=found.stdout.strip() if found.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired):pass
    return result


def make_plan(*,task_ids=None,arms=('B0','F0'),trials=1,seed=20261018,limits=None,model=MODEL,mode='live'):
    if not arms or len(set(arms))!=len(arms) or set(arms)-ARMS.keys():raise ValueError('unknown or duplicate arm')
    if type(trials) is not int or not 1<=trials<=100:raise ValueError('trials must be 1..100')
    tasks={task['id']:task for task in catalog()}
    selected=list(task_ids) if task_ids is not None else list(tasks)
    if not selected or set(selected)-tasks.keys() or len(set(selected))!=len(selected):raise ValueError('unknown or duplicate task ID')
    limits=(limits or Limits()).validate()
    runs=[{'task_id':task,'arm':arm,'trial':trial,'task_hash':tasks[task]['hash']}
          for task in selected for trial in range(trials) for arm in arms]
    random.Random(seed).shuffle(runs)
    for index,row in enumerate(runs):row['order']=index
    return {'schema_version':1,'protocol_version':PROTOCOL_VERSION,'kind':'live_plan','created_at':utcnow(),'model':model,'mode':mode,
            'retry_policy':'Three attempts; exponential 1s/2s fallback; honor Retry-After/RPC RetryInfo; task-wide cooldown and wall budget.',
            'completion_policy':'Missing required output continues within the original unit-turn and task budgets.',
            'seed':seed,'trials':trials,'arms':{arm:ARMS[arm] for arm in arms},'limits':asdict(limits),
            'tasks':[tasks[task] for task in selected],'runs':runs,
            'primary_outcome':'Both task phases pass host-owned Docker unit and full-project acceptance inside the shared task budget.',
            'cost_policy':'Actual billed USD is unavailable without billing evidence; never infer it from token counts.',
            'scope':'Controlled CLI component microbenchmark. Kernel attacks/races are independently measured by A/C/E; this is not a MemTX comparison.'}


def _journal(path,value):
    with Path(path).open('a',encoding='utf8') as stream:
        stream.write(json.dumps(value,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())


def execute_task(task,arm,trial,work,limits,model,mode,client_factory=None):
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    memory,root,worker=context(work,'evaluation')
    project='evaluation-'+uuid.uuid4().hex[:12]
    source_id='repo:'+project+':tree'
    canonical=Workspace(work/'inputs')
    client=(client_factory(limits) if client_factory else ScriptedReference(limits) if mode=='scripted'
            else MeteredGemma(limits,model))
    saved={};units=[];phases=[];regenerated=0;reused=0;eligible=0;faults=[]
    revision=0;safety_failures=0;fault_used=False
    for phase in range(2):
        if perf_counter()-client.started>=limits.wall_seconds:break
        values=fixtures(task,phase)
        for name in canonical.list_files():
            if name not in values:canonical.safe(name).unlink()
        for name,value in values.items():canonical.write_file(name,value)
        manifest=canonical.file_manifest()
        memory.register_source_tree(worker,source_id,manifest)
        phase_contracts=contracts(task,phase)
        for kind,contract in phase_contracts.items():
            write_json(work/'acceptance'/str(phase)/kind/'cases.json',contract)
        for unit in task['units']:
            prior=saved.get(unit)
            if phase==1 and prior and unit not in affected_units(task):eligible+=1
            if phase and arm in {'F0','F1'} and prior and memory.status(worker,prior['artifact_id'])=='DECLARED_CURRENT':
                reused+=1
                units.append({'phase':phase,'unit':unit,'status':'REUSED','artifact_id':prior['artifact_id']})
                continue
            regenerated+=1
            for retry in range(2):
                if perf_counter()-client.started>=limits.wall_seconds:break
                goal=unit_goal(task,unit)
                key='task:'+unit
                try:memory.fact_head(worker,key)
                except KeyError:memory.put_fact(worker,key,{'goal':goal},expected_version=0)
                job=memory.create_job(worker.scope,worker.name,goal,actor=worker)
                memory.set_job(job,'RUNNING',actor=worker)
                def inject():
                    nonlocal fault_used
                    if task['fault']=='cancel':memory.set_job(job,'CANCELLED',actor=worker)
                    else:memory.reconcile_interrupted_jobs(worker.scope,owner=worker.name)
                    fault_used=True
                    faults.append({'type':task['fault'],'phase':phase,'unit':unit,'job':job})
                fault=inject if task['fault'] and not fault_used and phase==0 else None
                candidate=Workspace(work/'candidates'/job)
                canonical.snapshot_to(candidate)
                agent=EvaluationAgent(client,memory,worker,canonical,key,root_job=job,
                    project_id=project,acceptance_dir=work/'acceptance'/str(phase)/unit)
                agent.configure(arm=arm,unit=unit,limits=limits,source_id=source_id,source_manifest=manifest,fault=fault)
                outcome=agent.execute(candidate,goal)
                unit_row={'phase':phase,'unit':unit,'retry':retry,'job':job,**outcome}
                units.append(unit_row)
                state=memory.get_job(job)['state']
                if outcome['status']=='VERIFIED' and state!='RUNNING':safety_failures+=1
                if state=='RUNNING':memory.set_job(job,'COMPLETED' if outcome['status']=='VERIFIED' else 'FAILED',actor=worker)
                if outcome['status']=='VERIFIED':saved[unit]=outcome;break
                saved.pop(unit,None)
                if fault is None or retry:break
                regenerated+=1
        assembly=Workspace(work/'assembled'/str(phase))
        canonical.snapshot_to(assembly)
        observed=memory.observe(worker)
        assembled=True
        for unit in task['units']:
            if unit not in saved:assembled=False;continue
            try:
                artifact=observed.artifact(saved[unit]['artifact_id'])
                source=Path(artifact['snapshot'])/unit
                target=assembly.safe(unit)
                target.write_bytes(source.read_bytes())
            except (Stale,KeyError,ValueError):assembled=False
        status='INCOMPLETE';acceptance=None
        if assembled and perf_counter()-client.started<limits.wall_seconds:
            job=memory.create_job(worker.scope,worker.name,'assemble independently checked units',actor=worker)
            generation=memory.set_job(job,'RUNNING',actor=worker)
            outcome=UnifiedGate(memory,worker).publish(candidate=assembly,baseline=None,base_manifest={},observation=observed,
                developer={},acceptance={},model=client.model,calls=0,output_id='result:'+job,job_id=job,generation=generation,
                project_id=project,base_revision=revision,
                trusted_acceptance=lambda sealed:sealed.run_blackbox(work/'acceptance'/str(phase)/'project',deadline=client.started+limits.wall_seconds))
            status=outcome.status;acceptance=outcome.verification
            memory.set_job(job,'COMPLETED' if status=='VERIFIED' else 'FAILED',actor=worker)
            if status=='VERIFIED':revision+=1
        phases.append({'phase':phase,'status':status,'acceptance':acceptance,
            'starting_repository_sha256':digest(manifest),'acceptance_sha256':digest(phase_contracts)})
    usage=client.summary()
    complete=len(phases)==2 and all(p['status']=='VERIFIED' for p in phases)
    within_wall=usage['wall_seconds']<=limits.wall_seconds
    complete=complete and within_wall and not safety_failures
    return {'task_id':task['id'],'category':task['category'],'task_hash':task['hash'],'arm':arm,'trial':trial,
        'attempted':True,'status':'VERIFIED' if complete else 'FAILED','verified_completion':bool(complete),
        'mode':mode,'real_model_calls':usage['model_calls'] if mode=='live' else 0,
        'regenerated_artifacts':regenerated,'reused_artifacts':reused,'eligible_reuse_artifacts':eligible,
        'acceptance_failures':sum(bool(record.get('verification')) and record['verification']['status']!='PASS' for record in units)
            +sum(bool(p['acceptance']) and p['acceptance']['status']!='PASS' for p in phases),
        'incomplete_phases':2-sum(p['status']=='VERIFIED' for p in phases),
        'repair_attempts':sum(bool(u.get('retry')) for u in units),'safety_failures':safety_failures,
        'wall_budget_exceeded':not within_wall,'cost_usd':None,
        'fault_injections':faults,'phases':phases,'units':units,**usage}


def run_plan(plan,output,*,client_factory=None):
    if plan.get('protocol_version',1)!=PROTOCOL_VERSION:
        raise ValueError('Plan protocol does not match this runner. Use its recorded Git revision to reproduce a historical plan.')
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    write_json(output/'plan.json',plan)
    infrastructure=readiness()
    ready=infrastructure['daemon'] and infrastructure['python_image'] and infrastructure['node_image']
    tasks={task['id']:task for task in plan['tasks']}
    limits=Limits(**plan['limits']).validate()
    results=[]
    for scheduled in plan['runs']:
        run_id=f"{scheduled['order']:04d}-{scheduled['arm']}-{scheduled['task_id']}-t{scheduled['trial']}"
        if not ready or (plan['mode']=='live' and not os.getenv('GEMINI_API_KEY') and not client_factory):
            results.append({**scheduled,'run_id':run_id,'attempted':False,'verified_completion':None,'status':'BLOCKED_PREREQUISITES',
                'mode':plan['mode'],'reason':'Docker daemon, pinned runtime images, and (for live mode) GEMINI_API_KEY are required.'})
            continue
        _journal(output/'journal.jsonl',{'state':'STARTED','run_id':run_id,'started_at':utcnow(),**scheduled})
        began=perf_counter()
        active_client=None
        def factory(current_limits):
            nonlocal active_client
            active_client=(client_factory(current_limits) if client_factory else
                ScriptedReference(current_limits) if plan['mode']=='scripted' else MeteredGemma(current_limits,plan['model']))
            return active_client
        try:
            row=execute_task(tasks[scheduled['task_id']],scheduled['arm'],scheduled['trial'],
                             output/'runs'/run_id,limits,plan['model'],plan['mode'],factory)
        except Exception as exc:
            usage=active_client.summary() if active_client else {}
            row={**scheduled,'attempted':True,'verified_completion':False,'status':'ERROR','error_type':type(exc).__name__,
                 'mode':plan['mode'],'wall_seconds':perf_counter()-began,'total_tokens':None,'cost_usd':None,
                 'model_calls':None,'provider_attempts':None,'provider_retries':None,'safety_failures':None,
                 'accounting_incomplete':not bool(active_client),**usage}
        row.update({'run_id':run_id,'order':scheduled['order']})
        write_json(output/'runs'/run_id/'result.json',row)
        _journal(output/'journal.jsonl',{'state':'FINISHED','run_id':run_id,'status':row['status'],
            'verified_completion':row['verified_completion'],'finished_at':utcnow()})
        results.append(row)
        write_json(output/'results.json',{'rows':results})
    live_rows=[r for r in results if r['mode']=='live']
    result={'schema_version':1,'kind':'live_evaluation','generated_at':utcnow(),'plan':plan,'infrastructure':infrastructure,
        'provenance':provenance(),'rows':results,'summary':summarize_live(live_rows),
        'scripted_validation_rows':sum(r['mode']=='scripted' and r.get('attempted') for r in results),
        'caveats':['Actual billing data unavailable; cost fields are null.',
                   'Twenty controlled CLI tasks do not establish performance on large software repositories.',
                   'B0/B1 retain the same sealed acceptance and job authorization as FLUX; only memory/dependency policy differs.',
                   'Process interruption after a STARTED journal entry requires operator reconciliation; no automatic paid-call replay.']}
    write_json(output/'results.json',result)
    return result
