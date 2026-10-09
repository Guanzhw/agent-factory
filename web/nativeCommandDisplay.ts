import type { FactoryJob } from './models.js';
/** Display labels only; never change the immutable job, plan, or request. */
export function jobDisplayTitle(job: FactoryJob): string {
  if (job.input.mode !== 'personal-command') return job.input.topic;
  const names: Record<string, string> = {
    'Personal remote agent prompt': '原生会话研究消息',
    'Personal remote agent create': '创建原生研究会话',
    'Personal remote agent interrupt': '原生会话中断请求',
  };
  return names[job.input.topic] ? `${names[job.input.topic]} · ${job.id.slice(0, 8)}` : job.input.topic;
}
