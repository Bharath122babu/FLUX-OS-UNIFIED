"""FLUX//OS causal single-host state kernel.

Important boundary: checks recorded dependencies, not truth or undisclosed I/O.
Transactions are SQLite BEGIN IMMEDIATE; intended for a single coordinator.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from contextlib import contextmanager
from collections import deque
from pathlib import Path
from typing import Any

LEVELS = {"public": 0, "internal": 1, "secret": 2}


class FluxError(Exception):
    pass


class Denied(FluxError):
    pass


class Stale(FluxError):
    pass


class IntegrityError(FluxError):
    pass


def compact(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(compact(obj).encode()).hexdigest()


def projection(obj: Any, pointer: str) -> Any:
    if pointer == "":
        return obj
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must be empty or start with /")
    for raw in pointer[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(obj, list):
            obj = obj[int(key)]
        else:
            obj = obj[key]
    return obj


@dataclass(frozen=True)
class Principal:
    name: str
    scope: str
    clearance: int
    roles: frozenset[str]


class Memory:
    def __init__(self, home: str | Path):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.db = self.home / "state.sqlite3"
        self._init()

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.db, isolation_level=None, timeout=15)
        try:
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA busy_timeout=15000")
            c.execute("PRAGMA foreign_keys=ON")
            yield c
            if c.in_transaction:
                c.commit()
        except BaseException:
            if c.in_transaction:
                c.rollback()
            raise
        finally:
            c.close()

    def _init(self):
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS facts(scope TEXT,key TEXT,version INTEGER,
              payload TEXT NOT NULL,hash TEXT NOT NULL,level INTEGER NOT NULL,author TEXT NOT NULL,
              PRIMARY KEY(scope,key,version));
            CREATE TABLE IF NOT EXISTS heads(scope TEXT,key TEXT,version INTEGER NOT NULL,
              PRIMARY KEY(scope,key));
            CREATE TABLE IF NOT EXISTS artifacts(scope TEXT,id TEXT,version INTEGER,
              payload TEXT NOT NULL,hash TEXT NOT NULL,level INTEGER NOT NULL,
              author TEXT NOT NULL,manifest TEXT NOT NULL,status TEXT NOT NULL,
              PRIMARY KEY(scope,id,version));
            CREATE TABLE IF NOT EXISTS artifact_heads(scope TEXT,id TEXT,version INTEGER NOT NULL,
              PRIMARY KEY(scope,id));
            CREATE TABLE IF NOT EXISTS deps(scope TEXT,child_id TEXT,child_version INTEGER,
              kind TEXT,source TEXT,pointer TEXT,expected_hash TEXT,expected_version INTEGER,
              expected_authority TEXT,
              PRIMARY KEY(scope,child_id,child_version,kind,source,pointer));
            CREATE INDEX IF NOT EXISTS deps_by_source ON deps(scope,kind,source);
            CREATE TABLE IF NOT EXISTS project_revisions(
                scope TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL,
                output_id TEXT NOT NULL, artifact_version INTEGER NOT NULL,
                snapshot_path TEXT NOT NULL, manifest TEXT NOT NULL, author TEXT NOT NULL,
                created REAL NOT NULL, PRIMARY KEY(scope,project_id,revision));
            CREATE TABLE IF NOT EXISTS project_heads(
                scope TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL,
                PRIMARY KEY(scope,project_id));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              ts REAL NOT NULL,kind TEXT NOT NULL,details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS execution_events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,
              step INTEGER NOT NULL,kind TEXT NOT NULL,details TEXT NOT NULL,
              created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS execution_by_job ON execution_events(job_id,seq);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, scope TEXT, task TEXT,
              state TEXT, parent_id TEXT, owner TEXT, created REAL, generation INTEGER NOT NULL DEFAULT 0);
            """)
            # Older release has no authority witnesses; legacy rows are treated as
            # uncertified rather than silently assuming authorization continuity.
            cols={row["name"] for row in c.execute("PRAGMA table_info(deps)")}
            if "expected_authority" not in cols:
                c.execute("ALTER TABLE deps ADD COLUMN expected_authority TEXT")
            jobcols={row["name"] for row in c.execute("PRAGMA table_info(jobs)")}
            if "generation" not in jobcols:
                c.execute("ALTER TABLE jobs ADD COLUMN generation INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _role(actor: Principal, role: str, scope: str, level: int = 0):
        if actor.scope != scope or actor.clearance < level or role not in actor.roles:
            raise Denied(f"actor cannot {role} in this scope/classification")

    @staticmethod
    def _record(c, kind: str, **details):
        c.execute("INSERT INTO events(ts,kind,details) VALUES(?,?,?)", (time.time(), kind, compact(details)))

    def _put_fact_tx(self, c, actor: Principal, key: str, payload: str,
                     lvl: int, old=None) -> int:
        """One canonical fact publication transition; caller owns BEGIN IMMEDIATE."""
        if old is None:
            old = c.execute("SELECT h.version,f.level FROM heads h JOIN facts f ON "
                            "(h.scope=f.scope AND h.key=f.key AND h.version=f.version) "
                            "WHERE h.scope=? AND h.key=?", (actor.scope, key)).fetchone()
        if old:
            self._role(actor, "writer", actor.scope, old["level"])
            if lvl < old["level"] and "declassifier" not in actor.roles:
                raise Denied("classification downgrade requires declassifier")
        version = (old["version"] if old else 0) + 1
        c.execute("INSERT INTO facts VALUES(?,?,?,?,?,?,?)",
                  (actor.scope, key, version, payload, hashlib.sha256(payload.encode()).hexdigest(), lvl, actor.name))
        c.execute("INSERT INTO heads VALUES(?,?,?) ON CONFLICT(scope,key) DO UPDATE SET version=excluded.version",
                  (actor.scope, key, version))
        affected = self._invalidate_dependents(c, actor.scope, "fact", key)
        self._record(c, "fact.updated", scope=actor.scope, key=key, version=version, affected=affected)
        return version

    def put_fact(self, actor: Principal, key: str, value: Any,
                 label: str = "internal") -> int:
        if label not in LEVELS:
            raise ValueError("unknown classification")
        lvl = LEVELS[label]
        self._role(actor, "writer", actor.scope, lvl)
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            version = self._put_fact_tx(c, actor, key, compact(value), lvl)
            c.execute("COMMIT")
            return version

    @staticmethod
    def _authority(level: int, author: str) -> str:
        return digest({"level":level,"author":author})

    def _source_matches(self, c, scope: str, dependency, memo: dict[str,bool] | None = None) -> bool:
        """Authorization/lineage and value must *both* match recorded witnesses."""
        if not dependency["expected_authority"]:
            return False # pre-migration witnesses are not authority-certified
        if dependency["kind"] == "fact":
            ref = c.execute("SELECT f.* FROM facts f JOIN heads h ON "
                            "f.scope=h.scope AND f.key=h.key AND f.version=h.version "
                            "WHERE f.scope=? AND f.key=?", (scope,dependency["source"])).fetchone()
            if ref is None or self._authority(ref["level"],ref["author"]) != dependency["expected_authority"]:
                return False
            if hashlib.sha256(ref["payload"].encode()).hexdigest()!=ref["hash"]:
                raise IntegrityError("fact dependency hash mismatch")
            try:
                return digest(projection(json.loads(ref["payload"]),dependency["pointer"]))==dependency["expected_hash"]
            except (KeyError,ValueError,IndexError,TypeError):
                return False
        if dependency["kind"] == "artifact":
            ref=self._head_artifact(c,scope,dependency["source"])
            if ref is None or self._authority(ref["level"],ref["author"]) != dependency["expected_authority"]:
                return False
            if ref["hash"]!=dependency["expected_hash"] or ref["status"]=="STALE":
                return False
            if hashlib.sha256(ref["payload"].encode()).hexdigest()!=ref["hash"]:
                raise IntegrityError("artifact dependency hash mismatch")
            return True
        return False

    def _invalidate_dependents(self, c, scope: str, kind: str, source: str) -> list[str]:
        """Eager conservative invalidation; one pass per distinct affected node."""
        queue = deque([(kind,source)])
        traversed=set()
        affected=[]
        while queue:
            node=queue.popleft()
            if node in traversed:
                continue
            traversed.add(node)
            rows=c.execute("SELECT d.* FROM deps d JOIN artifact_heads h "
                           "ON h.scope=d.scope AND h.id=d.child_id AND h.version=d.child_version "
                           "WHERE d.scope=? AND d.kind=? AND d.source=?",(scope,*node)).fetchall()
            for dep in rows:
                child=dep["child_id"]
                current=c.execute("SELECT status FROM artifacts WHERE scope=? AND id=? AND version=?",
                                  (scope,child,dep["child_version"])).fetchone()
                if current is None:
                    continue
                # A STALE ancestor makes the descendant stale, even when its
                # stored output hash is coincidentally equal to an earlier value.
                if current["status"] != "STALE" and self._source_matches(c,scope,dep):
                    continue
                if current["status"] != "STALE":
                    c.execute("UPDATE artifacts SET status='STALE' WHERE scope=? AND id=? AND version=?",
                              (scope,child,dep["child_version"]))
                    affected.append(child)
                queue.append(("artifact",child))
        return affected

    def register_source_tree(self, actor: Principal, source_id: str,
                             hashes: dict[str, str]) -> bool:
        """Trusted coordinator records workspace HEAD; no update for unchanged bytes.

        The tree is a single versioned fact; agents witness individual path
        projections (or the full tree for listings/negative reads). The runtime
        must additionally verify the underlying workspace bytes at publication.
        Returns True if the registered source tree changed.
        """
        if not source_id.startswith("repo:") or len(source_id)>180:
            raise ValueError("source id must be a bounded repo: namespace")
        if len(hashes)>100 or any(not isinstance(n,str) or not isinstance(h,str)
                                    or len(h)!=64 for n,h in hashes.items()):
            raise ValueError("invalid file hash manifest")
        self._role(actor,"writer",actor.scope,LEVELS["internal"])
        tree={"hashes":hashes,"names":sorted(hashes)}
        payload=compact(tree)
        # Compare and publish in a *single* write transaction. Two concurrent
        # coordinators cannot both observe stale heads and then overwrite each
        # other's no-op registration through a separate put_fact call.
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT h.version,f.level,f.payload FROM facts f JOIN heads h ON "
                          "f.scope=h.scope AND f.key=h.key AND f.version=h.version "
                          "WHERE f.scope=? AND f.key=?",(actor.scope,source_id)).fetchone()
            if row is not None and row["payload"]==payload:
                c.execute("COMMIT")
                return False
            self._put_fact_tx(c,actor,source_id,payload,LEVELS["internal"],row)
            c.execute("COMMIT")
            return True

    def observe(self, actor: Principal) -> "Observation":
        self._role(actor, "reader", actor.scope)
        return Observation(self, actor)

    def _read_fact(self, c, actor: Principal, key: str) -> tuple[Any,int,int]:
        row = c.execute("SELECT f.* FROM facts f JOIN heads h ON "
                        "f.scope=h.scope AND f.key=h.key AND f.version=h.version "
                        "WHERE f.scope=? AND f.key=?", (actor.scope, key)).fetchone()
        if row is None:
            raise KeyError(key)
        self._role(actor, "reader", actor.scope, row["level"])
        if hashlib.sha256(row["payload"].encode()).hexdigest() != row["hash"]:
            raise IntegrityError("fact hash mismatch")
        return json.loads(row["payload"]),row["version"],row["level"],row["author"]

    def _head_artifact(self, c, scope: str, id: str):
        return c.execute("SELECT a.* FROM artifacts a JOIN artifact_heads h ON "
                         "a.scope=h.scope AND a.id=h.id AND a.version=h.version "
                         "WHERE a.scope=? AND a.id=?", (scope,id)).fetchone()

    def _verify_workspace_payload(self, payload:dict) -> None:
        """Bounded file integrity check for accepted workspace artifacts."""
        if not payload.get("independent_acceptance"):
            return
        hashes=payload.get("file_hashes")
        if not isinstance(hashes,dict) or len(hashes)>100:
            raise IntegrityError("published file manifest invalid")
        try:
            location=Path(payload["snapshot"]).resolve(strict=True)
        except (KeyError,OSError) as e:
            raise IntegrityError("published snapshot missing") from e
        if (location.parent.name!=".fluxos-published" or
            not location.is_relative_to(self.home.parent.resolve()) or
            not location.is_dir()):
            raise IntegrityError("published snapshot path outside trusted release store")
        found={}
        total=0
        for entry in location.rglob("*"):
            if entry.is_symlink():
                raise IntegrityError("symlink in published workspace")
            if entry.is_file():
                total+=entry.stat().st_size
                if total>20_000_000 or len(found)>=100:
                    raise IntegrityError("published workspace exceeds verification budget")
                name=entry.relative_to(location).as_posix()
                found[name]=hashlib.sha256(entry.read_bytes()).hexdigest()
        if found!=hashes:
            raise IntegrityError("published workspace content hash mismatch")

    def _validate(self, c, scope: str, id: str, memo: dict[str,bool] | None = None) -> bool:
        """Iterative, memoized, cycle-safe DAG validation; no recursive explosion."""
        memo={} if memo is None else memo
        visiting=set()
        stack=[(id,False)]
        checks=0
        while stack:
            node,finish=stack.pop()
            if node in memo:
                continue
            if finish:
                visiting.discard(node)
                ref=self._head_artifact(c,scope,node)
                if ref is None or ref["status"]=="STALE":
                    memo[node]=False
                    continue
                ok=True
                for dep in c.execute("SELECT * FROM deps WHERE scope=? AND child_id=? AND child_version=?",
                                     (scope,node,ref["version"])).fetchall():
                    if dep["kind"]=="artifact" and not memo.get(dep["source"],False):
                        ok=False; break
                    if not self._source_matches(c,scope,dep,memo):
                        ok=False; break
                memo[node]=ok
                continue
            if node in visiting:
                raise Stale("cyclic artifact dependency")
            ref=self._head_artifact(c,scope,node)
            if ref is None or ref["status"]=="STALE":
                memo[node]=False
                continue
            if hashlib.sha256(ref["payload"].encode()).hexdigest()!=ref["hash"]:
                raise IntegrityError(f"artifact {node} failed content hash")
            if node.startswith("result:"):
                payload=json.loads(ref["payload"])
                if isinstance(payload,dict):
                    self._verify_workspace_payload(payload)
            visiting.add(node)
            stack.append((node,True))
            for dep in c.execute("SELECT * FROM deps WHERE scope=? AND child_id=? AND child_version=?",
                                 (scope,node,ref["version"])).fetchall():
                if dep["kind"]=="artifact" and dep["source"] not in memo:
                    if dep["source"] in visiting:
                        raise Stale("cyclic artifact dependency")
                    stack.append((dep["source"],False))
            checks+=1
            if checks>20000:
                raise Stale("dependency validation graph budget exceeded")
        return memo.get(id,False)

    def artifact(self, actor: Principal, id: str) -> dict:
        with self._conn() as c:
            c.execute("BEGIN")
            row = self._head_artifact(c, actor.scope,id)
            if row is None:
                raise KeyError(id)
            self._role(actor,"reader",actor.scope,row["level"])
            ok = self._validate(c,actor.scope,id)
            if not ok:
                raise Stale(id)
            payload = json.loads(row["payload"])
            c.execute("COMMIT")
            return payload

    def verify_published_snapshot(self, actor:Principal, id:str) -> dict:
        """Recheck published files against their committed content hash manifest."""
        record=self.artifact(actor,id)  # includes currentness + snapshot integrity
        if not record.get("independent_acceptance"):
            raise Denied("not an independently accepted snapshot")
        self._verify_workspace_payload(record)
        return {"artifact":id,"files":sorted(record["file_hashes"]),"verified":True}

    def status(self, actor: Principal, id: str) -> str:
        with self._conn() as c:
            row = self._head_artifact(c,actor.scope,id)
            if row is None:
                raise KeyError(id)
            self._role(actor,"reader",actor.scope,row["level"])
            try:
                return "DECLARED_CURRENT" if self._validate(c,actor.scope,id) else "STALE"
            except IntegrityError:
                return "INTEGRITY_FAILED"

    def _would_cycle(self, c, scope: str, target: str, source: str) -> bool:
        """Check committed dependency ancestry before replacing target."""
        queue=[source]
        seen=set()
        while queue:
            cur=queue.pop()
            if cur==target:return True
            if cur in seen:continue
            seen.add(cur)
            row=self._head_artifact(c,scope,cur)
            if not row:continue
            for d in c.execute("SELECT source FROM deps WHERE scope=? AND child_id=? AND child_version=? AND kind='artifact'",
                               (scope,cur,row["version"])):
                queue.append(d["source"])
        return False

    def _check_manifest(self,c,actor:Principal,id:str,manifest:list[dict],level:int):
        # Recheck witnesses in the *same* transaction as publication.
        for d in manifest:
            kind,src = d["kind"],d["source"]
            if kind == "fact":
                obj,ver,dep_level,dep_author = self._read_fact(c,actor,src)
                if digest(projection(obj,d["pointer"])) != d["expected_hash"]:
                    raise Stale(f"fact {src} changed")
                authority=self._authority(dep_level,dep_author)
            elif kind == "artifact":
                if self._would_cycle(c,actor.scope,id,src):
                    raise Stale("dependency cycle would be introduced")
                ref = self._head_artifact(c,actor.scope,src)
                if ref is None or not self._validate(c,actor.scope,src):
                    raise Stale(f"artifact {src} changed")
                self._role(actor,"reader",actor.scope,ref["level"])
                if ref["hash"] != d["expected_hash"]:
                    raise Stale(f"artifact {src} changed")
                dep_level = ref["level"]
                authority=self._authority(ref["level"],ref["author"])
            else:
                raise ValueError("invalid dependency kind")
            if d.get("expected_authority") != authority:
                raise Stale(f"authority/lineage of {src} changed or witness missing")
            if dep_level > level and "declassifier" not in actor.roles:
                raise Denied("output would downgrade classification of dependency")

    def validate_manifest(self, actor:Principal, manifest:list[dict],label:str="internal") -> bool:
        """Read-only currentness check for drafts; not a commit certificate."""
        if label not in LEVELS:raise ValueError("invalid label")
        self._role(actor,"writer",actor.scope,LEVELS[label])
        if len(manifest)>256:raise Denied("manifest too large")
        with self._conn() as c:
            c.execute("BEGIN")
            self._check_manifest(c,actor,"",manifest,LEVELS[label])
            c.execute("COMMIT")
        return True

    def put_artifact(self, actor: Principal, id: str, value: Any,
                     manifest: list[dict], label: str = "internal",
                     job_id: str | None = None, job_generation: int | None = None,
                     project_id: str | None = None,
                     expected_project_revision: int | None = None) -> int:
        if label not in LEVELS:
            raise ValueError("unknown classification")
        level = LEVELS[label]
        self._role(actor,"writer",actor.scope,level)
        if len(manifest)>256:
            raise Denied("manifest too large")
        payload = compact(value)
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            if job_id is not None:
                job=c.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
                if (job is None or job["state"]!="RUNNING" or
                    job["scope"]!=actor.scope or job["owner"]!=actor.name or
                    job_generation is None or job["generation"]!=job_generation):
                    raise Stale("job ownership/generation fence no longer current")
            old = self._head_artifact(c,actor.scope,id)
            if old:
                self._role(actor,"writer",actor.scope,old["level"])
                if old["author"] != actor.name and "publisher" not in actor.roles:
                    raise Denied("replacing another agent's artifact requires publisher role")
                if level < old["level"] and "declassifier" not in actor.roles:
                    raise Denied("artifact downgrade forbidden")
            if id.startswith("result:") and (job_id is None or job_generation is None):
                # Agent outputs cannot escape generation fencing, even via SDK.
                # Legacy generic artifacts remain available to trusted internal code.
                raise Denied("result publication requires a live owned job and generation")
            project_revision = None
            if project_id is not None:
                if not isinstance(project_id,str) or not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}",project_id):
                    raise ValueError("invalid project ID")
                if not id.startswith("result:") or job_id is None:
                    raise Denied("a project revision requires a fenced agent result")
                head=c.execute("SELECT revision FROM project_heads WHERE scope=? AND project_id=?",
                               (actor.scope,project_id)).fetchone()
                current=head["revision"] if head else 0
                if expected_project_revision is None or expected_project_revision!=current:
                    raise Stale(f"project head moved: expected {expected_project_revision}, current {current}")
                if not isinstance(value,dict) or not value.get("independent_acceptance") or not value.get("file_hashes"):
                    raise Denied("project revision needs an independently accepted file snapshot")
                self._verify_workspace_payload(value)
                project_revision=current+1
            self._check_manifest(c,actor,id,manifest,level)
            version = (old["version"] if old else 0) + 1
            c.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?)",
                      (actor.scope,id,version,payload,hashlib.sha256(payload.encode()).hexdigest(),
                       level,actor.name,compact(manifest),"DECLARED_CURRENT"))
            for d in manifest:
                c.execute("INSERT INTO deps(scope,child_id,child_version,kind,source,pointer,expected_hash,expected_version,expected_authority) VALUES(?,?,?,?,?,?,?,?,?)",
                          (actor.scope,id,version,d["kind"],d["source"],d["pointer"],
                           d["expected_hash"],d["expected_version"],d["expected_authority"]))
            c.execute("INSERT INTO artifact_heads VALUES(?,?,?) ON CONFLICT(scope,id) DO UPDATE SET version=excluded.version",
                      (actor.scope,id,version))
            if project_revision is not None:
                c.execute("INSERT INTO project_revisions VALUES(?,?,?,?,?,?,?,?,?)",
                          (actor.scope,project_id,project_revision,id,version,
                           value["snapshot"],compact(value["file_hashes"]),actor.name,time.time()))
                c.execute("INSERT INTO project_heads VALUES(?,?,?) ON CONFLICT(scope,project_id) DO UPDATE SET revision=excluded.revision",
                          (actor.scope,project_id,project_revision))
                self._record(c,"project.revision",scope=actor.scope,project_id=project_id,
                             revision=project_revision,output_id=id)
            affected=self._invalidate_dependents(c,actor.scope,"artifact",id)
            self._record(c,"artifact.committed",scope=actor.scope,id=id,version=version,
                         dependencies=len(manifest),affected=affected)
            c.execute("COMMIT")
            return version

    def project_head(self, actor: Principal, project_id: str) -> dict | None:
        """Current accepted files, verified against their immutable snapshot."""
        self._role(actor,"reader",actor.scope)
        if not isinstance(project_id,str) or not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}",project_id):
            raise ValueError("invalid project ID")
        with self._conn() as c:
            c.execute("BEGIN")
            row=c.execute("SELECT r.* FROM project_revisions r JOIN project_heads h ON "
                          "r.scope=h.scope AND r.project_id=h.project_id AND r.revision=h.revision "
                          "WHERE r.scope=? AND r.project_id=?",(actor.scope,project_id)).fetchone()
            if row is None:
                return None
            rec=dict(row)
            source=self._head_artifact(c,actor.scope,rec["output_id"])
            if source is None or source["version"]!=rec["artifact_version"] or not self._validate(c,actor.scope,rec["output_id"]):
                raise Stale("published project head is invalid")
            self._role(actor,"reader",actor.scope,source["level"])
            self._verify_workspace_payload(json.loads(source["payload"]))
            rec["files"]=json.loads(rec.pop("manifest"))
            return rec

    def project_history(self, actor: Principal, project_id: str) -> list[dict]:
        self._role(actor,"reader",actor.scope)
        if not isinstance(project_id,str) or not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}",project_id):
            raise ValueError("invalid project ID")
        with self._conn() as c:
            return [{"revision":r["revision"],"output_id":r["output_id"],"created":r["created"]}
                    for r in c.execute("SELECT * FROM project_revisions WHERE scope=? AND project_id=? ORDER BY revision",
                                       (actor.scope,project_id))]

    def record_execution(self,job_id:str,step:int,kind:str,details:dict) -> None:
        """Durable diagnostics, not replay-safe tool execution or conversation resume."""
        if type(step) is not int or step<0 or not kind or len(kind)>50:
            raise ValueError('invalid execution event')
        encoded=compact(details)
        if len(encoded)>16000:raise ValueError('execution event too large')
        with self._conn() as c:
            if c.execute('SELECT 1 FROM jobs WHERE id=?',(job_id,)).fetchone() is None:
                raise KeyError(job_id)
            c.execute('INSERT INTO execution_events(job_id,step,kind,details,created) VALUES(?,?,?,?,?)',
                      (job_id,step,kind,encoded,time.time()))

    def execution_history(self,job_id:str,limit:int=100) -> list[dict]:
        with self._conn() as c:
            return [dict(seq=r['seq'],step=r['step'],kind=r['kind'],
                         details=json.loads(r['details']),created=r['created'])
                    for r in c.execute('SELECT * FROM execution_events WHERE job_id=? ORDER BY seq LIMIT ?',
                                       (job_id,min(max(1,limit),500)))]

    def timeline(self, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            return [dict(seq=r["seq"],time=r["ts"],kind=r["kind"],**json.loads(r["details"]))
                    for r in c.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?",(min(limit,500),))]

    def graph(self, scope: str = "demo") -> dict:
        with self._conn() as c:
            nodes=[];edges=[];memo={}
            for row in c.execute("SELECT a.id,a.version,a.status,a.hash FROM artifacts a JOIN artifact_heads h "
                                 "ON a.scope=h.scope AND a.id=h.id AND a.version=h.version WHERE a.scope=?",(scope,)):
                try:
                    effective = "DECLARED_CURRENT" if self._validate(c,scope,row["id"],memo=memo) else "STALE"
                except IntegrityError:
                    effective = "INTEGRITY_FAILED"
                except Stale:
                    effective = "STALE"
                nodes.append(dict(id=row["id"],version=row["version"],
                                  status=effective,hash=row["hash"][:12]))
            for row in c.execute("SELECT d.* FROM deps d JOIN artifact_heads h ON d.scope=h.scope AND d.child_id=h.id AND d.child_version=h.version WHERE d.scope=?",(scope,)):
                edges.append(dict(source=row["source"],target=row["child_id"],kind=row["kind"],pointer=row["pointer"]))
            return {"nodes":nodes,"edges":edges}

    def create_job(self, scope: str, owner: str, task: str,
                   parent_id: str | None = None, actor:Principal | None = None) -> str:
        # The actor-less path is for the trusted in-process coordinator only.
        if actor is not None:
            self._role(actor,"writer",scope)
            if actor.name!=owner:
                raise Denied("job owner mismatch")
        id=uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute("INSERT INTO jobs(id,scope,task,state,parent_id,owner,created,generation) "
                      "VALUES(?,?,?,?,?,?,?,0)",(id,scope,task,"PENDING",parent_id,owner,time.time()))
            self._record(c,"job.spawned",id=id,scope=scope,task=task,parent=parent_id)
        return id

    def get_job(self, id:str) -> dict:
        with self._conn() as c:
            row=c.execute("SELECT * FROM jobs WHERE id=?",(id,)).fetchone()
            if row is None:raise KeyError(id)
            return dict(row)

    def set_job(self,id: str,state: str, actor:Principal|None=None,
                expected_state:str|None=None, expected_generation:int|None=None) -> int:
        allowed={"PENDING":{"RUNNING","FAILED","CANCELLED","COMPLETED","DRAFT"},
                 "RUNNING":{"COMPLETED","DRAFT","FAILED","CANCELLED"},
                 "COMPLETED":set(),"DRAFT":set(),"FAILED":set(),"CANCELLED":set()}
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM jobs WHERE id=?",(id,)).fetchone()
            if row is None:raise KeyError(id)
            if actor is not None:
                self._role(actor,"writer",row["scope"])
                if actor.name!=row["owner"]:
                    raise Denied("only job owner can advance job")
            if (expected_state is not None and row["state"]!=expected_state or
                expected_generation is not None and row["generation"]!=expected_generation):
                raise Stale("job state/lease changed")
            if state not in allowed.get(row["state"],set()):
                raise Stale(f"illegal job transition {row['state']} -> {state}")
            epoch=row["generation"]+1 if state=="RUNNING" else row["generation"]
            c.execute("UPDATE jobs SET state=?,generation=? WHERE id=? AND state=? AND generation=?",
                      (state,epoch,id,row["state"],row["generation"]))
            if c.total_changes==0:
                raise Stale("job CAS lost")
            self._record(c,"job."+state.lower(),id=id,scope=row["scope"],generation=epoch)
            c.execute("COMMIT")
            return epoch

    def jobs(self,scope: str = "demo") -> list[dict]:
        with self._conn() as c:
            return [dict(x) for x in c.execute("SELECT * FROM jobs WHERE scope=? ORDER BY created",(scope,))]


class Observation:
    """Read set records fine-grained JSON pointers; no claim of capturing hidden I/O."""
    def __init__(self, memory: Memory, actor: Principal):
        self.memory=memory
        self.actor=actor
        self._witnesses: dict[tuple[str,str,str],dict] = {}

    def fact(self,key: str,pointer: str = "") -> Any:
        with self.memory._conn() as c:
            c.execute("BEGIN")
            obj,ver,lvl,author = self.memory._read_fact(c,self.actor,key)
            val=projection(obj,pointer)
            witness={"kind":"fact","source":key,"pointer":pointer,
                     "expected_hash":digest(val),"expected_version":ver,
                     "expected_authority":self.memory._authority(lvl,author)}
            slot=("fact",key,pointer)
            previous=self._witnesses.get(slot)
            if previous and (previous["expected_hash"]!=witness["expected_hash"] or
                             previous["expected_authority"]!=witness["expected_authority"]):
                raise Stale("source changed during a single observation; restart generation")
            self._witnesses[slot]=witness
            c.execute("COMMIT")
            return val

    def artifact(self,id: str) -> Any:
        with self.memory._conn() as c:
            c.execute("BEGIN")
            row=self.memory._head_artifact(c,self.actor.scope,id)
            if row is None:
                raise KeyError(id)
            self.memory._role(self.actor,"reader",self.actor.scope,row["level"])
            if not self.memory._validate(c,self.actor.scope,id):
                raise Stale(id)
            val=json.loads(row["payload"])
            witness={"kind":"artifact","source":id,"pointer":"",
                     "expected_hash":row["hash"],"expected_version":row["version"],
                     "expected_authority":self.memory._authority(row["level"],row["author"])}
            slot=("artifact",id,"")
            previous=self._witnesses.get(slot)
            if previous and (previous["expected_hash"]!=witness["expected_hash"] or
                             previous["expected_authority"]!=witness["expected_authority"]):
                raise Stale("source artifact changed during a single observation")
            self._witnesses[slot]=witness
            c.execute("COMMIT")
            return val

    def manifest(self) -> list[dict]:
        return list(self._witnesses.values())
