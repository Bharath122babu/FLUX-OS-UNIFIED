"""Identical deterministic workload: full restart vs tracked-selective repair.
Work units, not fabricated token or model-accuracy claims.
"""
from __future__ import annotations
from pathlib import Path
import tempfile
import json
import time
from .demo import bootstrap,mutate,repair


def benchmark() -> dict:
    with tempfile.TemporaryDirectory() as d:
        home=Path(d)/"run"
        a=bootstrap(home)
        start=time.perf_counter()
        b=mutate(home,"student_id")
        changed_ms=(time.perf_counter()-start)*1000
        invalidated=sorted(k for k,v in b["statuses"].items() if v=="STALE")
        retained=sorted(k for k,v in b["statuses"].items() if v=="DECLARED_CURRENT")
        start=time.perf_counter()
        c=repair(home)
        repair_ms=(time.perf_counter()-start)*1000
        return {"name":"synthetic contract mutation","baseline_units_restarted":3,
                "flux_units_repaired":len(invalidated),
                "preserved_units":retained,"invalidated_units":invalidated,
                "all_current_after_repair":all(v=="DECLARED_CURRENT" for v in c["statuses"].values()),
                "mutation_ms_single_run":round(changed_ms,3),"repair_ms_single_run":round(repair_ms,3),
                "gemma_calls":0,"quality_improvement_claim":"NOT_MEASURED",
                "caveat":"illustrative fixed workload; not a fair latency or token benchmark versus another agent framework"}

if __name__=="__main__":print(json.dumps(benchmark(),indent=2))
