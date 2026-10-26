import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const source = readFileSync(new URL('../src/Markdown.tsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const exports = {};
new Function('require', 'exports', outputText)(require, exports);
const render = text => renderToStaticMarkup(React.createElement(exports.default, { text }));

test('document markup is rendered as escaped text, never active HTML', () => {
  const html = render('<script>alert(1)</script>\n\n<img src=x onerror=alert(2)>');
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img'));
});

test('renders headings, paragraphs, lists and inline emphasis', () => {
  const html = render('# Summary\n\nA **strong** paragraph with `code`.\n\n- First\n- Second');
  assert.ok(html.includes('<h1>Summary</h1>'));
  assert.ok(html.includes('<strong>strong</strong>'));
  assert.ok(html.includes('<code>code</code>'));
  assert.ok(html.includes('<ul><li>First</li><li>Second</li></ul>'));
});

test('table blank cells retain their column positions', () => {
  const html = render('| Name | Empty | Value |\n| --- | --- | --- |\n| A | | 3 |');
  assert.ok(html.includes('<td>A</td><td></td><td>3</td>'));
  assert.equal((html.match(/<th>/g) ?? []).length, 3);
});

test('escaped literal pipes stay inside their table cell', () => {
  const html=render('| Name | Value |\n| --- | --- |\n| A\\|B | 3 |');
  assert.ok(html.includes('<td>A|B</td><td>3</td>'));
  assert.equal((html.match(/<td>/g)??[]).length,2);
});

test('fenced code and empty output remain safe and informative', () => {
  const code = render('```html\n<script>unsafe()</script>\n```');
  assert.ok(code.includes('<pre><code>&lt;script&gt;unsafe()&lt;/script&gt;</code></pre>'));
  assert.ok(render('').includes('No readable text was found.'));
});

test('separated numbered items preserve their actual markers instead of restarting at one',()=>{
  const html=render('1. First question\n\nFirst continuation paragraph.\n\n2. Second question\n\nSecond continuation paragraph.\n\n3. Third question');
  assert.ok(html.includes('<ol start="1"><li value="1">First question</li></ol>'));
  assert.ok(html.includes('<ol start="2"><li value="2">Second question</li></ol>'));
  assert.ok(html.includes('<ol start="3"><li value="3">Third question</li></ol>'));
  assert.ok(html.includes('<p>First continuation paragraph.</p>'));
});

test('explicit nonconsecutive numbers survive in one ordered list',()=>{
  const html=render('3. Third\n7) Seventh\n4. Fourth');
  assert.ok(html.includes('<ol start="3"><li value="3">Third</li><li value="7">Seventh</li><li value="4">Fourth</li></ol>'));
});

test('blank lines between same-kind items retain numbering and mixed list kinds stay separate',()=>{
  const html=render('2. Second\n\n3. Third\n\n- Bullet\n- Another');
  assert.ok(html.includes('<ol start="2"><li value="2">Second</li><li value="3">Third</li></ol>'));
  assert.ok(html.includes('<ul><li>Bullet</li><li>Another</li></ul>'));
});
