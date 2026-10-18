"""Real container validation of the evaluator, without API calls or AI claims."""
import json
from pathlib import Path
import tempfile

from fluxos.evaluation.live import make_plan, run_plan


def main():
    with tempfile.TemporaryDirectory(prefix='fluxos-evaluation-docker-') as home:
        result=run_plan(make_plan(task_ids=['dev-regression-fix'],mode='scripted'),Path(home)/'paired')
        assert all(r.get('attempted') and r['verified_completion'] for r in result['rows']),json.dumps(result)
        arms={r['arm']:r for r in result['rows']}
        assert arms['B0']['regenerated_artifacts']==4
        assert arms['F0']['regenerated_artifacts']==3 and arms['F0']['reused_artifacts']==1
        assert result['summary']['arms']==[] and result['scripted_validation_rows']==2
        print('Docker-backed paired orchestration passed: B0=4 regenerations, F0=3 + 1 reuse. Zero real model calls.')


if __name__=='__main__':main()
