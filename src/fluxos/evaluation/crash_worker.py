"""Trusted fault-injection fixture; deliberately exits inside publication boundaries."""
import argparse
import os
from pathlib import Path

from .common import context
from ..agent import Workspace
from ..gateway import UnifiedGate


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',required=True)
    parser.add_argument('--phase',required=True,choices=['after_seal','before_db_commit','after_db_commit','after_effect'])
    args=parser.parse_args()
    home=Path(args.home).resolve()
    memory,root,worker=context(home,'crash')
    job=memory.create_job('crash',worker.name,'crash fixture',actor=worker)
    generation=memory.set_job(job,'RUNNING',actor=worker)
    if args.phase=='after_effect':
        (home/'effect_receipt.txt').write_text('effect performed once',encoding='utf8')
        os._exit(76)
    candidate=Workspace(home/'candidate')
    candidate.write_file('main.py','print(42)\n')
    def acceptance(sealed):
        if args.phase=='after_seal':os._exit(73)
        return {'status':'PASS','test_count':1,'trust_boundary':'blackbox','contract_hash':'synthetic-crash-oracle',
                'candidate_manifest_hash':sealed.manifest_digest()}
    if args.phase=='before_db_commit':
        original=memory._record
        def before_commit(connection,kind,**details):
            original(connection,kind,**details)
            if kind=='artifact.committed':os._exit(74)
        memory._record=before_commit
    if args.phase=='after_db_commit':
        original=memory.put_artifact
        def after_commit(*args,**kwargs):
            original(*args,**kwargs)
            os._exit(75)
        memory.put_artifact=after_commit
    UnifiedGate(memory,worker).publish(candidate=candidate,baseline=None,base_manifest={},
        observation=memory.observe(worker),developer={},acceptance={},model='SYNTHETIC_CRASH_FIXTURE',calls=0,
        output_id='result:'+job,job_id=job,generation=generation,project_id='crash',base_revision=0,
        trusted_acceptance=acceptance)
    raise RuntimeError('Fault injection did not terminate its subprocess')


if __name__=='__main__':main()
