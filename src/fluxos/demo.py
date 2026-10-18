"""Deterministic *mechanics* demonstration. No simulated claims of LLM execution."""
from __future__ import annotations
from pathlib import Path
import shutil
from .kernel import Memory, Principal

DEMO = Principal("demo-engine","demo",1,frozenset({"reader","writer","coordinator"}))


def _write(work:Path, name:str, data:str):
    work.mkdir(parents=True,exist_ok=True)
    (work/name).write_text(data,encoding="utf8")


def bootstrap(home:Path)->dict:
    # Explicit reset for reproducibility; do not pass an existing user database here.
    home=Path(home)
    if home.exists():
        shutil.rmtree(home)
    memory=Memory(home)
    memory.put_fact(DEMO,"api",{"route":"/register","field":"email","auth":False})
    memory.put_fact(DEMO,"theme",{"accent":"#63e6be"})
    work=home/"workspace"
    obs=memory.observe(DEMO)
    field=obs.fact("api","/field")
    _write(work,"frontend.ts",f"// Frontend compiled against schema field: {field}\nexport const fieldName = '{field}';\n")
    memory.put_artifact(DEMO,"frontend",{"file":"frontend.ts","field":field},obs.manifest())
    obs=memory.observe(DEMO)
    front=obs.artifact("frontend")
    _write(work,"integration.spec.ts",f"// Contract test expects {front['field']}\n")
    memory.put_artifact(DEMO,"integration",{"file":"integration.spec.ts","field":front["field"]},obs.manifest())
    obs=memory.observe(DEMO)
    accent=obs.fact("theme","/accent")
    _write(work,"styles.css",f":root {{ --accent: {accent}; }}\n")
    memory.put_artifact(DEMO,"styles",{"file":"styles.css","accent":accent},obs.manifest())
    for task in ("Generate frontend from API contract","Generate integration tests","Build independent theme"):
        job=memory.create_job("demo","demo-engine",task)
        memory.set_job(job,"COMPLETED")
    return snapshot(home)


def mutate(home:Path,field="student_id")->dict:
    if not field.isidentifier() or len(field)>40:
        raise ValueError("field must be short identifier")
    memory=Memory(home)
    memory.put_fact(DEMO,"api",{"route":"/register","field":field,"auth":False})
    return snapshot(home)


def repair(home:Path)->dict:
    memory=Memory(home)
    work=Path(home)/"workspace"
    obs=memory.observe(DEMO)
    field=obs.fact("api","/field")
    _write(work,"frontend.ts",f"// Rebuilt against schema field: {field}\nexport const fieldName = '{field}';\n")
    memory.put_artifact(DEMO,"frontend",{"file":"frontend.ts","field":field},obs.manifest())
    obs=memory.observe(DEMO)
    front=obs.artifact("frontend")
    _write(work,"integration.spec.ts",f"// Rebuilt contract test expects {front['field']}\n")
    memory.put_artifact(DEMO,"integration",{"file":"integration.spec.ts","field":front['field']},obs.manifest())
    return snapshot(home)


def snapshot(home:Path)->dict:
    memory=Memory(home)
    graph=memory.graph("demo")
    statuses={n["id"]:memory.status(DEMO,n["id"]) for n in graph["nodes"]}
    work=Path(home)/"workspace"
    files={p.name:p.read_text() for p in work.glob("*.*") if p.is_file()} if work.exists() else {}
    return {"graph":graph,"statuses":statuses,"timeline":memory.timeline(30),
            "jobs":memory.jobs("demo"),"files":files,
            "mechanical_demo":True,"llm_used":False}
