"""Real file-hash dependency demonstration (NOT an LLM inference benchmark)."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from .kernel import Memory, Principal
from .agent import Workspace


def run(home:Path|str|None=None)->dict:
    temporary=None
    if home is None:
        temporary=TemporaryDirectory(prefix='fluxos-unified-')
        home=Path(temporary.name)
    home=Path(home)
    if (home/'state'/'state.sqlite3').exists():
        raise ValueError('Refusing to overwrite existing state; choose an empty demo directory')
    repo=Workspace(home/'project');repo.write_file('api.py',"FIELD = 'email'\n")
    repo.write_file('styles.css','body { color: navy; }\n')
    memory=Memory(home/'state')
    actor=Principal('example-coordinator','unified-demo',1,frozenset({'reader','writer','coordinator'}))
    source='repo:sample:tree'
    memory.register_source_tree(actor,source,repo.file_manifest())
    frontend=memory.observe(actor)
    frontend.fact(source,'/names')
    frontend.fact(source,'/hashes/api.py')
    memory.put_artifact(actor,'frontend',{'code':'render(email)'},frontend.manifest())
    styles=memory.observe(actor)
    styles.fact(source,'/hashes/styles.css')
    memory.put_artifact(actor,'styles',{'code':'navy'},styles.manifest())
    before={name:memory.status(actor,name) for name in ('frontend','styles')}
    repo.write_file('api.py',"FIELD = 'student_id'\n")
    memory.register_source_tree(actor,source,repo.file_manifest())
    after={name:memory.status(actor,name) for name in ('frontend','styles')}
    repaired=memory.observe(actor)
    repaired.fact(source,'/names');repaired.fact(source,'/hashes/api.py')
    memory.put_artifact(actor,'frontend',{'code':'render(student_id)'},repaired.manifest())
    final={name:memory.status(actor,name) for name in ('frontend','styles')}
    report={'demo_type':'DETERMINISTIC_FILE_HASH_DEPENDENCIES_NO_GEMMA',
            'before':before,'after_contract_change':after,'after_repair':final,
            'repaired':['frontend'],'preserved':['styles'],'model_calls':0,
            'file_witnesses':repaired.manifest()}
    if temporary is not None:temporary.cleanup()
    return report
