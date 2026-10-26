import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
function compile(file) {
  const source = readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const exports = {};
  new Function('require', 'exports', outputText)(require, exports);
  return exports;
}
const { UploadProgress, ProcessingProgress } = compile('ProgressPanel.tsx');
const { uploadDocument } = compile('api.ts');
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));

test('upload panel is immediately visible at zero and uses measured transfer progress', () => {
  const html = render(UploadProgress, { stage:'uploading', percent:0, fileName:'document.pdf' });
  assert.ok(html.includes('Uploading document'));
  assert.ok(html.includes('File upload progress'));
  assert.ok(html.includes('value="0"'));
  assert.ok(html.includes('document.pdf'));
  assert.ok(render(UploadProgress, { stage:'uploading', percent:42, fileName:'a.pdf' }).includes('42%'));
});

test('unknown transfer totals and server validation use indeterminate progress', () => {
  const unknown = render(UploadProgress, { stage:'uploading', percent:null, fileName:'a.pdf' });
  assert.ok(!unknown.includes('value='));
  const validating = render(UploadProgress, { stage:'validating', percent:100, fileName:'a.pdf' });
  assert.ok(validating.includes('Checking your upload'));
  assert.ok(!validating.includes('value='));
  assert.ok(!validating.includes('100%'));
});

test('queued and processing panels retain real stage, progress and connection status', () => {
  const job = {status:'running',current_stage:'reading_pages',progress:0.4,error:null};
  const running = render(ProcessingProgress, {job,live:true});
  assert.ok(running.includes('Processing: reading pages'));
  assert.ok(running.includes('value="0.4"'));
  assert.ok(running.includes('40%'));
  assert.ok(running.includes('Live updates'));
  const queued = render(ProcessingProgress, {job:{...job,status:'queued',progress:0},live:false});
  assert.ok(queued.includes('Queued for processing'));
  assert.ok(queued.includes('Checking for updates'));
});

class FakeXHR {
  static latest;
  upload = {};
  responseText = '';
  status = 0;
  constructor() { FakeXHR.latest = this; }
  open(method, url) { this.method = method; this.url = url; }
  send(form) { this.form = form; }
}
function installXHR() {
  const original = globalThis.XMLHttpRequest;
  globalThis.XMLHttpRequest = FakeXHR;
  return () => { globalThis.XMLHttpRequest = original; };
}

test('upload helper reports browser byte events then accepts the queued job', async () => {
  const restore = installXHR();
  try {
    const progress = []; let transferred = false;
    const pending = uploadDocument(new File(['document'], 'a.pdf'), p => progress.push(p), () => {transferred=true;});
    const xhr = FakeXHR.latest;
    assert.equal(xhr.method, 'POST');
    assert.equal(xhr.url, '/v1/documents');
    assert.equal(xhr.form.get('file').name, 'a.pdf');
    xhr.upload.onprogress({lengthComputable:true, loaded:25, total:100});
    xhr.upload.onprogress({lengthComputable:false, loaded:50, total:0});
    xhr.upload.onload();
    assert.deepEqual(progress, [25,null]);
    assert.equal(transferred,true);
    xhr.status=202; xhr.responseText=JSON.stringify({job_id:'job',status:'queued',already_exists:false}); xhr.onload();
    assert.equal((await pending).status,'queued');
  } finally { restore(); }
});

test('upload rejection preserves clear server reason', async () => {
  const restore = installXHR();
  try {
    const pending = uploadDocument(new File([], 'empty.pdf'), () => {}, () => {});
    const rejection = assert.rejects(pending, /The file is empty/);
    FakeXHR.latest.status=422;
    FakeXHR.latest.responseText=JSON.stringify({error:{code:'empty_file',message:'The file is empty'}});
    FakeXHR.latest.onload();
    await rejection;
  } finally { restore(); }
});

test('upload connection failure is actionable', async () => {
  const restore = installXHR();
  try {
    const pending = uploadDocument(new File(['x'], 'a.pdf'), () => {}, () => {});
    const rejection = assert.rejects(pending, /Check the connection/);
    FakeXHR.latest.onerror();
    await rejection;
  } finally { restore(); }
});
