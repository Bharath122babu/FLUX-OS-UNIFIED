"""Evidence identities, environment stamps, and immutable run directories."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

from ..kernel import Memory, Principal


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def provenance():
    source=Path(__file__).resolve().parents[3]
    def git(*args):
        try:return subprocess.check_output(['git','-C',str(source),*args],text=True,stderr=subprocess.DEVNULL).strip()
        except (OSError,subprocess.CalledProcessError):return None
    files={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted((source/'src').rglob('*.py'))}
    return {'git_commit':git('rev-parse','HEAD'),'working_tree_dirty':bool(git('status','--porcelain')),
            'source_files':files,'python':sys.version.split()[0],'platform':platform.platform(),
            'latency_clock':'time.perf_counter; milliseconds; nearest-rank p50/p95'}


def context(path,scope='bench'):
    memory=Memory(Path(path)/'state')
    root=Principal('operator',scope,2,frozenset({'reader','writer','coordinator','publisher'}))
    worker=Principal('worker',scope,1,frozenset({'reader','writer','agent'}))
    return memory,root,worker


def record(suite,category,*,seed=0,hostile=True,passed=True,status='OBSERVED',**evidence):
    return {'id':uuid.uuid4().hex,'suite':suite,'category':category,'seed':seed,
            'hostile':hostile,'passed':passed,'status':status,'observed_at':utcnow(),**evidence}


def write_json(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('w',encoding='utf8',newline='\n') as stream:
            stream.write(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()


def fresh_output(path):
    path=Path(path).resolve()
    path.mkdir(parents=True,exist_ok=False)
    return path
