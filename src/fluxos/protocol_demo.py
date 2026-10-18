"""Small, real shared-memory conflict demonstration used by the local UI."""
from __future__ import annotations
from tempfile import TemporaryDirectory
from pathlib import Path
from .kernel import Memory, Principal, Stale, digest

def run_conflict_test() -> dict:
    baseline={"decision":"INITIAL"}
    baseline["decision"]="KEEP_API_V1"
    baseline["decision"]="REPLACE_API_V2"
    with TemporaryDirectory(prefix="flux-protocol-") as td:
        memory=Memory(Path(td)/"state")
        root=Principal("operator","ui-demo",2,frozenset({"reader","writer","coordinator"}))
        worker_a=Principal("worker-a","ui-demo",1,frozenset({"reader","writer","agent"}))
        worker_b=Principal("worker-b","ui-demo",1,frozenset({"reader","writer","agent"}))
        memory.put_fact(root,"decision",{"value":"INITIAL"})
        observed_a=memory.observe(worker_a); observed_a.fact("decision","/value")
        observed_b=memory.observe(worker_b); observed_b.fact("decision","/value")
        a="COMMITTED"
        b="COMMITTED"
        memory.patch_fact(worker_a,"decision",[{"path":"/value","expected_hash":digest("INITIAL"),"value":"KEEP_API_V1"}],read_manifest=observed_a.manifest())
        try:
            memory.patch_fact(worker_b,"decision",[{"path":"/value","expected_hash":digest("INITIAL"),"value":"REPLACE_API_V2"}],read_manifest=observed_b.manifest())
        except Stale:
            b="STALE_REJECTED"
        final=memory.fact_head(root,"decision")["value"]["value"]
    return {"baseline":{"worker_a":"WRITE_OK","worker_b":"WRITE_OK","final_value":baseline["decision"],"lost_update":True},"flux":{"worker_a":a,"worker_b":b,"final_value":final,"lost_update":False},"result":"PASS" if b=="STALE_REJECTED" and final=="KEEP_API_V1" else "FAIL"}
