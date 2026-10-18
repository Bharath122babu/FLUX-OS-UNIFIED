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
ABSENT_WITNESS_HASH = hashlib.sha256(b"fluxos:absent-json-field:v1").hexdigest()


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


def witness_hash(obj: Any, pointer: str) -> str:
    """Hash an observed JSON leaf; only an absent FINAL object key is negative."""
    if pointer == "":
        return digest(obj)
    if not pointer.startswith("/"):
        raise ValueError("invalid JSON pointer")
    parts=[v.replace("~1","/").replace("~0","~") for v in pointer[1:].split("/")]
    parent=obj
    for part in parts[:-1]:
        parent=parent[int(part)] if isinstance(parent,list) else parent[part]
    if isinstance(parent,dict) and parts[-1] not in parent:
        return ABSENT_WITNESS_HASH
    leaf=parent[int(parts[-1])] if isinstance(parent,list) else parent[parts[-1]]
    return digest(leaf)


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
            CREATE TABLE IF NOT EXISTS claims(
              scope TEXT NOT NULL, id TEXT NOT NULL, subject TEXT NOT NULL,
              predicate TEXT NOT NULL, value TEXT NOT NULL, value_hash TEXT NOT NULL,
              source TEXT NOT NULL, author TEXT NOT NULL, level INTEGER NOT NULL,
              created REAL NOT NULL, PRIMARY KEY(scope,id));
            CREATE INDEX IF NOT EXISTS claims_by_slot ON claims(scope,subject,predicate);
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

    @staticmethod
    def _check_job_fences(c,actor:Principal,fences):
        if len(fences)>2:
            raise ValueError('at most a worker and parent job fence are supported')
        for job_id,generation in fences:
            job=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if (job is None or job['state']!='RUNNING' or job['scope']!=actor.scope or
                job['owner']!=actor.name or type(generation) is not int or job['generation']!=generation):
                raise Stale('shared-memory job ownership/generation fence no longer current')

    def _put_fact_tx(self, c, actor: Principal, key: str, payload: str,
                     lvl: int, old=None, origin_author: str | None = None) -> int:
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
                  (actor.scope, key, version, payload, hashlib.sha256(payload.encode()).hexdigest(), lvl,
                   # For field-merged revisions the original authority is retained;
                   # the actual editor is preserved separately in the event journal.
                   origin_author or actor.name))
        c.execute("INSERT INTO heads VALUES(?,?,?) ON CONFLICT(scope,key) DO UPDATE SET version=excluded.version",
                  (actor.scope, key, version))
        affected = self._invalidate_dependents(c, actor.scope, "fact", key)
        self._record(c, "fact.updated", scope=actor.scope, key=key, version=version, affected=affected)
        return version

    def put_fact(self, actor: Principal, key: str, value: Any,
                 label: str = "internal", *, expected_version: int | None = None,
                 job_fences=()) -> int:
        if expected_version is not None and (type(expected_version) is not int or expected_version<0):
            raise ValueError("expected_version must be a nonnegative integer")
        if label not in LEVELS:
            raise ValueError("unknown classification")
        lvl = LEVELS[label]
        self._role(actor, "writer", actor.scope, lvl)
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            self._check_job_fences(c,actor,job_fences)
            old = c.execute("SELECT h.version,f.level FROM heads h JOIN facts f ON "
                            "(h.scope=f.scope AND h.key=f.key AND h.version=f.version) "
                            "WHERE h.scope=? AND h.key=?",(actor.scope,key)).fetchone()
            current = old["version"] if old else 0
            if old is not None:
                # Check access before reporting any secret head/version detail.
                self._role(actor,"writer",actor.scope,old["level"])
            # No blind writes by ordinary workers. An explicitly privileged
            # in-process coordinator may publish authoritative changes without a
            # preimage (e.g. incoming user requirements). Caller-created roles are
            # NOT authentication; never expose Principal construction to models.
            if expected_version is None and "coordinator" not in actor.roles:
                raise Stale("fact update requires an expected_version")
            if expected_version is not None and expected_version != current:
                raise Stale(f"fact changed: expected {expected_version}, current {current}")
            version = self._put_fact_tx(c, actor, key, compact(value), lvl, old)
            c.execute("COMMIT")
            return version

    def fact_head(self, actor: Principal, key: str) -> dict:
        """Return a witnessed snapshot for an optimistic edit, not a mutable reference."""
        with self._conn() as c:
            row = c.execute("SELECT f.* FROM facts f JOIN heads h ON "
                            "f.scope=h.scope AND f.key=h.key AND f.version=h.version "
                            "WHERE f.scope=? AND f.key=?",(actor.scope,key)).fetchone()
            if row is None:
                raise KeyError(key)
            self._role(actor,"reader",actor.scope,row["level"])
            if hashlib.sha256(row["payload"].encode()).hexdigest()!=row["hash"]:
                raise IntegrityError("fact head payload damaged")
            return {"key":key,"version":row["version"],"value":json.loads(row["payload"]),
                    "label":next(k for k,v in LEVELS.items() if v==row["level"]),
                    "authority":self._authority(row["level"],row["author"])}

    @staticmethod
    def _pointer_parts(pointer: str) -> list[str]:
        """Strict JSON-object pointers. Arrays are intentionally not patched."""
        if not isinstance(pointer,str) or not pointer.startswith("/") or len(pointer)>512:
            raise ValueError("patch path must be a bounded JSON pointer")
        raw=pointer[1:].split("/")
        if len(raw)>16 or any(not part for part in raw):
            raise ValueError("patch path depth/empty component forbidden")
        for part in raw:
            if "~" in part.replace("~0","").replace("~1",""):
                raise ValueError("invalid JSON pointer escape")
        return [part.replace("~1","/").replace("~0","~") for part in raw]

    def patch_fact(self, actor: Principal, key: str, changes: list[dict],
                   *, read_manifest: list[dict] | None = None,
                   return_snapshot: bool = False,job_fences=()) -> int | dict:
        """Single atomic conditional patch: disjoint edits commute without lost updates.

        Each operation carries `path`, `expected_hash` (digest of previously
        witnessed value, or None for absence), and `value`.  The caller MUST
        observe the exact field; guessing a hash is not a semantic read proof.
        Whole-record dependent reasoning belongs in read_manifest and is rejected
        if any of those inputs changed.  Conflicting same-field edits fail closed.
        """
        if not isinstance(changes,list) or not 1 <= len(changes) <= 64:
            raise ValueError("patch requires 1..64 operations")
        if read_manifest is not None and (not isinstance(read_manifest,list) or len(read_manifest)>256):
            raise ValueError("read_manifest must be a list of at most 256 witnesses")
        parsed=[]
        for operation in changes:
            if not isinstance(operation,dict) or set(operation)!={"path","expected_hash","value"}:
                raise ValueError("patch operation requires exactly path, expected_hash, value")
            parts=self._pointer_parts(operation["path"])
            witness=operation["expected_hash"]
            if witness is not None and (not isinstance(witness,str) or len(witness)!=64 or
                                        any(ch not in "0123456789abcdef" for ch in witness)):
                raise ValueError("expected_hash must be SHA-256 or None for absent field")
            parsed.append((parts,witness,operation["value"]))
        for i,(a,*_) in enumerate(parsed):
            for b,*_ in parsed[:i]:
                if a[:len(b)]==b or b[:len(a)]==a:
                    raise ValueError("overlapping patch paths")
        self._role(actor,"writer",actor.scope)
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            self._check_job_fences(c,actor,job_fences)
            row=c.execute("SELECT f.* FROM facts f JOIN heads h ON "
                          "f.scope=h.scope AND f.key=h.key AND f.version=h.version "
                          "WHERE f.scope=? AND f.key=?",(actor.scope,key)).fetchone()
            if row is None:
                raise KeyError(key)
            self._role(actor,"reader",actor.scope,row["level"])
            self._role(actor,"writer",actor.scope,row["level"])
            if hashlib.sha256(row["payload"].encode()).hexdigest()!=row["hash"]:
                raise IntegrityError("fact payload damaged")
            # Validate causal reads under exactly the same writer lock as patch.
            if read_manifest:
                self._check_manifest(c,actor,"__patch__",read_manifest,row["level"])
            value=json.loads(row["payload"])
            if not isinstance(value,dict):
                raise ValueError("field patches require a JSON object")
            # Validate all preimages BEFORE changing anything.
            for parts,expected,new_value in parsed:
                obj=value
                for field in parts[:-1]:
                    if not isinstance(obj,dict) or field not in obj:
                        raise Stale("patch parent path missing")
                    obj=obj[field]
                if not isinstance(obj,dict):
                    raise ValueError("patch target parent must be an object")
                present=parts[-1] in obj
                actual=digest(obj[parts[-1]]) if present else None
                if actual!=expected:
                    raise Stale("field changed since it was observed")
            for parts,expected,new_value in parsed:
                obj=value
                for field in parts[:-1]:obj=obj[field]
                obj[parts[-1]]=new_value
            payload=compact(value)
            if len(payload)>1_000_000:
                raise ValueError("patched fact too large")
            # Origin authority continuity is maintained for same-scope editors;
            # editor identity, paths, and revision are preserved in audit events.
            version=self._put_fact_tx(c,actor,key,payload,row["level"],row,
                                      origin_author=row["author"])
            self._record(c,"fact.patched",scope=actor.scope,key=key,version=version,
                         editor=actor.name,paths=[op[0] for op in parsed])
            snapshot={"key":key,"version":version,"value":value,
                      "authority":self._authority(row["level"],row["author"])}
            c.execute("COMMIT")
            # Return the exact committed state, never a second raced head read.
            return snapshot if return_snapshot else version

    def record_claim(self, actor: Principal, subject: str, predicate: str, value: Any,
                     source: str, *, label: str = "internal",job_fences=()) -> dict:
        """An evidence-labelled assertion; conflicts are surfaced, never 'solved' by recency.

        This is intentionally not a truth oracle. A claim has an immutable ID;
        mutually different values in the same subject/predicate slot are DISPUTED.
        """
        if label not in LEVELS: raise ValueError("unknown classification")
        level=LEVELS[label]
        self._role(actor,"writer",actor.scope,level)
        if any(not isinstance(x,str) or not x.strip() or len(x)>200
               for x in (subject,predicate,source)):
            raise ValueError("subject, predicate and evidence source are required")
        payload=compact(value)
        if len(payload)>32_000: raise ValueError("claim value too large")
        claim_id=uuid.uuid4().hex
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            self._check_job_fences(c,actor,job_fences)
            c.execute("INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (actor.scope,claim_id,subject,predicate,payload,digest(value),
                       source,actor.name,level,time.time()))
            # Never leak the existence of a higher-clearance assertion through
            # the conflict status returned to this editor.
            visible=c.execute(
                "SELECT value,value_hash FROM claims WHERE scope=? AND subject=? AND predicate=? AND level<=?",
                (actor.scope,subject,predicate,actor.clearance)).fetchall()
            hashes=self._claim_hashes(visible)
            status="DISPUTED" if len(hashes)>1 else "UNCONTESTED"
            self._record(c,"claim.added",scope=actor.scope,id=claim_id,
                         subject=subject,predicate=predicate,status=status)
            c.execute("COMMIT")
        return {"id":claim_id,"status":status}

    def claims(self, actor: Principal, subject: str, predicate: str) -> dict:
        """Permission-filtered claims. Hidden claims are not exposed through status."""
        self._role(actor,"reader",actor.scope)
        with self._conn() as c:
            available=c.execute("SELECT id,value,value_hash,source,author,level,created FROM claims "
                           "WHERE scope=? AND subject=? AND predicate=? AND level<=? ORDER BY created,id",
                           (actor.scope,subject,predicate,actor.clearance)).fetchall()
            variants=self._claim_hashes(available)
            return {"status":("UNAVAILABLE" if not available else
                              "DISPUTED" if len(variants)>1 else "UNCONTESTED"),
                    "claims":[{"id":r["id"],"value":json.loads(r["value"]),
                               "source":r["source"],"author":r["author"],"created":r["created"]}
                              for r in available]}

    @staticmethod
    def _claim_hashes(rows) -> set[str]:
        hashes=set()
        for row in rows:
            actual=hashlib.sha256(row["value"].encode()).hexdigest()
            if actual!=row["value_hash"]:
                raise IntegrityError("claim payload damaged")
            hashes.add(actual)
        return hashes

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
                return witness_hash(json.loads(ref["payload"]),dependency["pointer"])==dependency["expected_hash"]
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
                try:
                    actual=witness_hash(obj,d["pointer"])
                except (KeyError,IndexError,ValueError,TypeError) as exc:
                    raise Stale(f"fact {src} path changed") from exc
                if actual != d["expected_hash"]:
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
            rows=c.execute("SELECT r.revision,r.output_id,r.created,a.level "
                           "FROM project_revisions r JOIN artifacts a "
                           "ON a.scope=r.scope AND a.id=r.output_id AND a.version=r.artifact_version "
                           "WHERE r.scope=? AND r.project_id=? ORDER BY r.revision",
                           (actor.scope,project_id)).fetchall()
            return [{"revision":r["revision"],"output_id":r["output_id"],"created":r["created"]}
                    for r in rows if r["level"] <= actor.clearance]

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

    def reconcile_interrupted_jobs(self, scope: str, *, owner: str | None = None) -> list[str]:
        """Quarantine orphaned work after restart; NEVER replay opaque tool effects.

        Invoke from a sole trusted coordinator only, after previous workers have
        been stopped. Generation increments fence off any delayed publications.
        Callers may create a NEW job based on an inspected checkpoint; this
        method never guesses whether an external effect happened.
        """
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            where="scope=? AND state='RUNNING'"
            params=[scope]
            if owner is not None:
                where+=" AND owner=?"
                params.append(owner)
            rows=c.execute(f"SELECT id,generation FROM jobs WHERE {where}",params).fetchall()
            ids=[]
            for row in rows:
                c.execute("UPDATE jobs SET state='INTERRUPTED',generation=generation+1 WHERE id=?",
                          (row["id"],))
                ids.append(row["id"])
                self._record(c,"job.interrupted",scope=scope,id=row["id"],
                             generation=row["generation"]+1)
            c.execute("COMMIT")
            return ids

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

    def absent_fact(self, key: str, pointer: str) -> bool:
        """Witness the absence of a JSON object field, not an arbitrary failed read."""
        parts=Memory._pointer_parts(pointer)
        with self.memory._conn() as c:
            c.execute("BEGIN")
            obj,ver,lvl,author=self.memory._read_fact(c,self.actor,key)
            node=obj
            for part in parts[:-1]:
                if not isinstance(node,dict) or part not in node:
                    raise KeyError("parent for negative witness missing")
                node=node[part]
            if not isinstance(node,dict) or parts[-1] in node:
                raise ValueError("field exists or is not an object member")
            witness={"kind":"fact","source":key,"pointer":pointer,
                     "expected_hash":ABSENT_WITNESS_HASH,"expected_version":ver,
                     "expected_authority":self.memory._authority(lvl,author)}
            slot=("fact",key,pointer)
            previous=self._witnesses.get(slot)
            if previous and (previous["expected_hash"]!=witness["expected_hash"] or
                             previous["expected_authority"]!=witness["expected_authority"]):
                raise Stale("negative source observation conflicted with earlier read")
            self._witnesses[slot]=witness
            c.execute("COMMIT")
            return True

    def patch_fact(self, key: str, changes: list[dict], *, job_fences=()) -> int:
        """Patch fields already observed and advance only our own read witnesses.

        The transaction validates the complete earlier read set and returns its
        exact post-write state. Rebinding to that state prevents self-staleness
        without silently refreshing reads to another worker's later write.
        """
        if not isinstance(changes,list) or not 1<=len(changes)<=64:
            raise ValueError("patch requires 1..64 operations")
        for operation in changes:
            if not isinstance(operation,dict):
                raise ValueError("invalid patch operation")
            pointer=operation.get("path")
            Memory._pointer_parts(pointer)
            previous=self._witnesses.get(("fact",key,pointer))
            expected=operation.get("expected_hash")
            observed=ABSENT_WITNESS_HASH if expected is None else expected
            if previous is None or previous["expected_hash"]!=observed:
                raise Stale("read each exact patch field (or its absence) before editing it")
        receipt=self.memory.patch_fact(self.actor,key,changes,
            read_manifest=self.manifest(),return_snapshot=True,job_fences=job_fences)
        updated=dict(self._witnesses)
        fallback=False
        for slot,witness in self._witnesses.items():
            if slot[:2]!=("fact",key):
                continue
            try:
                actual=witness_hash(receipt["value"],witness["pointer"])
            except (KeyError,IndexError,ValueError,TypeError):
                # A replaced ancestor removed this path. Conservatively witness
                # the resulting whole object rather than inventing an absence.
                del updated[slot]
                fallback=True
                continue
            updated[slot]={**witness,"expected_hash":actual,
                "expected_version":receipt["version"],"expected_authority":receipt["authority"]}
        if fallback:
            updated[("fact",key,"")]={"kind":"fact","source":key,"pointer":"",
                "expected_hash":digest(receipt["value"]),"expected_version":receipt["version"],
                "expected_authority":receipt["authority"]}
        self._witnesses=updated
        return receipt["version"]

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
