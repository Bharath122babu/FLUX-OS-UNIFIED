"""Bounded project-scoped model tools over the conditional shared-memory kernel."""
from __future__ import annotations

import re

from .kernel import Memory, Observation, Principal, Stale, compact, digest


def project_memory_key(project_id: str) -> str:
    if not isinstance(project_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',project_id):
        raise ValueError('invalid project ID')
    return 'shared:project:'+project_id


class SharedMemoryTools:
    def __init__(self,memory:Memory,actor:Principal,observation:Observation,
                 *,project_id:str|None,session_id:str,key:str|None=None,job_fences=None):
        self.memory=memory
        self.actor=actor
        self.observation=observation
        self.job_fences=job_fences if job_fences is not None else []
        # key overrides are internal to the harness for inheriting a parent
        # session. Model tool arguments never select a different project/key.
        self.key=key or (project_memory_key(project_id) if project_id is not None
                        else 'shared:task:'+digest(session_id)[:32])
        self.initialized=False

    def _ensure(self):
        if self.initialized:
            return
        try:
            self.memory.fact_head(self.actor,self.key)
        except KeyError:
            try:
                self.memory.put_fact(self.actor,self.key,{},expected_version=0,job_fences=self.job_fences)
            except Stale:
                # A concurrent first user created the same project note store.
                self.memory.fact_head(self.actor,self.key)
        self.initialized=True

    @staticmethod
    def _bounded(value):
        if len(compact(value).encode('utf8'))>16_000:
            raise ValueError('shared-memory result exceeds 16 KB; read a narrower field')
        return value

    def read(self,pointer:str='') -> dict:
        if pointer!='':
            Memory._pointer_parts(pointer)
        self._ensure()
        try:
            value=self.observation.fact(self.key,pointer)
            present=True
        except KeyError:
            self.observation.absent_fact(self.key,pointer)
            value=None
            present=False
        witness=next(w for w in self.observation.manifest()
                     if (w['kind'],w['source'],w['pointer'])==('fact',self.key,pointer))
        return self._bounded({'path':pointer,'present':present,'value':value,
            'expected_hash':witness['expected_hash'] if present else None,
            'version':witness['expected_version'],'trust':'UNVERIFIED_SHARED_NOTES'})

    def patch(self,changes:list[dict]) -> dict:
        # The model-facing interface stores bounded text notes. The kernel's
        # trusted Python API additionally supports arbitrary JSON object values.
        if not isinstance(changes,list) or not 1<=len(changes)<=16:
            raise ValueError('expected 1..16 shared note changes')
        for change in changes:
            if not isinstance(change,dict) or not isinstance(change.get('value'),str):
                raise ValueError('shared note values must be text')
            if len(change['value'].encode('utf8'))>8192:
                raise ValueError('shared note exceeds 8 KB')
        self._ensure()
        version=self.observation.patch_fact(self.key,changes,job_fences=self.job_fences)
        return {'version':version,'paths':[change['path'] for change in changes],
                'trust':'UNVERIFIED_SHARED_NOTES'}

    def record_claim(self,predicate:str,value:str,source:str) -> dict:
        if not isinstance(value,str) or len(value.encode('utf8'))>8192:
            raise ValueError('claim value must be text of at most 8 KB')
        return self.memory.record_claim(self.actor,self.key,predicate,value,source,job_fences=self.job_fences)

    def claims(self,predicate:str) -> dict:
        if not isinstance(predicate,str) or not 1<=len(predicate)<=200:
            raise ValueError('predicate must be 1..200 characters')
        return self._bounded(self.memory.claims(self.actor,self.key,predicate))
