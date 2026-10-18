"""Reviewed dashboard rows derived solely from saved experiment records."""
from collections import defaultdict
from .common import utcnow, write_json
from .metrics import percentile


def snapshot(deterministic, live=None, files=None):
    files=files or ['deterministic.json','pilot/results.json']
    metrics=deterministic['summary']['metrics']
    live_summary=(live or {}).get('summary',{})
    arms=live_summary.get('arms',[])
    treatment=next((a for a in arms if a['arm']=='F0'),None)
    comparison=live_summary.get('paired_f0_vs_b0',{})
    stale=metrics['stale_acceptance_rate'];reuse=metrics['reuse_rate']
    completion=treatment['completion'] if treatment else {'numerator':0,'denominator':0,'rate':None}
    groups=deterministic['concurrency_groups']
    maximum=max(g['writers'] for g in groups)
    selected=[g for g in groups if g['writers']==maximum and g['scenario']=='disjoint']
    throughput=sum(g['committed'] for g in selected)/sum(g['wall_seconds'] for g in selected)
    headlines=[
        {'key':'stale','label':'Stale acceptance','value':stale['rate'],'unit':'percent',**stale,
         'detail':f"{stale['numerator']} accepted / {stale['denominator']} tested stale attempts"},
        {'key':'reuse','label':'Valid work preserved','value':reuse['rate'],'unit':'percent',**reuse,
         'detail':f"{reuse['numerator']} reused / {reuse['denominator']} eligible kernel artifacts"},
        {'key':'completion','label':'Verified completion','value':completion['rate'],'unit':'percent',**completion,
         'detail':f"F0 {completion['numerator']}/{completion['denominator']}; B0 comparison pending" if not arms else
            f"F0 − B0: {comparison.get('difference_pp')} pp; {comparison.get('paired_runs',0)} pairs"},
        {'key':'cost','label':'Cost per success','value':treatment.get('cost_per_verified_completion_usd') if treatment else None,
         'unit':'USD','numerator':None,'denominator':completion['numerator'],'detail':'Actual billing evidence unavailable'},
        {'key':'p95','label':'P95 completion time','value':treatment.get('p95_seconds') if treatment else None,
         'unit':'s','numerator':None,'denominator':completion['denominator'],'detail':'F0 attempted tasks, including failures and retries'},
        {'key':'throughput','label':'Concurrent throughput','value':throughput,'unit':'commits/s',
         'numerator':sum(g['committed'] for g in selected),'denominator':sum(g['wall_seconds'] for g in selected),
         'detail':f'{maximum} writers; disjoint kernel commits; {len(selected)} seeds'},
    ]
    grouped=defaultdict(list)
    for group in groups:grouped[(group['writers'],group['scenario'])].append(group)
    concurrency=[]
    for (writers,scenario),records in sorted(grouped.items()):
        ids={r['id'] for r in records}
        latencies=[r['latency_ms'] for r in deterministic['rows'] if r.get('group_id') in ids]
        concurrency.append({'writers':writers,'scenario':scenario,'seeds':len(records),
            'committed':sum(r['committed'] for r in records),'conflicts':sum(r['conflicts_rejected'] for r in records),
            'errors':sum(r['errors'] for r in records),'passed':all(r['passed'] for r in records),
            'throughput':sum(r['committed'] for r in records)/sum(r['wall_seconds'] for r in records),
            'p50_ms':percentile(latencies,.5),'p95_ms':percentile(latencies,.95)})
    gates=[{'metric':key,'numerator':value['numerator'],'denominator':value['denominator'],
            'rate':value['rate']} for key,value in metrics.items()]
    attacks=[r for r in deterministic['rows'] if r['suite']=='E']
    pending=[{'task_id':r['task_id'],'arm':r['arm'],'trial':r['trial'],'status':r['status'],
        'attempted':r.get('attempted',False),'verified_completion':r.get('verified_completion')}
        for r in (live or {}).get('rows',[])]
    definitions=[{'label':r['label'],'definition':r['detail'],'componentIds':['headline-'+r['key']],
        'formula':'See numerator, denominator and unit in reviewed row. Null means unavailable.',
        'numerator':str(r['numerator']),'denominator':str(r['denominator']),
        'sourceLineage':[{'files':files}]} for r in headlines]
    def query(rows,label):
        return {'rows':rows,'source':{'label':label,'files':files,'executedAt':deterministic['finished_at'],
            'metricDefinitions':definitions,'caveats':[
                'Deterministic and scripted checks are not real-model task results.',
                'Zero observed failures are limited to tested cases; hidden dependencies are outside the kernel guarantee.',
                'Concurrency is in-process kernel writers, not simultaneous language-model agents.',
                'Latency percentiles use pooled raw attempts; throughput is commits divided by measured group seconds.']},
            'methods':[{'language':'python','code':'fluxos.evaluation.report.snapshot(saved_deterministic, saved_live)'}]}
    return {'surface':'dashboard','title':'FLUX//OS benchmark evidence','generatedAt':utcnow(),
        'status':'Kernel measurements complete; real-model paired study pending' if not arms else 'Measured paired study',
        'buildStatus':'creating','filters':[], 'queries':{
            'headlines':query(headlines,'Six requested measures'),
            'gates':query(gates,'Defined invariant populations'),
            'concurrency':query(concurrency,'Pooled kernel concurrency matrix'),
            'concurrency_groups':query(groups,'Raw per-seed concurrency groups'),
            'attacks':query(attacks,'Adversarial and process crash records'),
            'limitations':query(deterministic['summary']['limitations'],'Dependency observation boundary'),
            'live_runs':query(pending,'Every scheduled paired run'),
            'live_arms':query(arms,'Attempted live runs only; scripted records excluded'),
            'kernel_records':query(deterministic['rows'],'Complete deterministic evidence')}}


def main():
    import argparse,json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deterministic',type=Path,required=True)
    parser.add_argument('--live',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    kernel=json.loads(args.deterministic.read_text(encoding='utf8'))
    live=json.loads(args.live.read_text(encoding='utf8')) if args.live else None
    write_json(args.output,snapshot(kernel,live))


if __name__=='__main__':main()
