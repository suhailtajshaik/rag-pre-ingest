import type { Job } from './types';

export type UploadStage = 'uploading' | 'validating' | 'connecting';

export function ProcessingProgress({job,live}:{job:Job;live:boolean}) {
  const active = job.status === 'queued' || job.status === 'running';
  const stage = job.current_stage.replaceAll('_', ' ');
  return <section className="processing progress-panel" aria-live="polite" aria-busy={active}>
    <div className="progress-heading">
      {active && <span className="progress-spinner" aria-hidden="true"/>}
      <strong>{job.status === 'failed' ? 'Processing stopped' : job.status === 'queued' ? 'Queued for processing' : `Processing: ${stage}`}</strong>
      {active && <span className={`live-indicator ${live?'connected':''}`}>{live?'Live updates':'Checking for updates'}</span>}
    </div>
    {job.status === 'failed' ? <p>{job.error ?? 'The document could not be processed.'}</p> : <>
      <div className="progress-meter"><progress aria-label="Document processing progress" max={1} value={job.progress}/>
        <span>{Math.round(job.progress * 100)}%</span></div>
      <p>{job.status === 'queued' ? 'Your upload is accepted. Processing will begin shortly.' : 'Reading and checking your document. This stage updates as work completes.'}</p>
    </>}
  </section>;
}

export function UploadProgress({stage,percent,fileName}:{stage:UploadStage;percent:number|null;fileName:string}) {
  const transferring = stage === 'uploading';
  return <section className="processing progress-panel upload-progress" aria-live="polite" aria-busy="true">
    <div className="progress-heading"><span className="progress-spinner" aria-hidden="true"/>
      <strong>{transferring ? 'Uploading document' : stage === 'validating' ? 'Checking your upload' : 'Upload accepted · Connecting to job'}</strong>
      <span className="progress-file" title={fileName}>{fileName}</span>
    </div>
    <div className="progress-meter"><progress aria-label={transferring ? 'File upload progress' : 'Waiting for processing'} max={100} value={transferring && percent !== null ? percent : undefined}/>
      <span>{transferring && percent !== null ? `${percent}%` : transferring ? 'Sending…' : 'Please wait…'}</span>
    </div>
    <p>{transferring ? 'Sending the file to the service. Processing starts after validation.' : stage === 'validating' ? 'The file has transferred. Checking its type, size, and integrity.' : 'Waiting for the first processing update.'}</p>
  </section>;
}
