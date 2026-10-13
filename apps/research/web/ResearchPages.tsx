import './styles.css';
import type { WorkspaceContext } from '../../../web/App.js';
import { OpenResearchWorkspace } from './OpenResearchWorkspace.js';
import { AutoResearch } from './AutoResearch.js';
import { ComparisonPanel } from './ComparisonPanel.js';
import { researchApi } from './api.js';

export function ResearchCatalog({ context }: { context: WorkspaceContext }) {
  return <article className="or-catalog-card"><span className="quiet">研究应用</span><h2>OpenResearch</h2><p>关联原生项目、整理研究会话，沿原任务查看结果与证据。</p><p className="quiet">可用能力以工作区服务端检查为准。</p><button className="primary" onClick={() => context.navigate({ tab: 'openresearch' })}>进入 OpenResearch</button></article>;
}
export function ResearchDeveloperTools({ context }: { context: WorkspaceContext }) {
  return <details className="technical-detail"><summary>受控实验开发入口</summary><p>预设工作负载与原生 OpenResearch 项目彼此独立。</p><button className="secondary" onClick={() => context.navigate({ tab: 'autoresearch' })}>打开受控 Auto-Research 实验</button></details>;
}
export function ResearchPages({ context }: { context: WorkspaceContext }) {
  const { user, route, navigate, onTask, busy, onCompose } = context;
  if (route.tab === 'openresearch') return <OpenResearchWorkspace key={user.id} ownerId={user.id}
    onModels={() => navigate({ tab: 'models', modelReturn: 'openresearch' })}
    selectedProject={route.project ?? ''} selectedMode={route.mode === 'personal' ? 'personal' : route.mode === 'managed' || route.project ? 'managed' : 'personal'}
    onMode={mode => navigate({ tab: 'openresearch', mode })} onProject={project => navigate({ project, mode: 'managed' })}
    onTask={onTask} onResources={() => navigate({ tab: 'resources' })} onCatalog={() => navigate({ tab: 'catalog' })}/>;
  if (route.tab === 'autoresearch') return <AutoResearch key={`${user.id}:${route.run || 'entry'}`} ownerId={user.id} api={researchApi.autoresearch}
    runId={route.run || undefined} onRun={(run, passive) => { if (!passive) navigate({ tab: 'autoresearch', run }); }} onOpenTasks={() => navigate({ tab: 'catalog' })}/>;
  if (route.tab === 'comparison') return <ComparisonPanel ownerId={user.id} api={researchApi.comparisons} disabled={!!busy} onPrepare={seed => onCompose?.({ key: `${seed.applicationRef.sha256}:${seed.mode}`, applicationRef: seed.applicationRef, mode: seed.mode, goal: seed.goal }, '比较输入已固定，请生成提案并完成独立方案审查。')}/>;
  return null;
}
