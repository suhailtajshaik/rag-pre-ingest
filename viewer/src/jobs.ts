import type { Job } from './types';

export function newestUploadsFirst(jobs:Job[]):Job[] {
  return [...jobs].sort((left,right)=>right.created_at.localeCompare(left.created_at)
    ||right.job_id.localeCompare(left.job_id));
}

export function updateJob(jobs:Job[],updated:Job):Job[] {
  return newestUploadsFirst([...jobs.filter(job=>job.job_id!==updated.job_id),updated]);
}
