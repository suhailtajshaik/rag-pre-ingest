export interface Warning { page_number: number | null; code: string; message: string }
export interface Cell { row: number; col: number; text: string; is_header: boolean; row_span: number; col_span: number }
export interface Block {
  id: string; type: 'heading'|'paragraph'|'list'|'table'|'image'|'header'|'footer'|'other';
  level: number|null; text: string; markdown: string; bbox: [number,number,number,number];
  heading_path: string[]; confidence: number|null; source: 'read'|'ocr'|'caption';
  rows: number|null; columns: number|null; cells: Cell[]; image_ref: string|null;
  ocr_text: string|null; caption: string|null; description: string|null; is_decorative: boolean;
}
export interface Page {
  page_number: number; width: number; height: number; method: 'read'|'ocr'|'mixed'; blocks: Block[];
  quality?: { character_count: number; garbage_share: number; image_coverage: number;
    words_per_area: number; needs_ocr: boolean; reasons: string[] }|null;
}
export interface Stats {
  pages: {total:number; read:number; ocr:number; mixed:number};
  images: {total:number; decorative:number; with_ocr_text:number};
  tables: {total:number; with_merged_cells:number}; headings:number; paragraphs:number; lists:number;
  warnings: {total:number; by_code:Record<string,number>}; duration_seconds:number;
}
export interface Job {
  job_id:string; file_name:string; file_type:string; file_hash:string; created_at:string;
  status:'queued'|'running'|'done'|'failed'; current_stage:string; progress:number;
  error:string|null; error_code:string|null; warnings:Warning[]; stats:Stats|null;
}
export interface Result {
  document:{id:string; file_name:string; file_type:string; file_hash:string; page_count:number;
    processed_at:string; confidence:{average:number|null; lowest_block:number|null}};
  stats:Stats; markdown:string; pages:Page[]; warnings:Warning[];
}
export interface Upload {job_id:string; status:Job['status']; already_exists:boolean}
