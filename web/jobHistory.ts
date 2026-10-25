import type { JobSummary } from './models.js';

export function compareJobOrder(a: JobSummary, b: JobSummary): number {
  return a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** Keep loaded history while updating repeated rows from the newest persisted observation. */
export function mergeJobHistory(current: JobSummary[], incoming: JobSummary[]): JobSummary[] {
  const jobs = new Map(current.map(job => [job.id, job]));
  for (const job of incoming) {
    const previous = jobs.get(job.id);
    const observed = (value: JobSummary) => value.observedAt ?? value.updatedAt;
    if (!previous || observed(job) >= observed(previous)) jobs.set(job.id, job);
  }
  return [...jobs.values()].sort((a, b) => compareJobOrder(b, a));
}
