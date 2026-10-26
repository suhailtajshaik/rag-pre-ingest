export async function request<T>(url:string, options?:RequestInit):Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Request failed (${response.status}). Try again.`;
    try { const body = await response.json(); message = body.error?.message ?? message; } catch { /* retain clear fallback */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
export const jobUrl = (id:string) => `/v1/jobs/${encodeURIComponent(id)}`;
import type { Upload } from './types';

export async function deleteDocument(id:string):Promise<'deleted'|'missing'> {
  const response = await fetch(jobUrl(id), {method:'DELETE'});
  if(response.status === 404) return 'missing';
  if(!response.ok) {
    let message = 'Could not delete the document. Try again.';
    try { const body = await response.json(); message = body.error?.message ?? message; } catch { /* retain fallback */ }
    throw new Error(message);
  }
  return 'deleted';
}


export function uploadDocument(
  file: File,
  onProgress: (percent: number | null) => void,
  onTransferred: () => void,
): Promise<Upload> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/v1/documents');
    xhr.upload.onprogress = event => {
      onProgress(event.lengthComputable && event.total > 0
        ? Math.min(100, Math.round(event.loaded / event.total * 100)) : null);
    };
    xhr.upload.onload = onTransferred;
    xhr.onload = () => {
      try {
        const body = JSON.parse(xhr.responseText);
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(new Error(body.error?.message ?? `Upload failed (${xhr.status}). Try again.`));
        } else {
          resolve(body as Upload);
        }
      } catch {
        reject(new Error('The upload returned an unreadable response. Try again.'));
      }
    };
    xhr.onerror = () => reject(new Error('Could not upload the document. Check the connection and try again.'));
    xhr.onabort = () => reject(new Error('The upload was interrupted. Choose the file again to retry.'));
    xhr.ontimeout = () => reject(new Error('The upload timed out. Try again.'));
    const form = new FormData();
    form.append('file', file);
    xhr.send(form);
  });
}
