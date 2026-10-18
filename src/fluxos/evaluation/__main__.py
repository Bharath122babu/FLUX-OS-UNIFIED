"""Reproducible evaluation CLI. Live calls require an explicit --execute."""
import argparse
import json
from pathlib import Path

from .budget import Limits
from .common import write_json
from .deterministic import run
from .live import make_plan, run_plan
from .tasks import catalog

PILOT = ('coord-api-contract','coord-disjoint-edits','dev-regression-fix','attack-fake-test-output')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    deterministic=commands.add_parser('deterministic',help='Run A/B/C/E without model calls')
    deterministic.add_argument('--output',type=Path,required=True)
    deterministic.add_argument('--seeds',type=int,nargs='+',default=[11,29,47])
    deterministic.add_argument('--writers',type=int,nargs='+',default=[1,2,5,10,20,50])
    deterministic.add_argument('--nodes',type=int,default=24)
    deterministic.add_argument('--no-crashes',action='store_true')
    commands.add_parser('catalog',help='Print the 20 controlled task definitions')
    for name in ('plan','run'):
        command=commands.add_parser(name)
        command.add_argument('--output',type=Path,required=True)
        command.add_argument('--full',action='store_true',help='Select all 20 tasks; default is the approved four-task pilot')
        command.add_argument('--tasks',nargs='+')
        command.add_argument('--arms',nargs='+',default=['B0','F0'])
        command.add_argument('--trials',type=int,default=1)
        command.add_argument('--seed',type=int,default=20261018)
        command.add_argument('--model',default='gemma-4-26b-a4b-it')
        command.add_argument('--mode',choices=['live','scripted'],default='live')
        command.add_argument('--calls',type=int,default=24)
        command.add_argument('--tokens',type=int,default=80000)
        command.add_argument('--seconds',type=float,default=600)
        if name=='run':command.add_argument('--execute',action='store_true',help='Required to permit API calls')
    args=parser.parse_args()
    if args.command=='catalog':
        print(json.dumps(catalog(),indent=2));return 0
    if args.command=='deterministic':
        if args.output.exists():parser.error('output already exists; preserve previous evidence')
        result=run(seeds=args.seeds,writers=args.writers,nodes=args.nodes,crashes=not args.no_crashes)
        write_json(args.output,result)
        print(json.dumps(result['summary'],indent=2))
        return 0 if result['summary']['hard_safety_gate_passed'] else 1
    if args.command=='run' and args.mode=='live' and not args.execute:
        parser.error('live execution requires --execute; use plan to inspect the randomized schedule first')
    plan=make_plan(task_ids=args.tasks or (None if args.full else PILOT),arms=args.arms,trials=args.trials,
        seed=args.seed,limits=Limits(model_calls=args.calls,total_tokens=args.tokens,wall_seconds=args.seconds),
        model=args.model,mode=args.mode)
    if args.command=='plan':
        if args.output.exists():parser.error('output already exists')
        write_json(args.output,plan)
        print(f"Saved {len(plan['runs'])} scheduled runs to {args.output}")
        return 0
    result=run_plan(plan,args.output)
    print(json.dumps(result['summary'],indent=2))
    if any(not row.get('attempted') for row in result['rows']):return 2
    return 0 if all(row['verified_completion'] for row in result['rows']) else 1


if __name__=='__main__':raise SystemExit(main())
