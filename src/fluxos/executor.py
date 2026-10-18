"""Bounded Docker-only development process execution (not production attestation)."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import secrets

IMAGES={'python':'python:3.12-alpine','node':'node:22-alpine'}

def docker_exec(workspace,argv:list[str],*,runtime:str='python',timeout:int=20,cwd:str='.') -> dict:
    if runtime not in IMAGES:raise ValueError('runtime must be python or node')
    if not isinstance(argv,list) or not 1<=len(argv)<=24 or any(
        not isinstance(x,str) or not x or len(x)>2000 or '\x00' in x for x in argv):
        raise ValueError('invalid argv')
    if type(timeout) is not int or not 1<=timeout<=45:raise ValueError('timeout must be 1..45 seconds')
    if cwd!='.':
        target=workspace.safe(cwd)
        if not target.is_dir():raise ValueError('cwd must be existing directory')
        rel=target.relative_to(workspace.path).as_posix()
    else:rel=''
    if shutil.which('docker') is None:
        return {'status':'UNAVAILABLE','reason':'Docker required, no host subprocess fallback'}
    uid=os.getuid() if hasattr(os,'getuid') and os.getuid()!=0 else 65534
    gid=os.getgid() if hasattr(os,'getgid') and os.getuid()!=0 else 65534
    name='fluxos-exec-'+secrets.token_hex(8)
    cmd=['docker','run','--pull','never','--rm','--name',name,'--network','none',
         '--memory','512m','--cpus','1','--pids-limit','96',
         '--cap-drop','ALL','--security-opt','no-new-privileges','--read-only',
         '--tmpfs','/tmp:rw,nosuid,size=64m','--user',f'{uid}:{gid}',
         '--mount',f'type=bind,src={workspace.path},dst=/work',
         '-w','/work'+('/'+rel if rel else ''),IMAGES[runtime],*argv]
    try:
        p=subprocess.run(cmd,capture_output=True,timeout=timeout,text=True,errors='replace')
        return {'status':'COMPLETED' if p.returncode==0 else 'FAILED',
                'exit_code':p.returncode,'stdout':p.stdout[-12000:],
                'stderr':p.stderr[-12000:],'truncated':len(p.stdout)>12000 or len(p.stderr)>12000}
    except subprocess.TimeoutExpired:
        try:subprocess.run(['docker','rm','-f',name],capture_output=True,text=True,timeout=8)
        except (OSError,subprocess.TimeoutExpired):pass
        return {'status':'TIMEOUT','reason':'command time limit reached'}
    except OSError as e:
        return {'status':'UNAVAILABLE','reason':type(e).__name__}
