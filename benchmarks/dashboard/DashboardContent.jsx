import React from 'react';
import { DataComponent, DataTable, EvidenceChart, MetricCard, SectionHeader,
  SortableItem, SortableRegion, useDataApp } from '../../data-app-public.jsx';
const number=(v,d=1)=>v==null?'Pending':Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
const rate=v=>v==null?'Unavailable':`${number(v*100,2)}%`;
const pretty=v=>String(v).replaceAll('_',' ');
const gateColumns=[{key:'metric',label:'Metric',renderCell:pretty},
  {key:'numerator',label:'Numerator',type:'number'},{key:'denominator',label:'Denominator',type:'number'},
  {key:'rate',label:'Rate',type:'number',renderCell:rate}];
const matrixColumns=[{key:'writers',label:'Writers',type:'number'},{key:'scenario',label:'Scenario',renderCell:pretty},
  {key:'committed',label:'Committed',type:'number'},{key:'conflicts',label:'Expected conflicts',type:'number'},
  {key:'errors',label:'Errors',type:'number'},{key:'p95_ms',label:'P95 (ms)',type:'number',renderCell:v=>number(v,2)},
  {key:'throughput',label:'Commits/s',type:'number',renderCell:v=>number(v,2)}];
const runColumns=[{key:'task_id',label:'Task'},{key:'arm',label:'Arm'},
  {key:'trial',label:'Trial',type:'number'},{key:'status',label:'Status',renderCell:pretty},
  {key:'verified_completion',label:'Verified',renderCell:v=>v==null?'Pending':v?'Yes':'No'}];
const armColumns=[{key:'arm',label:'Arm'},
  {key:'completion',label:'Verified / attempted',renderCell:v=>v?`${v.numerator}/${v.denominator} (${rate(v.rate)})`:'Pending'},
  {key:'model_calls',label:'Model calls',type:'number'},
  {key:'total_tokens',label:'Total tokens',type:'number',renderCell:(v,r)=>v==null?`Unknown (≥${number(r.observed_known_tokens,0)} observed)`:number(v,0)},
  {key:'provider_http_429',label:'HTTP 429',type:'number'},
  {key:'provider_http_5xx',label:'HTTP 5xx',type:'number'},
  {key:'regenerated_artifacts',label:'Regenerated',type:'number'},
  {key:'reused_artifacts',label:'Reused',type:'number'},
  {key:'p95_seconds',label:'P95 (s)',type:'number',renderCell:v=>number(v,2)},
  {key:'cost_per_verified_completion_usd',label:'USD / success',type:'number',renderCell:v=>v==null?'Unavailable':number(v,4)}];
const attackColumns=[{key:'category',label:'Injected failure',renderCell:pretty},{key:'seed',label:'Seed',type:'number'},
  {key:'passed',label:'Invariant held',renderCell:v=>v?'Yes':'No'},
  {key:'observation',label:'Gate outcome'},{key:'observed_exit_code',label:'Process exit',type:'number'},
  {key:'external_effect_outcome',label:'Effect outcome',renderCell:v=>v?pretty(v):'—'}];
export function DashboardContent(){
  const {reviewedRows}=useDataApp();
  const headlines=reviewedRows('headlines');
  const matrix=reviewedRows('concurrency');
  const table=(id,title,queryId,columns,searchable=true)=>(
    <SortableItem key={id} id={id} label={title} kind="table" span={12}>
      <DataComponent id={id} title={title} queryId={queryId} kind="table" variant="card"
        sourceRows={reviewedRows(queryId)} displayRows={reviewedRows(queryId)}>
        <DataTable rows={reviewedRows(queryId)} columns={columns} searchable={searchable} caption={title}/>
      </DataComponent>
    </SortableItem>);
  const rows=[
    {id:'bench:metrics-a',kind:'metrics',items:headlines.slice(0,3).map(r=>'headline-'+r.key)},
    {id:'bench:metrics-b',kind:'metrics',items:headlines.slice(3).map(r=>'headline-'+r.key),spacing:'metrics'},
    {id:'bench:gates',items:['kernel-gates'],header:<SectionHeader id="gates-title" title="Correctness and selective reuse"/>},
    {id:'bench:scaling',items:['throughput-chart','latency-chart'],header:<SectionHeader id="scaling-title" title="Kernel scaling across three seeds"/>},
    {id:'bench:matrix',items:['matrix-records'],spacing:'continuation'},
    {id:'bench:pilot',items:['arm-results'],header:<SectionHeader id="pilot-title" title="Four-task B0 vs F0 pilot"/>},
    {id:'bench:uncertainty',items:['paired-uncertainty'],spacing:'continuation'},
    {id:'bench:attempts',items:['pilot-records'],spacing:'continuation'},
    {id:'bench:adversarial',items:['attack-records'],header:<SectionHeader id="attack-title" title="Adversarial and crash boundaries"/>},
    {id:'bench:boundary',items:['observation-boundary'],spacing:'continuation'}
  ];
  return <SortableRegion id="bench:canvas" variant="canvas" spacing="standard" columns={12} rows={rows} label="Benchmark evidence">
    {headlines.map(row=><SortableItem key={row.key} id={'headline-'+row.key} label={row.label} kind="metric" span={4}>
      <MetricCard id={'headline-'+row.key} title={row.label} queryId="headlines" sourceRows={[row]} displayRows={[row]}
        value={row.value==null?'Pending':row.unit==='percent'?rate(row.value):`${number(row.value)} ${row.unit}`}
        comparison={row.detail} deltaTone="neutral" description={row.detail}/>
    </SortableItem>)}
    {table('kernel-gates','Defined populations and observed rates','gates',gateColumns,false)}
    <SortableItem id="throughput-chart" label="Committed writes per second" kind="chart" span={6}>
      <EvidenceChart id="throughput-chart" title="Committed writes per second" queryId="concurrency" variant="card"
        rows={matrix} sourceRows={matrix} height={270}
        spec={{type:'line',x:'writers',y:'throughput',series:'scenario',stackable:false,valueDecimals:2}}/>
    </SortableItem>
    <SortableItem id="latency-chart" label="P95 commit latency (ms)" kind="chart" span={6}>
      <EvidenceChart id="latency-chart" title="P95 commit latency (ms)" queryId="concurrency" variant="card"
        rows={matrix} sourceRows={matrix} height={270}
        spec={{type:'line',x:'writers',y:'p95_ms',series:'scenario',stackable:false,valueDecimals:2}}/>
    </SortableItem>
    {table('matrix-records','Concurrency matrix · kernel writers, including expected rejections','concurrency',matrixColumns)}
    {table('arm-results','Matched arms · actual Gemma calls and independent acceptance','live_arms',armColumns,false)}
    <SortableItem id="paired-uncertainty" label="Paired completion difference" kind="custom" span={12}>
      <DataComponent id="paired-uncertainty" title="Paired completion difference" queryId="paired_comparison" variant="card"
        sourceRows={reviewedRows('paired_comparison')} displayRows={reviewedRows('paired_comparison')}>
        {reviewedRows('paired_comparison').map((row,i)=><div key={i} data-reviewed-rows>
          <p>{row.difference_pp==null?'Paired comparison pending':`F0 − B0: ${number(row.difference_pp,2)} percentage points; 95% interval ${number(row.low_pp,2)} to ${number(row.high_pp,2)}; ${row.paired_runs} pairs across ${row.tasks} tasks.`}</p>
          {row.caveat&&<p>{row.caveat}</p>}
        </div>)}
      </DataComponent>
    </SortableItem>
    {table('pilot-records','Eight scheduled paired runs · every failure retained','live_runs',runColumns,false)}
    {table('attack-records','Injected failures · synthetic acceptance in fault probes','attacks',attackColumns)}
    <SortableItem id="observation-boundary" label="Dependency observation boundary" kind="custom" span={12}>
      <DataComponent id="observation-boundary" title="Dependency observation boundary" queryId="limitations" variant="card"
        sourceRows={reviewedRows('limitations')} displayRows={reviewedRows('limitations')}>
        {reviewedRows('limitations').map(row=><p key={row.id} data-reviewed-rows>{row.rule}</p>)}
      </DataComponent>
    </SortableItem>
  </SortableRegion>;
}
