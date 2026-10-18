"""Deterministic hostile schedules for the FLUX v0.6 shared-memory kernel.

Not an LLM benchmark.  No external APIs, Docker, or hidden background work.
Run: PYTHONPATH=src python scripts/shared_memory_stress.py
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import json
import random

from fluxos.kernel import Memory, Principal, Stale, digest


def run(seed: int = 271828, workers: int = 20, trials: int = 12) -> dict:
    started = perf_counter()
    with TemporaryDirectory(prefix='flux06-stress-') as td:
        m=Memory(Path(td)/'state')
        root=Principal('operator','stress',2,frozenset({'reader','writer','coordinator'}))
        actors=[Principal(f'agent-{i}','stress',1,frozenset({'reader','writer','agent'})) for i in range(workers)]
        rng=random.Random(seed)
        passed=0
        for trial in range(trials):
            key=f'state-{trial}'
            initial={f'field{i}':0 for i in range(workers)}
            m.put_fact(root,key,initial)
            schedules=[]
            for i, actor in enumerate(actors):
                observed=m.observe(actor)
                assert observed.fact(key, f'/field{i}')==0
                schedules.append((i,actor,observed.manifest()))
            rng.shuffle(schedules)
            def update(info):
                i,actor,manifest=info
                return m.patch_fact(actor,key,[{
                    'path':f'/field{i}','expected_hash':digest(0),'value':i+1
                }],read_manifest=manifest)
            with ThreadPoolExecutor(max_workers=min(workers,20)) as pool:
                versions=list(pool.map(update,schedules))
            if sorted(versions)!=list(range(2,workers+2)):
                raise AssertionError('unexpected version order')
            expected={f'field{i}':i+1 for i in range(workers)}
            if m.fact_head(root,key)['value']!=expected:
                raise AssertionError('independent edit lost')
            passed+=1
        # Exactly one competing edit wins the same preimage.
        m.put_fact(root,'contested',{'value':0})
        def contender(i):
            try:
                m.patch_fact(actors[i],'contested',[{
                    'path':'/value','expected_hash':digest(0),'value':i+1}])
                return True
            except Stale:
                return False
        with ThreadPoolExecutor(max_workers=min(workers,20)) as pool:
            results=list(pool.map(contender,range(workers)))
        if sum(results)!=1:
            raise AssertionError('expected exactly one same-key winner')
        return {'seed':seed,'agents':workers,'trials':trials,
                'disjoint_edits_preserved':workers*trials,
                'lost_updates':0,'same_field_winners':sum(results),
                'same_field_conflicts':workers-sum(results),
                'elapsed_seconds':round(perf_counter()-started,3),
                'real_model_calls':0,'result':'PASS'}


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
