"""Evaluation integrity tests; mocked acceptance is never published as live evidence."""
from dataclasses import replace
import json
from time import perf_counter

import httpx
import pytest

from fluxos.agent import Workspace
from fluxos.evaluation.budget import BudgetExceeded, Limits, MeteredGemma
from fluxos.evaluation.common import write_json
from fluxos.evaluation.deterministic import run, _reject
from fluxos.evaluation.live import execute_task, make_plan, run_plan
from fluxos.evaluation.metrics import paired_difference, ratio, summarize_live
from fluxos.evaluation.tasks import catalog, affected_units, contracts


def test_empty_denominators_and_paired_failures():
    assert ratio(0,0)['rate'] is None
    rows=[dict(task_id='one',trial=0,arm=arm,attempted=True,verified_completion=value,
        wall_seconds=2,total_tokens=None,cost_usd=None) for arm,value in [('B0',False),('F0',True)]]
    summary=summarize_live(rows)
    assert summary['paired_f0_vs_b0']['difference_pp']==100
    assert summary['arms'][0]['completion']==ratio(0,1)
    assert summary['arms'][0]['cost_per_verified_completion_usd'] is None
    assert summary['arms'][0]['safety_failures'] is None
    assert summary['arms'][0]['safety_evidence_complete'] is False
    assert paired_difference([dict(task_id='blocked',trial=0,arm='B0',attempted=False)])['paired_runs']==0


def test_wrong_exception_is_not_a_successful_rejection():
    def broken():raise RuntimeError('unexpected failure')
    row=_reject('A','probe',broken,ValueError)
    assert row['passed'] is False and row['status']=='UNEXPECTED_ERROR'
    assert row['false_accept'] is False


def test_small_matrix_and_actual_process_crash_boundaries():
    result=run(seeds=(17,),writers=(1,2,5),nodes=7)
    assert result['summary']['hard_safety_gate_passed']
    assert len(result['concurrency_groups'])==9
    assert len([r for r in result['rows'] if r['category'].startswith('crash_')])==4
    assert result['summary']['metrics']['lost_update_rate']['numerator']==0
    boundary=result['summary']['limitations'][0]
    assert boundary['passed'] is None and boundary['status']=='BOUNDARY_LIMITATION'


def test_catalog_and_randomized_balanced_full_plan():
    tasks=catalog()
    assert len(tasks)==20 and len({t['id'] for t in tasks})==20
    assert [sum(t['category']==c for t in tasks) for c in ('coordination','development','adversarial')]==[8,8,4]
    plan=make_plan(arms=('B0','B1','F0','F1'),trials=3)
    assert len(plan['runs'])==240
    assert plan['runs']==make_plan(arms=('B0','B1','F0','F1'),trials=3)['runs']
    assert set(contracts(tasks[0],0))=={'engine.py','formatter.py','project'}
    assert all(len(t['hash'])==64 for t in tasks)


def test_blocked_runs_do_not_call_provider_or_enter_completion_denominator(tmp_path,monkeypatch):
    import fluxos.evaluation.live as live
    monkeypatch.setattr(live,'readiness',lambda:{'daemon':False,'python_image':None,'node_image':None})
    def forbidden(_):pytest.fail('provider must not be constructed before Docker readiness')
    result=run_plan(make_plan(task_ids=[catalog()[0]['id']]),tmp_path/'blocked',client_factory=forbidden)
    assert all(not r['attempted'] and r['verified_completion'] is None for r in result['rows'])
    assert result['summary']['arms']==[]
    assert result['summary']['paired_f0_vs_b0']['difference_pp'] is None


def test_unit_reuse_and_baseline_restart_with_synthetic_gate_only(tmp_path,monkeypatch):
    def synthetic(self,contract_dir,**kwargs):
        return {'status':'PASS','test_count':1,'trust_boundary':'blackbox','contract_hash':'UNIT_TEST_ONLY',
                'candidate_manifest_hash':self.manifest_digest()}
    monkeypatch.setattr(Workspace,'run_blackbox',synthetic)
    task=next(t for t in catalog() if t['id']=='dev-regression-fix')
    assert affected_units(task)=={'formatter.py'}
    results=[execute_task(task,arm,0,tmp_path/arm,Limits(),'', 'scripted') for arm in ('B0','F0')]
    assert all(r['verified_completion'] for r in results)
    assert [r['regenerated_artifacts'] for r in results]==[4,3]
    assert [r['reused_artifacts'] for r in results]==[0,1]
    assert all(r['real_model_calls']==0 for r in results)


def test_live_budget_reservation_retries_and_unknown_billing():
    attempts=[]
    def provider(req):
        if req.url.path.endswith(':countTokens'):return httpx.Response(200,json={'totalTokens':20})
        attempts.append(1)
        if len(attempts)==1:return httpx.Response(503,json={})
        return httpx.Response(200,json={'usageMetadata':{'totalTokenCount':25},
            'candidates':[{'content':{'parts':[{'text':'done'}]}}]})
    client=MeteredGemma(Limits(total_tokens=200,output_tokens=30),key='UNIT_TEST_ONLY',transport=httpx.MockTransport(provider))
    client.generate([],[],'test')
    summary=client.summary()
    assert summary['provider_attempts']==2 and summary['provider_retries']==1
    assert summary['total_tokens'] is None and summary['budget_charged_tokens']==75
    assert summary['observed_known_tokens']==25
    assert 'UNIT_TEST_ONLY' not in json.dumps(summary)
    limited=MeteredGemma(Limits(total_tokens=20),key='UNIT_TEST_ONLY',transport=httpx.MockTransport(provider))
    with pytest.raises(BudgetExceeded):limited.generate([],[],'test')
    assert limited.summary()['provider_attempts']==0


def test_acceptance_deadline_prevents_container_launch(tmp_path,monkeypatch):
    import fluxos.agent as agent
    workspace=Workspace(tmp_path/'code');workspace.write_file('main.py','print(42)\n')
    write_json(tmp_path/'contracts'/'cases.json',{'entry':'main.py','cases':[{'stdin':'','stdout':'42\n'}]})
    monkeypatch.setattr(agent.shutil,'which',lambda _: 'docker')
    def forbidden(*args,**kwargs):pytest.fail('expired deadline launched a process')
    monkeypatch.setattr(agent.subprocess,'run',forbidden)
    assert workspace.run_blackbox(tmp_path/'contracts',deadline=perf_counter()-1)['status']=='TIMEOUT'


def test_dashboard_pending_results_and_pooled_latency():
    from fluxos.evaluation.report import snapshot
    result=run(seeds=(5,),writers=(1,2),nodes=4,crashes=False)
    reviewed=snapshot(result)
    headlines={r['key']:r for r in reviewed['queries']['headlines']['rows']}
    assert headlines['completion']['value'] is None and headlines['cost']['value'] is None
    assert headlines['stale']['numerator']==0 and headlines['stale']['denominator']>0
    assert all(r['p95_ms']>=r['p50_ms'] for r in reviewed['queries']['concurrency']['rows'])
    live_rows=[dict(task_id='task',trial=0,arm=arm,attempted=True,verified_completion=complete,
        wall_seconds=3,total_tokens=50,cost_usd=None,status='VERIFIED' if complete else 'FAILED')
        for arm,complete in [('B0',False),('F0',True)]]
    live_snapshot=snapshot(result,{'summary':summarize_live(live_rows),'rows':live_rows,'generated_at':'2026-10-18T07:00:00Z'})
    live_headline=next(r for r in live_snapshot['queries']['headlines']['rows'] if r['key']=='completion')
    assert 'B0 0/1; F0 1/1' in live_headline['detail']
    assert live_snapshot['queries']['live_runs']['source']['executedAt']=='2026-10-18T07:00:00Z'
