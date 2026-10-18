"""Local hackathon development console. Not intended for public internet exposure."""
from __future__ import annotations
import os
import base64
import binascii
import io
import zipfile
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from .kernel import Memory,Principal
from .agent import GemmaClient,GemmaAgent,Workspace,ConfigError,MODEL
from .shared import project_memory_key
from . import __version__
from . import demo

class Change(BaseModel):
    field: str = Field(default="student_id",min_length=1,max_length=40,pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")

class Goal(BaseModel):
    task: str = Field(min_length=5,max_length=1500)
    project_id: str = Field(default="my-project",pattern=r"^[A-Za-z0-9_-]{1,64}$")
    image_base64: str | None = Field(default=None,max_length=2_700_000)
    image_mime: str | None = None


def create_app(home: str|Path=".fluxos") -> FastAPI:
    home=Path(home).resolve()
    home.mkdir(parents=True,exist_ok=True)
    app=FastAPI(title="FLUX//OS",description="Local research backend",version=__version__)
    demo_home=home/"causal_demo"
    gemma_home=home/"gemma_workspace"
    acceptance_root=home/"acceptance"

    @app.middleware("http")
    async def local_only(request:Request,call_next):
        # Defense in depth; host launch remains bound to 127.0.0.1.
        peer=request.client.host if request.client else ""
        if peer not in {"127.0.0.1","::1","testclient"}:
            return __import__("fastapi").responses.JSONResponse(status_code=403,
                content={"detail":"Local loopback development only"})
        origin=request.headers.get("origin")
        host=request.headers.get("host", "")
        # IPv6 Host headers are bracketed: [::1]:8765.
        host_only=(host[1:].split("]",1)[0] if host.startswith("[")
                   else host.split(":",1)[0]).lower()
        if host_only not in {"127.0.0.1","localhost","testserver","::1"}:
            return __import__("fastapi").responses.JSONResponse(status_code=403,
                content={"detail":"Unexpected host header"})
        if origin and origin.rstrip("/") != "http://"+host:
            # An arbitrary localhost PORT is not the same origin.
            return __import__("fastapi").responses.JSONResponse(status_code=403,
                content={"detail":"Cross-origin dashboard requests denied"})
        if request.method in {"POST","PUT","PATCH","DELETE"}:
            # Browser navigations without Origin are not accepted for mutations.
            # Non-browser clients require a local-only pairing token in the
            # deployed version; this build is loopback demonstration only.
            if origin and origin.rstrip("/") != "http://"+host:
                return __import__("fastapi").responses.JSONResponse(status_code=403,
                    content={"detail":"Cross-origin mutation denied"})
        return await call_next(request)

    @app.get('/')
    def index():
        return {'service':'FLUX//OS unified backend','status':'development-only',
                'api_docs':'/docs','health':'/api/health'}

    @app.get("/api/health")
    def health():
        return {"running":True,"gemma_key_present":bool(os.getenv("GEMINI_API_KEY")),
                "model":os.getenv('GEMMA_MODEL') or MODEL,"version":__version__,
                "causal_demo_present":(demo_home/"state.sqlite3").exists(),
                "mode":"LOCAL_DEVELOPMENT_ONLY"}

    @app.get("/api/demo")
    def snapshot():
        if not (demo_home/"state.sqlite3").exists():
            return demo.bootstrap(demo_home)
        return demo.snapshot(demo_home)

    @app.post("/api/demo/reset")
    def reset():return demo.bootstrap(demo_home)

    @app.post("/api/demo/change")
    def change(params:Change):
        if not (demo_home/"state.sqlite3").exists():demo.bootstrap(demo_home)
        return demo.mutate(demo_home,params.field)

    @app.post("/api/demo/repair")
    def repair():
        if not (demo_home/"state.sqlite3").exists():raise HTTPException(400,"Initialize first")
        return demo.repair(demo_home)

    def project_reader():
        return Memory(home/"gemma_state"), Principal("gemma-worker","gemma-demo",1,frozenset({"reader","writer","agent"}))

    @app.get("/api/projects/{project_id}")
    def get_project(project_id:str):
        mem,actor=project_reader()
        try:
            head=mem.project_head(actor,project_id)
            return {"project_id":project_id,"head":{k:v for k,v in head.items() if k!="snapshot_path"} if head else None,
                    "history":mem.project_history(actor,project_id)}
        except ValueError as exc:
            raise HTTPException(422,str(exc))
        except (Exception,) as exc:
            raise HTTPException(409,f"Project unavailable: {type(exc).__name__}")

    @app.get("/api/projects/{project_id}/export")
    def export_project(project_id:str):
        mem,actor=project_reader()
        try:
            head=mem.project_head(actor,project_id)
            if head is None:raise HTTPException(404,"No accepted project revision")
            base=Path(head["snapshot_path"])
            data=io.BytesIO()
            with zipfile.ZipFile(data,"w",zipfile.ZIP_DEFLATED) as archive:
                for name in sorted(head["files"]):
                    archive.write(base/name,arcname=name)
            data.seek(0)
            return StreamingResponse(data,media_type="application/zip",headers={
                "Content-Disposition":f'attachment; filename="{project_id}-r{head["revision"]}.zip"'})
        except HTTPException:raise
        except (ValueError,Exception) as exc:
            raise HTTPException(409,f"Project unavailable: {type(exc).__name__}")

    @app.get("/api/projects/{project_id}/memory")
    def project_memory(project_id:str):
        mem,actor=project_reader()
        try:
            key=project_memory_key(project_id)
            head=mem.fact_head(actor,key)
            return {"project_id":project_id,"version":head['version'],
                    "notes":head['value'],"trust":"UNVERIFIED_SHARED_NOTES"}
        except KeyError:
            return {"project_id":project_id,"version":0,"notes":{},
                    "trust":"UNVERIFIED_SHARED_NOTES"}
        except ValueError as exc:
            raise HTTPException(422,str(exc))
        except Exception as exc:
            raise HTTPException(409,f"Shared memory unavailable: {type(exc).__name__}")

    @app.get('/api/jobs/{job_id}/events')
    def job_events(job_id:str):
        mem,actor=project_reader()
        try:
            job=mem.get_job(job_id)
            if job['scope']!=actor.scope:raise HTTPException(404,'Job not found')
            return {'job_id':job_id,'state':job['state'],
                    'events':mem.execution_history(job_id)}
        except KeyError:raise HTTPException(404,'Job not found')

    @app.post("/api/gemma/run")
    def gemma_run(params:Goal):
        try:
            client=GemmaClient()
        except ConfigError as e:
            raise HTTPException(422,str(e))
        mem,actor=project_reader()
        try:
            accepted=mem.project_head(actor,params.project_id)
        except (ValueError,Exception) as exc:
            raise HTTPException(409,f"Project head invalid: {type(exc).__name__}")
        base_revision=accepted["revision"] if accepted else 0
        job=mem.create_job(actor.scope,actor.name,params.task,actor=actor)
        mem.put_fact(actor,"task:"+job,{"goal":params.task},expected_version=0)
        mem.set_job(job,"RUNNING",actor=actor)
        try:
            image=None
            if params.image_base64:
                if params.image_mime not in {"image/jpeg","image/png","image/webp"}:
                    raise HTTPException(422,"Unsupported image MIME type")
                try:
                    raw=base64.b64decode(params.image_base64,validate=True)
                except (ValueError,binascii.Error):
                    raise HTTPException(422,"Invalid base64 image")
                if len(raw)>2_000_000:
                    raise HTTPException(422,"Image limit is 2 MB")
                image=(raw,params.image_mime)
            workspace=Workspace(gemma_home/job)
            if accepted:
                Workspace(Path(accepted["snapshot_path"])).snapshot_to(workspace)
            agent=GemmaAgent(client,mem,actor,workspace,"task:"+job,
                              root_job=job,project_id=params.project_id,
                              base_revision=base_revision,
                              base_output_id=accepted["output_id"] if accepted else None,
                              acceptance_dir=(acceptance_root/params.project_id)
                                  if (acceptance_root/params.project_id/"cases.json").is_file() else None)
            result=agent.run(params.task,image=image)
            mem.set_job(job,"COMPLETED" if result["status"]=="VERIFIED" else
                        "DRAFT" if result["status"]=="DRAFT" else "FAILED",actor=actor)
            result["job_id"]=job
            result["project_id"]=params.project_id
            result["project_base_revision"]=base_revision
            return result
        except HTTPException:
            if mem.get_job(job)["state"]=="RUNNING":mem.set_job(job,"FAILED",actor=actor)
            raise
        except Exception as e:
            if mem.get_job(job)["state"]=="RUNNING":mem.set_job(job,"FAILED",actor=actor)
            raise HTTPException(500,f"Agent failed: {type(e).__name__}: {str(e)[:250]}")

    return app

