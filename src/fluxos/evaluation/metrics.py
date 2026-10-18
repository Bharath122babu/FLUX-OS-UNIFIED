"""Denominator-preserving metrics and paired, task-cluster uncertainty."""
from __future__ import annotations

from collections import defaultdict
import math
import random


def ratio(numerator: int, denominator: int) -> dict:
    return {'numerator':numerator,'denominator':denominator,
            'rate':numerator/denominator if denominator else None}


def percentile(values, q: float):
    """Nearest-rank percentile; no average of subgroup percentiles."""
    ordered=sorted(values)
    return ordered[max(0,math.ceil(q*len(ordered))-1)] if ordered else None


def wilson(successes:int, attempts:int, z:float=1.959963984540054) -> dict:
    if not attempts:
        return {'low':None,'high':None,'level':0.95,'method':'Wilson score'}
    p=successes/attempts
    scale=1+z*z/attempts
    center=(p+z*z/(2*attempts))/scale
    half=z*math.sqrt(p*(1-p)/attempts+z*z/(4*attempts*attempts))/scale
    return {'low':max(0,center-half),'high':min(1,center+half),
            'level':0.95,'method':'Wilson score; descriptive per arm'}


def paired_difference(rows, baseline='B0', treatment='F0', seed=20261018, samples=2000):
    """Paired task-cluster bootstrap: keep a task's repeated trials together."""
    paired=defaultdict(dict)
    for row in rows:
        if row.get('attempted') and row['arm'] in {baseline,treatment}:
            paired[(row['task_id'],row['trial'])][row['arm']]=int(row['verified_completion'])
    clusters=defaultdict(list)
    for (task,trial),arms in paired.items():
        if baseline in arms and treatment in arms:
            clusters[task].append(arms[treatment]-arms[baseline])
    if not clusters:
        return {'baseline':baseline,'treatment':treatment,'paired_runs':0,'tasks':0,
                'difference_pp':None,'low_pp':None,'high_pp':None,'method':'paired task-cluster bootstrap'}
    values=list(clusters.values())
    estimate=sum(sum(v) for v in values)/sum(map(len,values))
    rng=random.Random(seed)
    draws=[]
    for _ in range(samples):
        selected=[rng.choice(values) for _ in values]
        draws.append(sum(sum(v) for v in selected)/sum(map(len,selected)))
    return {'baseline':baseline,'treatment':treatment,'paired_runs':sum(map(len,values)),
            'tasks':len(values),'difference_pp':100*estimate,
            'low_pp':100*percentile(draws,.025),'high_pp':100*percentile(draws,.975),
            'level':.95,'method':'paired task-cluster percentile bootstrap',
            'caveat':'Few task clusters and all-equal outcomes can produce uninformative intervals.'}


def summarize_live(rows):
    groups=defaultdict(list)
    for row in rows:
        if row.get('attempted'):
            groups[row['arm']].append(row)
    result=[]
    for arm,records in sorted(groups.items()):
        successes=sum(bool(r['verified_completion']) for r in records)
        costs=[r.get('cost_usd') for r in records]
        actual_cost=sum(costs) if all(value is not None for value in costs) else None
        times=[r['wall_seconds'] for r in records]
        result.append({'arm':arm,'completion':ratio(successes,len(records)),
            'completion_interval':wilson(successes,len(records)),
            'total_tokens':sum(r.get('total_tokens',0) for r in records) if all(r.get('total_tokens') is not None for r in records) else None,
            'model_calls':sum(r.get('model_calls',0) for r in records) if all(r.get('model_calls') is not None for r in records) else None,
            'provider_attempts':sum(r.get('provider_attempts',0) for r in records) if all(r.get('provider_attempts') is not None for r in records) else None,
            'retries':sum(r.get('provider_retries',0) for r in records) if all(r.get('provider_retries') is not None for r in records) else None,
            'cost_usd':actual_cost,'cost_per_verified_completion_usd':actual_cost/successes if actual_cost is not None and successes else None,
            'p50_seconds':percentile(times,.5),'p95_seconds':percentile(times,.95),
            **{key:sum(r[key] for r in records) if all(r.get(key) is not None for r in records) else None
               for key in ('regenerated_artifacts','reused_artifacts','eligible_reuse_artifacts',
                           'acceptance_failures','safety_failures')},
            'known_safety_failures':sum(r.get('safety_failures') or 0 for r in records),
            'safety_evidence_complete':all(r.get('safety_failures') is not None for r in records)})
    return {'arms':result,'paired_f0_vs_b0':paired_difference(rows),
            'planned_or_blocked_runs':sum(not r.get('attempted') for r in rows)}
