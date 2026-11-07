import { useEffect, useState, type ReactNode } from 'react';
import { IconArrowLeft, IconArrowRight, IconBook, IconChevronDown, IconDatabase, IconHexagonLetterA, IconHome, IconLogout, IconMessageCircle, IconRobotFace, IconUser } from '@tabler/icons-react';
import type { User } from '../../../models.js';
import type { WorkspaceRoute } from '../../../workspaceNavigation.js';
import { researchApi } from '../client.js';
import type { Page, ResearchProject, ResearchProjectSummary } from '../types.js';
import { Dialog } from './Dialog.js';
import { ProjectDetails, projectStates } from './ProjectDetails.js';
import { assistantApi, type ResearchAssistant } from './assistantClient.js';
import { AssistantSettings, accountingNotice } from './AssistantSettings.js';
import { AssistantDirectory, AskAssistant, OriginalQuestion } from './AssistantQuestions.js';
import { AssistantInbox } from './AssistantInbox.js';
import { AssociationDetail, DeliveryDetail, EvidenceDirectory } from './EvidenceViews.js';
import { ResearchSessions } from '../ResearchSessions.js';
import './workbench.css';
import '../chat.css';

const errorText = (error: unknown) => error instanceof Error ? error.message : '读取失败，请重试。';
type Props = { user: User; route: WorkspaceRoute; navigate: (patch: Partial<WorkspaceRoute>) => void; onLogout: () => void; sessionBusy: boolean; sessionError: string; workspaceContent?: ReactNode; onTab?: (tab: WorkspaceRoute['tab']) => void };

function AssistantPanel({ project, assistant, onSettings }: { project: ResearchProject | null; assistant: ResearchAssistant | null; onSettings: () => void }) {
  const goal = project?.goals.find(goal => goal.version === project.currentGoalVersion);
  const current = goal && !goal.sourceUnavailable ? goal : undefined;
  return <div className="rw-assistant-content"><header><h2>研究助手</h2><p>{project ? `当前项目：${project.title}` : '选择项目，查看关联助手与研究进度。'}</p></header><div className="rw-assistant-body">
    <article className="rw-assistant-note"><IconRobotFace size={28}/><div><h3>{assistant ? '我的研究助手' : '尚未创建研究助手'}</h3>{assistant && <p className="rw-id">{assistant.id}</p>}<p>{assistant?.qa.state === 'configured' ? assistant.qa.available ? '可在授权范围内回答经验询问。' : `当前不可用：${assistant.qa.unavailableCode}` : '明确创建、发布配置并确认操作额度后才可回答问题。'}</p><p>{accountingNotice}</p><button onClick={onSettings}>设置我的助手</button></div></article>
    {project?.researchAssistantId && <p className="rw-id">项目关联助手：{project.researchAssistantId}</p>}{project?.assistantId && <p className="rw-id">历史执行端点：{project.assistantId}</p>}
    {project && <article className="rw-source"><h3>当前约定</h3><p>{project.sourceUnavailable ? '来源不可用，原目标正文已隐藏。' : current?.agreement.objective ?? '先明确研究目标与边界。'}</p><small>来源：项目 {project.id} · 目标版本 {project.currentGoalVersion}</small><p>{current?.confirmedAt ? '约定已确认；这不代表实验已运行。' : '约定尚未确认。'}</p></article>}
    <p className="rw-muted">分析需要明确出处；运行完成与研究结论分别核对。</p>
  </div></div>;
}

export function ResearchWorkbench({ user, route, navigate, onLogout, sessionBusy, sessionError, workspaceContent, onTab }: Props) {
  const [page, setPage] = useState<Page<ResearchProjectSummary> | null>(null);
  const [after, setAfter] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [listError, setListError] = useState('');
  const [projectError, setProjectError] = useState('');
  const [accountOpen, setAccountOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(!!route.researchPeer || !!route.researchQuestion);
  const [myAssistant, setMyAssistant] = useState<ResearchAssistant | null>(null);
  const [assistantError, setAssistantError] = useState('');
  const [assistantLoading, setAssistantLoading] = useState(true);
  const [assistantRefresh, setAssistantRefresh] = useState(0);
  const openTab = (tab: WorkspaceRoute['tab']) => onTab ? onTab(tab) : navigate({ tab });
  const selectedId = route.project;
  const team = route.researchView === 'team';
  const settings = route.researchView === 'assistant';
  const history = workspaceContent === undefined && (route.researchView === 'history' || !!route.project);
  const sessions = !team && !settings && !history;
  const tab = route.researchTab || 'overview';
  const home = () => navigate({ tab: 'research', project: '', researchView: '', researchSession: '', researchTab: '', researchSetup: '', researchQASetup: '', researchPeer: '', researchQuestion: '', researchAssociation: '', researchDelivery: '' });
  const openSessions = (id = route.researchSession ?? '') => navigate({ tab: 'research', project: '', researchView: '', researchSession: id, researchTab: '', researchSetup: '', researchQASetup: '', researchPeer: '', researchQuestion: '', researchAssociation: '', researchDelivery: '' });
  const resources = () => navigate({ tab: 'resources', modelReturn: 'research', project: !team && !settings && !sessions ? selectedId ?? '' : route.project ?? '' });
  const openTask = (task: string) => navigate({ tab: 'tasks', task, taskReturn: 'research', taskReturnTask: task,
    project: !team && !settings && !sessions ? selectedId ?? '' : route.project ?? '' });
  useEffect(() => {
    const controller = new AbortController(); setAssistantError(''); setAssistantLoading(true);
    void assistantApi.me(user.id, controller.signal).then(value => { if (!controller.signal.aborted) setMyAssistant(value.assistant); }).catch(reason => { if (!controller.signal.aborted) setAssistantError(errorText(reason)); }).finally(() => { if (!controller.signal.aborted) setAssistantLoading(false); });
    return () => controller.abort();
  }, [user.id, assistantRefresh]);
  useEffect(() => {
    if (!history) return;
    const controller = new AbortController(); setPage(null); setListError('');
    void researchApi.projects(user.id, after, controller.signal).then(result => { if (!controller.signal.aborted) setPage(result); }).catch(reason => { if (!controller.signal.aborted) setListError(errorText(reason)); });
    return () => controller.abort();
  }, [user.id, after, refresh, history]);
  useEffect(() => {
    setProject(null); setProjectError('');
    if (!selectedId) return;
    const controller = new AbortController();
    void researchApi.project(user.id, selectedId, controller.signal).then(result => { if (!controller.signal.aborted) setProject(result); }).catch(reason => { if (!controller.signal.aborted) setProjectError(errorText(reason)); });
    return () => controller.abort();
  }, [user.id, selectedId, refresh]);
  const openSettings = () => { setAssistantOpen(false); navigate({ tab: 'research', researchView: 'assistant', researchPeer: '', researchQuestion: '', researchAssociation: '', researchDelivery: '' }); };
  const assistant = route.researchQuestion ? <div className="rw-assistant-content"><OriginalQuestion key={`${user.id}:${route.researchQuestion}`} ownerId={user.id} questionId={route.researchQuestion} onTask={openTask} onSettings={openSettings}/></div> : route.researchPeer ? <div className="rw-assistant-content"><AskAssistant key={`${user.id}:${route.researchPeer}`} ownerId={user.id} peerId={route.researchPeer} onQuestion={id => navigate({ researchQuestion: id })}/></div> : <AssistantPanel project={project} assistant={myAssistant} onSettings={openSettings}/>;
  const navigation = <><div className="rw-brand"><IconHexagonLetterA size={33}/><div><strong>Agent Factory</strong><span>对话与研究</span></div></div>
      <nav aria-label="工作区"><button aria-current={sessions && workspaceContent === undefined ? 'page' : undefined} onClick={home}><IconMessageCircle/>对话</button><button aria-current={team && workspaceContent === undefined ? 'page' : undefined} onClick={() => navigate({ tab: 'research', project: '', researchView: 'team', researchQuestion: '', researchPeer: '', researchAssociation: '', researchDelivery: '' })}><IconBook/>团队经验</button><button aria-current={history ? 'page' : undefined} onClick={() => navigate({ tab: 'research', project: '', researchView: 'history', researchTab: '', researchDelivery: '' })}><IconHome/>历史项目</button><button onClick={resources}><IconDatabase/>设置</button><button aria-current={settings && workspaceContent === undefined ? 'page' : undefined} onClick={openSettings}><IconRobotFace/>离线代答</button></nav>
      <details className="rs-advanced-nav"><summary>更多工具</summary><nav aria-label="高级工具">
      <button onClick={() => openTab('tasks')}>执行记录</button>
      <button onClick={() => openTab('applications')}>应用模板</button>
      <button onClick={() => openTab('materials')}>共享材料</button>
      <button onClick={() => openTab('schedules')}>计划任务</button>
      <button onClick={() => openTab('storage')}>存储</button>
      <button onClick={() => openTab('reviews')}>历史方案记录</button>
      {user.role === 'manager' && <button onClick={() => openTab('accounts')}>团队账号管理</button>}
    </nav></details>
    <footer className="rw-identity"><button aria-expanded={accountOpen} onClick={() => setAccountOpen(value => !value)}><span className="rw-avatar"><IconUser size={20}/></span><span>{user.name}</span><IconChevronDown size={16}/></button>{accountOpen && <div className="rw-account-menu"><p>{user.name}</p><button disabled={sessionBusy} onClick={onLogout}><IconLogout size={18}/>{sessionBusy ? '正在退出…' : '退出登录'}</button></div>}<p>个人研究空间</p></footer>
    </>;
  if (sessions || workspaceContent !== undefined) return <div className="rw-shell rw-chat-shell">
    <ResearchSessions key={user.id} ownerId={user.id} selectedId={route.researchSession} questionId={route.researchQuestion}
      onQuestion={id => navigate({ researchQuestion: id })} onSelect={openSessions}
      onModels={() => navigate({ tab: 'models', modelReturn: 'research' })} onTask={openTask}
      navigation={navigation} workspaceContent={workspaceContent} sessionError={sessionError}/>
  </div>;
  return <div className="rw-shell rw-chat-shell">
    <ResearchSessions ownerId={user.id} selectedId={route.researchSession} onSelect={openSessions}
      onQuestion={id => navigate({ researchQuestion: id })} onModels={() => navigate({ tab: 'models', modelReturn: 'research' })}
      onTask={openTask} navigation={navigation} workspaceContent={<>{sessionError && <p className="rw-error" role="alert">{sessionError}</p>}
      <header className="rw-heading"><div>{(route.project || settings) && <button className="rw-back" onClick={home}><IconArrowLeft size={16}/>返回工作台</button>}<h1>{settings ? '助手设置' : team ? '团队经验' : route.project ? '项目详情' : '历史项目'}</h1><p>{settings ? '明确身份、模型与有界问答授权。' : team ? '向指定助手私密询问有出处的团队经验。' : '保留研究目标、实验条件与证据。'}</p></div></header>
      {settings ? <>{assistantError && <p role="alert">{assistantError}<button onClick={() => setAssistantRefresh(value => value + 1)}>重读个人助手</button></p>}{assistantLoading && <p role="status">正在读取个人助手…</p>}{((!assistantLoading && !assistantError) || myAssistant) && <AssistantSettings key={user.id} ownerId={user.id} assistant={myAssistant} setupId={route.researchQASetup} onSetup={id => navigate({ researchQASetup: id })} onSaved={setMyAssistant} onReload={() => setAssistantRefresh(value => value + 1)} onResources={resources}/>}</> : team ? <><AssistantInbox key={`${user.id}:inbox`} ownerId={user.id} onSettings={openSettings} onQuestion={id => { navigate({ researchQuestion: id, researchPeer: '' }); setAssistantOpen(true); }}/><AssistantDirectory key={user.id} ownerId={user.id} onAsk={id => { navigate({ researchPeer: id, researchQuestion: '', researchAssociation: '', researchDelivery: '' }); setAssistantOpen(true); }}/><EvidenceDirectory key={`${user.id}:associations`} ownerId={user.id} kind="associations" onSelect={id => navigate({ researchAssociation: id, researchDelivery: '' })}/><EvidenceDirectory key={`${user.id}:deliveries`} ownerId={user.id} kind="deliveries" onSelect={id => navigate({ researchDelivery: id, researchAssociation: '' })}/>{route.researchAssociation && <AssociationDetail key={`${user.id}:${route.researchAssociation}`} ownerId={user.id} id={route.researchAssociation}/>}</> : <>
        <div className="rw-actions"><button onClick={() => setRefresh(value => value + 1)}>刷新项目</button></div>
        {!route.project && <>{listError && <p className="rw-error" role="alert">{listError}</p>}{!page && !listError && <p role="status">正在读取项目…</p>}
          {page && !page.items.length && <div className="rw-empty"><h2>{after ? '本页没有项目' : '还没有研究项目'}</h2><p>这里保留原项目记录；新工作从助手开始。</p><button onClick={resources}>配置模型与资源</button></div>}
          {!!page?.items.length && <div className="rw-project-table" aria-label="研究项目"><div className="rw-project-header"><span>项目</span><span>当前状态</span><span>下一步</span></div>{page.items.map(item => <button className={`rw-project-row ${selectedId === item.id ? 'selected' : ''}`} key={item.id} onClick={() => navigate({ tab: 'research', project: item.id, researchTab: '', researchView: '', researchSetup: '', researchQASetup: '', researchPeer: '', researchQuestion: '', researchAssociation: '', researchDelivery: '' })}><strong>{item.title}</strong><span className={`rw-state ${item.state}`}>{projectStates[item.state]}</span><span className="rw-next">{item.state === 'draft' ? '明确并确认研究约定' : item.state === 'ended' ? '查看结束依据与历史' : '查看实验与证据'}</span><IconArrowRight size={18}/></button>)}</div>}
          <div className="rw-actions">{after && <button onClick={() => setAfter('')}>返回第一页</button>}{page?.nextCursor && <button onClick={() => setAfter(page.nextCursor!)}>下一页项目</button>}</div>
        </>}
        {projectError && <div className="rw-error" role="alert"><p>{projectError}</p><button onClick={home}>返回研究工作台</button></div>}
        {selectedId && !project && !projectError && <p role="status">正在读取项目详情…</p>}
        {project && <ProjectDetails onTask={openTask} key={project.id} project={project} tab={tab} onTab={value => navigate({ researchTab: value === 'overview' ? '' : value })}/>}

      </>}
      {route.researchDelivery && <DeliveryDetail key={`${user.id}:${route.researchDelivery}`} ownerId={user.id} id={route.researchDelivery}/>}
</>}/>
    <button className="rw-mobile-assistant" onClick={() => setAssistantOpen(true)}><IconMessageCircle size={22}/>研究助手</button>
    {assistantOpen && <Dialog title="研究助手" onClose={() => setAssistantOpen(false)}>{assistant}</Dialog>}
  </div>;
}
