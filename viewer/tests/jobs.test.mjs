import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
const source=readFileSync(new URL('../src/jobs.ts',import.meta.url),'utf8');
const {outputText}=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}});
const exports={};new Function('exports',outputText)(exports);
const {newestUploadsFirst,updateJob}=exports;
const older={job_id:'older',created_at:'2026-10-24T10:00:00+00:00',status:'done'};
const newer={job_id:'newer',created_at:'2026-10-24T11:00:00+00:00',status:'running'};

test('selecting or refreshing an older document preserves newest-upload order',()=>{
  const list=[newer,older];
  const updated=updateJob(list,{...older,current_stage:'done'});
  assert.deepEqual(updated.map(job=>job.job_id),['newer','older']);
  assert.deepEqual(list,[newer,older]);
  assert.equal(updated[1].current_stage,'done');
});

test('SSE updates replace a job without duplicates or order changes',()=>{
  let jobs=[newer,older];
  for(let i=0;i<5;i++)jobs=updateJob(jobs,{...older,progress:i/5});
  assert.equal(jobs.length,2);
  assert.deepEqual(jobs.map(job=>job.job_id),['newer','older']);
});

test('new uploads sort first and matching creation times use a stable identifier tie',()=>{
  const newest={job_id:'z',created_at:'2026-10-24T12:00:00+00:00'};
  assert.equal(updateJob([newer,older],newest)[0].job_id,'z');
  const tied={...newest,job_id:'a'};
  assert.deepEqual(newestUploadsFirst([tied,newest]).map(job=>job.job_id),['z','a']);
});
