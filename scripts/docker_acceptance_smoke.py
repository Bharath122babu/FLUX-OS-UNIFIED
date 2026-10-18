"""Real Docker + scripted model API smoke; no cloud requests or credentials.

Requires preloaded python:3.12-alpine and node:22-alpine images. This verifies
ordinary runtime behavior, not adversarial container security certification.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from fluxos.agent import Workspace
from fluxos.api import create_app


SOURCE='import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)\n'
CONTRACT={'entry':'main.py','cases':[
    {'stdin':'2 3\n','stdout':'5\n','exit_code':0},
    {'stdin':'-5 7\n','stdout':'2\n','exit_code':0},
    {'stdin':'10 25\n','stdout':'35\n','exit_code':0},
]}


class ScriptedModel:
    model='SCRIPTED_MODEL_LIVE_DOCKER'
    def generate(self,contents,tools,system):
        if len(contents)==1:
            calls=[('read_shared_memory',{'pointer':'/implementation'})]
        elif len(contents)==3:
            note=contents[-1]['parts'][0]['functionResponse']['response']['result']
            calls=[]
            if not note['present']:
                calls.append(('patch_shared_memory',{'changes':[{
                    'path':'/implementation','expected_hash':None,'value':'sum two integers'}]}))
            calls.append(('write_file',{'path':'main.py','content':SOURCE}))
        else:
            return {'parts':[{'text':'Scripted candidate ready for independent acceptance.'}]}
        return {'parts':[{'functionCall':{'name':name,'args':args}} for name,args in calls]}


def run() -> dict:
    subprocess.run(['docker','info'],check=True,capture_output=True,timeout=30)
    with TemporaryDirectory(prefix='fluxos-docker-smoke-') as directory:
        root=Path(directory)
        work=Workspace(root/'commands')
        python=work.execute_command(['python','-c','print("python-ready")'])
        assert python['status']=='COMPLETED',python
        assert python['stdout']=='python-ready\n',python
        node=work.execute_command(['node','-e','process.stdout.write("node-ready\\n")'],runtime='node')
        assert node['status']=='COMPLETED',node
        assert node['stdout']=='node-ready\n',node
        home=root/'server'
        contract=home/'acceptance'/'docker-smoke'/'cases.json'
        contract.parent.mkdir(parents=True)
        contract.write_text(json.dumps(CONTRACT),encoding='utf8')
        with patch('fluxos.api.GemmaClient',ScriptedModel):
            client=TestClient(create_app(home))
            for revision in (1,2):
                response=client.post('/api/gemma/run',json={
                    'project_id':'docker-smoke','task':'Build a Python CLI that sums two integers.'})
                assert response.status_code==200,response.text
                result=response.json()
                assert result['status']=='VERIFIED',result
                assert result['acceptance']['test_count']==3,result
                assert result['project_base_revision']==revision-1,result
            head=client.get('/api/projects/docker-smoke').json()
            assert head['head']['revision']==2,head
            assert len(head['history'])==2,head
            notes=client.get('/api/projects/docker-smoke/memory').json()
            assert notes['notes']=={'implementation':'sum two integers'},notes
            exported=client.get('/api/projects/docker-smoke/export')
            assert exported.status_code==200,exported.text
            with ZipFile(io.BytesIO(exported.content)) as archive:
                assert archive.read('main.py')==SOURCE.encode('utf8')
        # A failing real acceptance case must never be described as passing.
        work.write_file('main.py',SOURCE)
        bad=root/'bad-contract';bad.mkdir()
        (bad/'cases.json').write_text(json.dumps({'entry':'main.py','cases':[
            {'stdin':'2 3\n','stdout':'incorrect\n','exit_code':0}]}),encoding='utf8')
        assert work.run_blackbox(bad)['status']=='FAIL'
    return {'result':'PASS','python_command':'PASS','node_command':'PASS',
            'accepted_revisions':2,'accepted_cases_per_revision':3,
            'shared_notes_reused':True,'zip_export':'PASS','wrong_stdout_rejected':True,
            'real_model_calls':0,'model':'SCRIPTED_MODEL_LIVE_DOCKER',
            'security_certification':False}


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
