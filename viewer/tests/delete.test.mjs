import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require=createRequire(import.meta.url);
function compile(file) {
  const source=readFileSync(new URL(`../src/${file}`,import.meta.url),'utf8');
  const {outputText}=ts.transpileModule(source,{
    compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},
  });
  const exports={};new Function('require','exports',outputText)(require,exports);return exports;
}
const {deleteDocument}=compile('api.ts');
const DeleteDialog=compile('DeleteDialog.tsx').default;

// Only mocked requests: these tests never contact a server or remove files.
test('delete sends the exact document route and accepts an empty 204 response',async()=>{
  const original=globalThis.fetch;
  const calls=[];
  globalThis.fetch=async(url,options)=>{calls.push([url,options]);return new Response(null,{status:204});};
  try {
    assert.equal(await deleteDocument('document/id'),'deleted');
    assert.deepEqual(calls,[['/v1/jobs/document%2Fid',{method:'DELETE'}]]);
  } finally {globalThis.fetch=original;}
});

test('already removed document requests a local refresh rather than throwing',async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async()=>new Response('',{status:404});
  try {assert.equal(await deleteDocument('missing'),'missing');}
  finally {globalThis.fetch=original;}
});

test('failed deletion preserves the server explanation',async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:'storage_error',message:'Unable to remove stored files.'}}),{status:500});
  try {await assert.rejects(deleteDocument('job'),/Unable to remove stored files/);}
  finally {globalThis.fetch=original;}
});

test('confirmation names permanent upload/result removal and processing cancellation',()=>{
  const html=renderToStaticMarkup(React.createElement(DeleteDialog,{
    job:{file_name:'active.pdf',status:'running'},busy:false,error:'',onCancel(){},onConfirm(){},
  }));
  assert.ok(html.includes('aria-labelledby="delete-title"'));
  assert.ok(html.includes('aria-describedby="delete-description"'));
  assert.ok(html.includes('active.pdf'));
  assert.ok(html.includes('original upload, extracted results, and saved images'));
  assert.ok(html.includes('permanently removed'));
  assert.ok(html.includes('processing job will also be stopped'));
  assert.ok(html.includes('Keep document'));
  assert.ok(html.includes('Delete document'));
});

test('deletion pending state disables both actions and escapes filenames',()=>{
  const html=renderToStaticMarkup(React.createElement(DeleteDialog,{
    job:{file_name:'<img onerror=bad>',status:'done'},busy:true,error:'',onCancel(){},onConfirm(){},
  }));
  assert.equal((html.match(/disabled=""/g)??[]).length,2);
  assert.ok(html.includes('Deleting…'));
  assert.ok(html.includes('&lt;img onerror=bad&gt;'));
  assert.ok(!html.includes('<img'));
});
