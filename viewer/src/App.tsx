import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import { deleteDocument, jobUrl, request, uploadDocument } from './api';
import DeleteDialog from './DeleteDialog';
import { newestUploadsFirst, updateJob } from './jobs';
import Markdown from './Markdown';
import { ProcessingProgress, UploadProgress } from './ProgressPanel';
import type { UploadStage } from './ProgressPanel';
import type { Block, Job, Page, Result } from './types';

function Grid({block}:{block:Block}) {
  const cells=block.cells;
  const rows=block.rows??Math.max(0,...cells.map(c=>c.row+c.row_span));
  const columns=block.columns??Math.max(0,...cells.map(c=>c.col+c.col_span));
  if(!rows||!columns) return <p>{block.text||'No table cells detected.'}</p>;
  return <div className="table-scroll"><table className="cell-grid"><tbody>{Array.from({length:rows},(_,row)=><tr key={row}>
    {Array.from({length:columns},(_,col)=>{
      const cell=cells.find(c=>c.row===row&&c.col===col);
      if(!cell&&cells.some(c=>row>=c.row&&row<c.row+c.row_span&&col>=c.col&&col<c.col+c.col_span)) return null;
      const Cell=cell?.is_header?'th':'td';
      return <Cell key={col} rowSpan={cell?.row_span??1} colSpan={cell?.col_span??1}
        title={`Row ${row+1}, column ${col+1}${cell&&(cell.row_span>1||cell.col_span>1)?' (merged)':''}`}>{cell?.text??''}</Cell>;
    })}</tr>)}</tbody></table></div>;
}

export function SourcePage({page,jobId,selected,onSelect,hover,onHover,ocrOnly,heat,arrows}:{
  page:Page;jobId:string;selected:string|null;onSelect:(id:string)=>void;hover:string|null;
  onHover:(id:string|null)=>void;ocrOnly:boolean;heat:boolean;arrows:boolean;
}) {
  const [imageError,setImageError]=useState(false);
  useEffect(()=>setImageError(false),[jobId,page.page_number]);
  const blocks=page.blocks.filter(b=>!ocrOnly||b.source==='ocr');
  const position=(b:Block)=>({left:`${b.bbox[0]/page.width*100}%`,top:`${b.bbox[1]/page.height*100}%`,
    width:`${(b.bbox[2]-b.bbox[0])/page.width*100}%`,height:`${(b.bbox[3]-b.bbox[1])/page.height*100}%`});
  return <div className="paper" style={{aspectRatio:`${page.width||1}/${page.height||1}`}}>
    {!imageError?<img src={`${jobUrl(jobId)}/pages/${page.page_number}/image`} alt={`Original page ${page.page_number}`}
      loading="lazy" decoding="async" onError={()=>setImageError(true)}/>: <div className="image-error" role="status">Page preview unavailable. The extracted blocks are still available.</div>}
    {arrows&&<svg className="order-arrows" viewBox={`0 0 ${page.width} ${page.height}`} aria-hidden="true">
      <defs><marker id={`arrow-${page.page_number}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#2864ac"/></marker></defs>
      {blocks.slice(1).map((block,index)=>{const prev=blocks[index];return <line key={block.id}
        x1={(prev.bbox[0]+prev.bbox[2])/2} y1={(prev.bbox[1]+prev.bbox[3])/2}
        x2={(block.bbox[0]+block.bbox[2])/2} y2={(block.bbox[1]+block.bbox[3])/2} markerEnd={`url(#arrow-${page.page_number})`}/>;})}
    </svg>}
    {blocks.map(block=><button key={block.id} type="button" style={position(block)}
      className={`box box-${block.type} ${block.source==='ocr'?'box-ocr':''} ${block.confidence!==null&&block.confidence<0.6?'low-confidence':''} ${heat?(block.confidence===null?'heat-unknown':block.confidence<0.6?'heat-low':'heat-high'):''} ${selected===block.id||hover===block.id?'box-active':''}`}
      aria-label={`${block.type} block ${page.blocks.indexOf(block)+1}, ${block.source}${block.confidence===null?'':`, confidence ${Math.round(block.confidence*100)} percent`}`}
      aria-pressed={selected===block.id} onClick={()=>onSelect(block.id)}
      onMouseEnter={()=>onHover(block.id)} onMouseLeave={()=>onHover(null)}>
      <span>{page.blocks.indexOf(block)+1}</span></button>)}
  </div>;
}

export function activeSourcePage(tops:number[],scrollTop:number,viewportHeight:number):number {
  const probe=scrollTop+Math.min(viewportHeight*0.25,96);
  let active=0;
  tops.forEach((top,index)=>{if(top<=probe)active=index;});
  return active;
}

export function paneScrollTarget(scrollTop:number,paneTop:number,targetTop:number):number {
  return Math.max(0,scrollTop+targetTop-paneTop);
}

export default function App() {
  const [jobs,setJobs]=useState<Job[]>([]); const [selectedId,setSelectedId]=useState<string|null>(null);
  const [job,setJob]=useState<Job|null>(null); const [result,setResult]=useState<Result|null>(null);
  const [pageIndex,setPageIndex]=useState(0); const [blockId,setBlockId]=useState<string|null>(null);
  const [hover,setHover]=useState<string|null>(null); const [tab,setTab]=useState<'rendered'|'markdown'|'json'>('rendered');
  const [error,setError]=useState(''); const [notice,setNotice]=useState(''); const [uploading,setUploading]=useState(false);
  const [uploadStage,setUploadStage]=useState<UploadStage|null>(null);
  const [uploadPercent,setUploadPercent]=useState<number|null>(0);
  const [uploadFileName,setUploadFileName]=useState('');
  const [liveUpdates,setLiveUpdates]=useState(false);
  const [deleteTarget,setDeleteTarget]=useState<Job|null>(null);
  const [deleting,setDeleting]=useState(false); const [deleteError,setDeleteError]=useState('');
  const removedIds=useRef(new Set<string>());
  const [dragging,setDragging]=useState(false); const [ocrOnly,setOcrOnly]=useState(false);
  const [heat,setHeat]=useState(false); const [arrows,setArrows]=useState(false);
  const input=useRef<HTMLInputElement>(null);
  const sourceScroll=useRef<HTMLDivElement>(null);const blockScroll=useRef<HTMLDivElement>(null);
  const sourceFrame=useRef<number|null>(null);

  useEffect(()=>{
    if(!blockId||!result)return;
    const frame=requestAnimationFrame(()=>{
      const pane=blockScroll.current;
      const block=document.getElementById(`block-${result.pages[pageIndex]?.page_number}-${blockId}`);
      if(pane&&block)pane.scrollTo({top:Math.max(0,paneScrollTarget(pane.scrollTop,pane.getBoundingClientRect().top,block.getBoundingClientRect().top)-8),behavior:'smooth'});
    });
    return()=>cancelAnimationFrame(frame);
  },[blockId,pageIndex,result]);
  useEffect(()=>{
    sourceScroll.current?.scrollTo({top:0,behavior:'instant'});
    return()=>{if(sourceFrame.current!==null){cancelAnimationFrame(sourceFrame.current);sourceFrame.current=null;}};
  },[result]);

  useEffect(()=>{let active=true;
    request<Job[]>('/v1/jobs').then(data=>{if(active){const ordered=newestUploadsFirst(data);setJobs(ordered);if(ordered[0])setSelectedId(ordered[0].job_id);}})
      .catch(e=>{if(active)setError(e.message);});return()=>{active=false;};
  },[]);

  useEffect(()=>{
    if(!selectedId)return; let active=true;let loaded=false;let loading=false;
    setJob(null);setResult(null);setPageIndex(0);setBlockId(null);setHover(null);setError('');setLiveUpdates(false);
    const update=async(data:Job)=>{
      if(!active||removedIds.current.has(data.job_id))return;setJob(data);setJobs(old=>updateJob(old,data));
      setUploadStage(current=>current==='connecting'?null:current);
      if(data.status==='done')setNotice(current=>current==='Upload accepted. Reading your document.'?'Document ready to inspect.':current);
      if(data.status==='done'&&!loaded&&!loading){loading=true;
        try{const document=await request<Result>(`${jobUrl(selectedId)}/result`);if(active&&!removedIds.current.has(data.job_id)){setResult(document);loaded=true;setError('');}}
        catch(e){if(active&&!removedIds.current.has(data.job_id))setError((e as Error).message);}finally{loading=false;}
      }
    };
    const poll=()=>request<Job>(jobUrl(selectedId)).then(update).catch(e=>{if(active&&!removedIds.current.has(selectedId))setError(e.message);});
    void poll();const timer=window.setInterval(()=>{if(!loaded)void poll();},2000);
    const stream=new EventSource(`${jobUrl(selectedId)}/events`);
    stream.onopen=()=>{if(active)setLiveUpdates(true);};
    stream.addEventListener('progress',event=>{try{const data=JSON.parse((event as MessageEvent).data) as Job;void update(data);
      if(data.status==='done'||data.status==='failed')stream.close();}catch{/* polling recovers malformed events */}});
    stream.onerror=()=>{if(active)setLiveUpdates(false);stream.close();};
    return()=>{active=false;clearInterval(timer);stream.close();};
  },[selectedId]);

  async function upload(file:File) {
    if(uploading)return;setUploading(true);setUploadStage('uploading');setUploadPercent(0);setUploadFileName(file.name);setError('');setNotice('');
    try{
      const data=await uploadDocument(file,setUploadPercent,()=>setUploadStage('validating'));
      setUploadStage('connecting');
      setNotice(data.already_exists?'This file already exists. Showing its original job.':'Upload accepted. Reading your document.');
      if(data.job_id===selectedId){setJob(await request<Job>(jobUrl(data.job_id)));setUploadStage(null);}
      else setSelectedId(data.job_id);
      setJobs(newestUploadsFirst(await request<Job[]>('/v1/jobs')));
    }catch(e){setError((e as Error).message);setUploadStage(null);}finally{setUploading(false);if(input.current)input.current.value='';}
  }
  function choose(event:ChangeEvent<HTMLInputElement>){if(event.target.files?.[0])void upload(event.target.files[0]);}
  function drop(event:DragEvent){event.preventDefault();setDragging(false);if(event.dataTransfer.files[0])void upload(event.dataTransfer.files[0]);}
  function activatePage(index:number){if(index!==pageIndex){setPageIndex(index);setBlockId(null);setHover(null);}}
  function selectBlock(index:number,id:string){activatePage(index);setBlockId(id);}
  function trackSourcePage(){
    if(sourceFrame.current!==null)return;
    sourceFrame.current=requestAnimationFrame(()=>{
      sourceFrame.current=null;
      const pane=sourceScroll.current;if(!pane)return;
      const top=pane.getBoundingClientRect().top;
      const pages=Array.from(pane.querySelectorAll<HTMLElement>('[data-source-page]'));
      activatePage(activeSourcePage(pages.map(item=>paneScrollTarget(pane.scrollTop,top,item.getBoundingClientRect().top)),pane.scrollTop,pane.clientHeight));
    });
  }
  function changePage(index:number){
    setPageIndex(index);setBlockId(null);setHover(null);
    const pane=sourceScroll.current;
    const target=pane?.querySelector<HTMLElement>(`[data-source-page="${index}"]`);
    if(pane&&target)pane.scrollTo({top:paneScrollTarget(pane.scrollTop,pane.getBoundingClientRect().top,target.getBoundingClientRect().top),behavior:'instant'});
  }
  function askDelete(target:Job){setDeleteError('');setDeleteTarget(target);}
  async function confirmDelete(){
    if(!deleteTarget||deleting)return;
    const target=deleteTarget;setDeleting(true);setDeleteError('');
    try{
      const outcome=await deleteDocument(target.job_id);
      removedIds.current.add(target.job_id);
      const remaining=jobs.filter(item=>item.job_id!==target.job_id);
      setJobs(remaining);
      if(selectedId===target.job_id){setJob(null);setResult(null);setBlockId(null);setHover(null);setPageIndex(0);setLiveUpdates(false);setSelectedId(remaining[0]?.job_id??null);}
      setDeleteTarget(null);setError('');
      setNotice(outcome==='missing'?'This document was already removed.':`Deleted ${target.file_name}.`);
      if(outcome==='missing'){
        try{const refreshed=newestUploadsFirst((await request<Job[]>('/v1/jobs')).filter(item=>!removedIds.current.has(item.job_id)));setJobs(refreshed);if(selectedId===target.job_id)setSelectedId(refreshed[0]?.job_id??null);}
        catch{setError('The document was removed, but the document list could not refresh. Reload to try again.');}
      }
    }catch(e){setDeleteError((e as Error).message);}finally{setDeleting(false);}
  }
  const page=result?.pages[pageIndex]; const stats=result?.stats;
  const shown=page?.blocks.filter(block=>!ocrOnly||block.source==='ocr')??[];
  return <div className="app-shell">
    <aside className="sidebar" aria-label="Document library">
      <a className="brand" href="/" aria-label="rag-pre-ingest home"><span className="brand-mark" aria-hidden="true">▤</span><span>rag-pre-ingest<small>Document inspector</small></span></a>
      <div className={`upload-zone ${dragging?'dragging':''}`} onDragOver={e=>{e.preventDefault();setDragging(true);}}
        onDragLeave={()=>setDragging(false)} onDrop={drop}>
        <span className="upload-symbol" aria-hidden="true">↥</span><strong>Bring a document</strong><p>Drop a file here to inspect its content.</p>
        <button className="primary" onClick={()=>input.current?.click()} disabled={uploading||deleting}>{uploading?'Uploading…':'Choose a file'}</button>
        <input ref={input} type="file" onChange={choose} accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,.gif,.webp,.bmp,.tif,.tiff" aria-label="Upload document" hidden/>
        <small>PDF, Word, Excel, or image</small>
      </div>
      <div className="library-title"><div><h2>Documents</h2><small className="library-order">Newest uploads first</small></div><span>{jobs.length}</span></div>
      <nav className="jobs" aria-label="Recent documents">{jobs.map(item=><div key={item.job_id} className={`job-row ${selectedId===item.job_id?'selected':''}`}><button className={`job ${selectedId===item.job_id?'selected':''}`}
        aria-current={selectedId===item.job_id?'true':undefined} onClick={()=>{setNotice('');setSelectedId(item.job_id);}}>
        <span className="file-glyph" aria-hidden="true">▱</span><span className="job-label"><strong title={item.file_name}>{item.file_name}</strong>
          <small><span className={`status-dot ${item.status}`}/>{item.status==='done'?'Ready to inspect':item.status} <span className="file-type">{item.file_type}</span></small></span></button><button type="button" className="delete-job" aria-label={`Delete ${item.file_name}`} title={`Delete ${item.file_name}`} disabled={!!uploadStage||uploading||deleting} onClick={()=>askDelete(item)}><svg width="14" height="14" viewBox="0 0 20 20" aria-hidden="true"><path d="M4 6h12M8 3h4l1 3H7l1-3ZM5 6l1 11h8l1-11M8 9v5m4-5v5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg></button></div>)}
        {!jobs.length&&<p className="muted library-empty">Uploaded documents will appear here.</p>}</nav>
      <a className="api-link" href="/docs" target="_blank" rel="noreferrer">API reference ↗</a>
    </aside>
    <main>
      <header className="workspace-heading"><div><p className="muted">Inspection workspace</p><h1>{uploadStage?uploadFileName:job?.file_name??'Make every page inspectable.'}</h1></div>
        <div className="document-actions">{uploadStage?<span className="status-label running">{uploadStage==='uploading'?'Uploading':uploadStage==='validating'?'Checking upload':'Connecting'}</span>:job&&<><span className={`status-label ${job.status}`}>{job.status==='done'?'Ready':job.status}</span><button className="delete-selected" type="button" onClick={()=>askDelete(job)} disabled={deleting||uploading}>Delete document</button></>}</div></header>
      {error&&<div role="alert" className="banner error">{error}<button aria-label="Dismiss error" onClick={()=>setError('')}>×</button></div>}
      {notice&&<div role="status" className="banner">{notice}</div>}
      {uploadStage?<UploadProgress stage={uploadStage} percent={uploadPercent} fileName={uploadFileName}/>:job&&job.status!=='done'&&<ProcessingProgress job={job} live={liveUpdates}/>}
      {stats&&!uploadStage&&<section className="summary" aria-label="Document summary">
        {[[stats.pages.total,'Pages'],[stats.images.total,'Images'],[stats.tables.total,'Tables'],[stats.headings,'Headings'],[stats.paragraphs,'Paragraphs'],[stats.warnings.total,'Warnings']].map(([value,label])=><div key={label}><strong>{value}</strong><span>{label}</span></div>)}
        <p><span className="method-key read"/>{stats.pages.read} read <span className="method-key ocr"/>{stats.pages.ocr} OCR <span className="method-key mixed"/>{stats.pages.mixed} mixed<small>{stats.duration_seconds.toFixed(2)} seconds</small></p>
      </section>}
      {result&&!uploadStage&&<>
        <div className="inspection-toolbar"><div className="page-nav"><button aria-label="Previous page" disabled={pageIndex===0} onClick={()=>changePage(pageIndex-1)}>‹</button>
          <label>Page <select aria-label="Page" value={pageIndex} onChange={e=>changePage(Number(e.target.value))}>{result.pages.map((p,index)=><option value={index} key={p.page_number}>{p.page_number}</option>)}</select> of {result.pages.length}</label>
          <button aria-label="Next page" disabled={pageIndex>=result.pages.length-1} onClick={()=>changePage(pageIndex+1)}>›</button></div>
          <div className="toggles"><label><input type="checkbox" checked={arrows} onChange={e=>setArrows(e.target.checked)}/> Reading order</label><label><input type="checkbox" checked={ocrOnly} onChange={e=>setOcrOnly(e.target.checked)}/> OCR only</label><label><input type="checkbox" checked={heat} onChange={e=>setHeat(e.target.checked)}/> Confidence heat</label></div>
        </div>
        {page?<div className="inspection-panes">
          <section className="pane source-pane" aria-label="Original pages"><div className="pane-heading"><h2>Original pages</h2><span>Page {page.page_number} of {result.pages.length}</span></div>
            <div className="page-scroll" ref={sourceScroll} onScroll={trackSourcePage} aria-label="Scrollable original pages" tabIndex={0}>
              {result.pages.map((sourcePage,index)=><article className="source-page" data-source-page={index} key={`${selectedId}-${sourcePage.page_number}`} aria-label={`Source page ${sourcePage.page_number}`}>
                <div className="source-page-label"><strong>Page {sourcePage.page_number}</strong><span>{sourcePage.width.toFixed(0)} × {sourcePage.height.toFixed(0)}</span></div>
                <SourcePage page={sourcePage} jobId={selectedId!} selected={pageIndex===index?blockId:null} onSelect={id=>selectBlock(index,id)} hover={pageIndex===index?hover:null} onHover={id=>{if(id!==null)activatePage(index);setHover(id);}} ocrOnly={ocrOnly} heat={heat} arrows={arrows}/>
              </article>)}
            </div>
            <div className="legend"><span className="legend-heading">Heading</span><span className="legend-paragraph">Text</span><span className="legend-table">Table</span><span className="legend-image">Image</span><span className="legend-ocr">Dashed: OCR</span></div>
          </section>
          <section className="pane blocks-pane" aria-label="Reading order blocks"><div className="pane-heading"><h2>Reading order</h2><span>{shown.length} blocks</span></div>
            <div className="block-scroll" ref={blockScroll}>{shown.map(block=><article key={`${page.page_number}-${block.id}`} id={`block-${page.page_number}-${block.id}`} tabIndex={0}
              className={`block ${blockId===block.id||hover===block.id?'block-selected':''}`} onMouseEnter={()=>setHover(block.id)} onMouseLeave={()=>setHover(null)}
              onFocus={()=>setHover(block.id)} onBlur={()=>setHover(null)} onClick={()=>setBlockId(block.id)}>
              <div className="block-meta"><span className={`number type-${block.type}`}>{page.blocks.indexOf(block)+1}</span><strong>{block.type}</strong><span className={`source ${block.source}`}>{block.source}</span>
                <span title="Provisional confidence">{block.confidence===null?'Unscored':`${Math.round(block.confidence*100)}%`}</span></div>
              {block.heading_path.length>0&&<small className="heading-path">{block.heading_path.join(' / ')}</small>}
              {block.type==='table'?<Grid block={block}/>:block.type==='image'?<p className="muted">{block.caption||block.ocr_text||'Image region'}{block.is_decorative?' (decorative)':''}</p>:<p>{block.text||block.markdown||'Empty block'}</p>}
            </article>)}{!shown.length&&<p className="empty-pane">{ocrOnly?'No OCR blocks on this page.':'No blocks on this page.'}</p>}</div>
          </section>
          <section className="pane output-pane" aria-label="Document output"><div className="tabs" role="tablist" aria-label="Output format">{(['rendered','markdown','json'] as const).map(value=><button key={value} role="tab" aria-selected={tab===value} aria-controls="output-content" id={`tab-${value}`} onClick={()=>setTab(value)}>{value==='rendered'?'Preview':value==='markdown'?'Markdown':'JSON'}</button>)}</div>
            <div id="output-content" className="output-scroll" role="tabpanel" aria-labelledby={`tab-${tab}`} tabIndex={0}>{tab==='rendered'?<Markdown text={result.markdown}/>:<pre>{tab==='markdown'?result.markdown:JSON.stringify(result,null,2)}</pre>}</div>
            <div className="output-note">Clean document output · Images are tracked separately.</div>
          </section>
        </div>:<p className="empty-pane">This result contains no pages. Check the warnings below.</p>}
        {page?.quality&&<details className="quality"><summary>Page quality signals{page.quality.needs_ocr?' · OCR requested':' · Direct read'}</summary><p>{page.quality.character_count} characters; {(page.quality.garbage_share*100).toFixed(2)}% garbage; {(page.quality.image_coverage*100).toFixed(1)}% image coverage; {page.quality.words_per_area.toFixed(6)} words per area.</p><p>{page.quality.reasons.join(', ')||'No OCR signals fired.'}</p></details>}
        <details className="warnings" open={result.warnings.length>0}><summary>Warnings <span>{result.warnings.length}</span></summary>{result.warnings.length?result.warnings.map((warning,index)=><button key={index} disabled={warning.page_number===null} onClick={()=>{const at=result.pages.findIndex(p=>p.page_number===warning.page_number);if(at>=0)changePage(at);}}><span>{warning.page_number===null?'Document':`Page ${warning.page_number}`}</span><strong>{warning.code.replaceAll('_',' ')}</strong><span>{warning.message}</span></button>):<p>No warnings reported.</p>}</details>
      </>}
      {!selectedId&&!uploadStage&&<section className="welcome"><div className="sample-page" aria-hidden="true"><span/><span/><span/><span/></div><h2>From document to readable content.</h2><p>Upload a document, then inspect its original pages alongside extracted blocks and clean markdown.</p><button className="primary" onClick={()=>input.current?.click()}>Upload your first document</button><p className="muted">Read first. OCR only where needed.</p></section>}
    </main>
    {deleteTarget&&<DeleteDialog job={deleteTarget} busy={deleting} error={deleteError} onCancel={()=>{if(!deleting)setDeleteTarget(null);}} onConfirm={()=>void confirmDelete()}/>}
  </div>;
}
