import { useEffect, useRef } from 'react';
import type { Job } from './types';

export default function DeleteDialog({job,busy,error,onCancel,onConfirm}:{
  job:Job;busy:boolean;error:string;onCancel:()=>void;onConfirm:()=>void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    const element=dialog.current;
    element?.showModal();
    cancel.current?.focus();
    return()=>element?.close();
  },[]);
  return <dialog className="delete-dialog" ref={dialog} aria-labelledby="delete-title" aria-describedby="delete-description"
    onCancel={event=>{event.preventDefault();if(!busy)onCancel();}}>
    <h2 id="delete-title">Delete this document?</h2>
    <p className="delete-file">{job.file_name}</p>
    <p id="delete-description">The original upload, extracted results, and saved images will be permanently removed. This cannot be undone.</p>
    {(job.status==='running'||job.status==='queued')&&<p className="delete-processing">Its processing job will also be stopped.</p>}
    {error&&<p className="delete-error" role="alert">{error}</p>}
    <div className="dialog-actions"><button ref={cancel} type="button" onClick={onCancel} disabled={busy}>Keep document</button>
      <button className="danger" type="button" onClick={onConfirm} disabled={busy}>{busy?'Deleting…':'Delete document'}</button></div>
  </dialog>;
}
