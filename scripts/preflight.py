"""Readiness report that never calls a provider or prints API credentials."""
import json
import os
import shutil
import subprocess
import sys

from fluxos import __version__
from fluxos.agent import MODEL


def run():
    docker=shutil.which('docker')
    daemon=False
    images={name:False for name in ('python:3.12-alpine','node:22-alpine')}
    if docker:
        try:
            daemon=subprocess.run([docker,'info'],capture_output=True,timeout=15).returncode==0
            if daemon:
                for name in images:
                    images[name]=subprocess.run([docker,'image','inspect',name],
                        capture_output=True,timeout=10).returncode==0
        except (OSError,subprocess.TimeoutExpired):
            pass
    key_present=bool(os.getenv('GEMINI_API_KEY'))
    return {'version':__version__,'python':sys.version.split()[0],
            'model':os.getenv('GEMMA_MODEL') or MODEL,'gemini_key_present':key_present,
            'docker_cli_present':bool(docker),'docker_daemon_ready':daemon,
            'images':images,'live_acceptance_prerequisites_present':key_present and daemon and images['python:3.12-alpine'],
            'provider_access_verified':False,'provider_requests_made':0}


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
