"""One budget shared by every generation, repair, provider retry, and child."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import os
import re
import threading
from time import perf_counter, sleep

import httpx

from ..agent import MODEL, ConfigError


class BudgetExceeded(RuntimeError):pass


def _provider_retry_delay(response,attempt):
    """Honor Retry-After and RPC RetryInfo without retaining provider error text."""
    delay=float(2**attempt)
    if response is None:return delay
    header=response.headers.get('Retry-After')
    if header:
        try:delay=max(delay,float(header))
        except ValueError:
            try:delay=max(delay,(parsedate_to_datetime(header)-datetime.now(timezone.utc)).total_seconds())
            except (TypeError,ValueError,OverflowError):pass
    try:
        details=response.json().get('error',{}).get('details',[])
        for item in details:
            if item.get('@type','').endswith('/google.rpc.RetryInfo'):
                value=item.get('retryDelay','')
                if isinstance(value,str) and re.fullmatch(r'\d+(?:\.\d+)?s',value):
                    delay=max(delay,float(value[:-1]))
    except (ValueError,TypeError,AttributeError):pass
    return delay


@dataclass(frozen=True)
class Limits:
    model_calls:int=24
    provider_attempts:int=36
    total_tokens:int=80000
    output_tokens:int=1024
    wall_seconds:float=600
    unit_turns:int=5
    temperature:float=.2
    thinking_level:str='minimal'

    def validate(self):
        for name in ('model_calls','provider_attempts','total_tokens','output_tokens','unit_turns'):
            if type(getattr(self,name)) is not int or getattr(self,name)<1:raise ValueError('invalid '+name)
        if self.wall_seconds<=0 or self.thinking_level not in {'minimal','high'}:raise ValueError('invalid wall/thinking budget')
        if not 0<=self.temperature<=2:raise ValueError('invalid temperature')
        return self


class MeteredGemma:
    """Pinned Gemini REST protocol; secret headers never enter experiment records."""
    def __init__(self,limits:Limits,model=MODEL,*,key=None,transport=None):
        self.limits=limits.validate()
        self.model=model
        self._key=key or os.getenv('GEMINI_API_KEY')
        if not self._key:raise ConfigError('GEMINI_API_KEY is required for live evaluation')
        if not re.fullmatch(r'[A-Za-z0-9._-]+',model):raise ValueError('invalid model ID')
        self.transport=transport
        self.started=perf_counter()
        self.lock=threading.RLock()
        self.calls=0;self.attempts=0;self.count_requests=0;self.tokens=0;self.observed_tokens=0;self.reserved=0
        self.records=[];self.last_usage={};self.budget_exhausted=False
        self.usage_complete=True
        self.cooldown_until=0.0;self.cooldown_seconds=0.0

    def _remaining(self):
        remaining=self.limits.wall_seconds-(perf_counter()-self.started)
        if remaining<=0:
            self.budget_exhausted=True
            raise BudgetExceeded('task wall-clock budget exhausted')
        return remaining

    def generate(self,contents,tools,system):
        with self.lock:
            self._wait_for_cooldown()
            self._remaining()
            if self.calls>=self.limits.model_calls:
                self.budget_exhausted=True;raise BudgetExceeded('shared model-call budget exhausted')
            self.calls+=1
        payload={'systemInstruction':{'parts':[{'text':system}]},'contents':contents,
            'generationConfig':{'temperature':self.limits.temperature,'maxOutputTokens':self.limits.output_tokens,
                'thinkingConfig':{'thinkingLevel':self.limits.thinking_level}},
            'tools':[{'functionDeclarations':tools}]}
        base=f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}'
        reservation=0
        with httpx.Client(transport=self.transport,timeout=min(100,self._remaining())) as client:
            with self.lock:self.count_requests+=1
            counted=client.post(base+':countTokens',headers={'x-goog-api-key':self._key},json={
                'generateContentRequest':{'model':'models/'+self.model,**payload}})
            counted.raise_for_status()
            prompt=counted.json()['totalTokens']
            if type(prompt) is not int or prompt<0:raise RuntimeError('invalid token-count response')
            with self.lock:
                available=self.limits.total_tokens-self.tokens-self.reserved-prompt
                allowed=min(self.limits.output_tokens,available)
                if allowed<1:
                    self.budget_exhausted=True;raise BudgetExceeded('shared token budget exhausted')
                payload['generationConfig']['maxOutputTokens']=allowed
                reservation=prompt+allowed
                self.reserved+=reservation
            try:
                for attempt in range(3):
                    with self.lock:
                        self._wait_for_cooldown()
                        remaining=self._remaining()
                        if self.attempts>=self.limits.provider_attempts:
                            self.budget_exhausted=True;raise BudgetExceeded('provider-attempt budget exhausted')
                        if self.tokens+self.reserved>self.limits.total_tokens:
                            self.budget_exhausted=True;raise BudgetExceeded('retry would exceed reserved token budget')
                        self.attempts+=1
                    began=perf_counter()
                    try:
                        response=client.post(base+':generateContent',headers={'x-goog-api-key':self._key},
                                             json=payload,timeout=min(100,remaining))
                    except (httpx.TimeoutException,httpx.NetworkError) as exc:
                        with self.lock:
                            self.usage_complete=False
                            self.tokens+=reservation
                            delay=_provider_retry_delay(None,attempt)
                            self.cooldown_until=max(self.cooldown_until,perf_counter()+delay)
                            self.records.append({'type':'transport_error','error':type(exc).__name__,
                                'attempt':attempt+1,'retry_delay_seconds':delay,'elapsed_seconds':perf_counter()-began})
                        if attempt==2:raise
                    else:
                        if response.is_success:
                            data=response.json();usage=data.get('usageMetadata',{})
                            with self.lock:
                                self.last_usage=usage
                                charged=usage.get('totalTokenCount')
                                if not isinstance(charged,int):
                                    self.usage_complete=False;charged=reservation
                                self.tokens+=charged
                                if isinstance(usage.get('totalTokenCount'),int):self.observed_tokens+=charged
                                self.records.append({'type':'response','status':response.status_code,
                                    'response_id':data.get('responseId'),'usage':usage,
                                    'elapsed_seconds':perf_counter()-began,'attempt':attempt+1})
                                if charged>reservation or self.tokens>self.limits.total_tokens:
                                    self.budget_exhausted=True
                                    raise BudgetExceeded('provider usage exceeded reserved budget')
                            candidates=data.get('candidates',[])
                            if not candidates or not candidates[0].get('content',{}).get('parts'):
                                raise RuntimeError('provider returned no usable content parts')
                            return candidates[0]['content']
                        with self.lock:
                            # Unknown failed-attempt usage consumes its full
                            # reservation; never silently treat it as free.
                            self.tokens+=reservation;self.usage_complete=False
                            retryable=response.status_code in {408,429,500,502,503,504}
                            delay=_provider_retry_delay(response,attempt) if retryable else 0
                            if retryable:self.cooldown_until=max(self.cooldown_until,perf_counter()+delay)
                            self.records.append({'type':'http_error','status':response.status_code,
                                'attempt':attempt+1,'retry_delay_seconds':delay,'elapsed_seconds':perf_counter()-began})
                        if response.status_code not in {408,429,500,502,503,504} or attempt==2:
                            response.raise_for_status()
            finally:
                with self.lock:self.reserved-=reservation

    def _wait_for_cooldown(self):
        delay=max(0,self.cooldown_until-perf_counter())
        if not delay:return
        if delay>=self._remaining():
            self.budget_exhausted=True
            raise BudgetExceeded('provider cooldown exceeds task wall budget')
        started=perf_counter();sleep(delay)
        self.cooldown_seconds+=perf_counter()-started

    def summary(self):
        with self.lock:
            return {'model_calls':self.calls,'provider_attempts':self.attempts,
                'provider_retries':sum(r.get('attempt',1)>1 for r in self.records),
                'count_tokens_requests':self.count_requests,'total_tokens':self.observed_tokens if self.usage_complete else None,
                'provider_cooldown_seconds':self.cooldown_seconds,
                'observed_known_tokens':self.observed_tokens,'budget_charged_tokens':self.tokens,
                'usage_complete':self.usage_complete,'budget_exhausted':self.budget_exhausted,
                'wall_seconds':perf_counter()-self.started,'limits':asdict(self.limits),'requests':list(self.records)}
