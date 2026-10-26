import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require=createRequire(import.meta.url);
const cache=new Map();
function compile(file){
  if(cache.has(file))return cache.get(file);
  const fileUrl=new URL(`../src/${file}`,import.meta.url);
  const source=readFileSync(fileUrl,'utf8');
  const {outputText}=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}});
  const exports={};cache.set(file,exports);
  function localRequire(name){
    if(!name.startsWith('.'))return require(name);
    const base=new URL(name,fileUrl);
    for(const suffix of ['.tsx','.ts'])if(existsSync(new URL(base.href+suffix)))return compile(new URL(base.href+suffix).pathname.split('/').pop());
    throw new Error(`Missing local module ${name}`);
  }
  new Function('require','exports',outputText)(localRequire,exports);
  return exports;
}
const {activeSourcePage,paneScrollTarget,SourcePage}=compile('App.tsx');

test('continuous source scrolling activates pages as their labels enter the pane',()=>{
  const tops=[17,817,1617];
  assert.equal(activeSourcePage(tops,0,400),0);
  assert.equal(activeSourcePage(tops,750,400),1);
  assert.equal(activeSourcePage(tops,1600,400),2);
  assert.equal(activeSourcePage(tops,400,400),0);
  assert.equal(activeSourcePage([],0,400),0);
});

test('page navigation computes a local pane offset without scrolling the document',()=>{
  assert.equal(paneScrollTarget(500,300,750),950);
  assert.equal(paneScrollTarget(500,300,-150),50);
  assert.equal(paneScrollTarget(0,300,200),0);
});

const block={id:'shared-id',type:'paragraph',text:'Text',markdown:'Text',source:'read',confidence:null,bbox:[10,20,60,50]};
const props={jobId:'job',selected:null,onSelect(){},hover:null,onHover(){},ocrOnly:false,heat:false,arrows:true};
test('each stacked preview loads lazily and keeps page-local box coordinates and arrow identifiers',()=>{
  const render=number=>renderToStaticMarkup(React.createElement(SourcePage,{...props,page:{page_number:number,width:100,height:200,blocks:[block]}}));
  const first=render(1),second=render(2);
  assert.ok(first.includes('loading="lazy"'));
  assert.ok(first.includes('decoding="async"'));
  assert.ok(first.includes('/pages/1/image'));
  assert.ok(second.includes('/pages/2/image'));
  assert.ok(first.includes('left:10%;top:10%;width:50%;height:15%'));
  assert.ok(first.includes('id="arrow-1"'));
  assert.ok(second.includes('id="arrow-2"'));
  assert.ok(!first.includes('class="page-scroll"'));
});
