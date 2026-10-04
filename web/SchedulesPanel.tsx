import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api.js';
import { useCommandKeys } from './commandKeys.js';
import { occurrencePage, scheduleMetadata, schedulePage, schedulePreview, scheduleSummary, sendScheduleOnce, ScheduleGuard,
  type ScheduleApi, type ScheduleMetadata, type ScheduleMutation, type ScheduleOccurrencePage, type SchedulePage, type SchedulePreview, type ScheduleSummary } from './scheduleState.js';
export interface SchedulesPanelProps {
  ownerId: string; canManage: boolean; seed?: { planId: string; planFingerprint: string; goal: string }; api: ScheduleApi;
  onTask: (id: string) => void; disabled?: boolean;
}
interface Pointer { requestId: string; scheduleId: string | null }
const pointerStorage = (owner: string) => `factory-schedule-pending-v1:${encodeURIComponent(owner)}`;
function readPointer(owner: string): Pointer | undefined {
  try {
    const raw: unknown = JSON.parse(window.localStorage.getItem(pointerStorage(owner)) ?? 'null');
    if (raw && typeof raw === 'object' && 'requestId' in raw && typeof raw.requestId === 'string' && /^[A-Za-z0-9_.:-]{8,100}$/.test(raw.requestId)
        && 'scheduleId' in raw && (raw.scheduleId === null || typeof raw.scheduleId === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(raw.scheduleId))) return raw as Pointer;
  } catch { /* Browser storage contains only an opaque operation pointer. */ }
}
const occurrenceNames = { reserving: '正在保留准入', accepted: '原生队列已接受准入', unknown: 'UNKNOWN · 准入确认未知', rejected: '本次准入被拒绝' };
export function SchedulesPanel({ ownerId, canManage, seed, api, onTask, disabled = false }: SchedulesPanelProps) {
  const guard = useRef(new ScheduleGuard()); const epoch = guard.current.enter(ownerId); const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const active = () => mounted.current && guard.current.current(epoch);
  const transport = useRef(api); transport.current = api;
  const [data, setData] = useState<{ epoch: number; metadata: ScheduleMetadata; page: SchedulePage }>();
  const [chosen, setChosen] = useState<{ epoch: number; row: ScheduleSummary }>();
  const [history, setHistory] = useState<{ epoch: number; page: ScheduleOccurrencePage }>();
  const [preview, setPreview] = useState<{ epoch: number; value: SchedulePreview }>();
  const [pending, setPending] = useState<{ epoch: number; pointer: Pointer }>(); const intent = useRef<{ epoch: number; value: ScheduleMutation } | undefined>(undefined);
  const [name, setName] = useState(''); const [cron, setCron] = useState('0 8 * * *'); const [timezone, setTimezone] = useState('Etc/UTC');
  const [after, setAfter] = useState<string>(); const [refresh, setRefresh] = useState(0); const [busy, setBusy] = useState(true); const [error, setError] = useState('');
  const keys = useCommandKeys(ownerId); const selected = chosen?.epoch === epoch ? chosen.row : undefined;
  const state = data?.epoch === epoch ? data : undefined; const uncertain = pending?.epoch === epoch;
  const manages = canManage && state?.metadata.canManage === true;
  const writable = manages && !disabled && !busy && !uncertain;
  const checkedPreview = preview?.epoch === epoch && preview.value.cron === cron.trim().split(/\s+/).join(' ') && preview.value.timezone === timezone.trim() ? preview.value : undefined;
  function remember(pointer?: Pointer) {
    if (!active()) return; setPending(pointer ? { epoch, pointer } : undefined);
    try { if (pointer) window.localStorage.setItem(pointerStorage(ownerId), JSON.stringify(pointer)); else window.localStorage.removeItem(pointerStorage(ownerId)); } catch { /* Keep the current-page lock even without durable storage. */ }
  }
  useEffect(() => {
    setData(undefined); setChosen(undefined); setHistory(undefined); setPreview(undefined); setName(''); setCron('0 8 * * *'); setTimezone('Etc/UTC'); setAfter(undefined); setError(''); intent.current = undefined;
    const pointer = readPointer(ownerId); setPending(pointer ? { epoch, pointer } : undefined);
  }, [ownerId, epoch]);
  useEffect(() => {
    const controller = new AbortController(); setBusy(true);
    void Promise.all([transport.current.metadata(controller.signal), transport.current.list(after, controller.signal)]).then(async ([meta, rows]) => {
      const metadata = scheduleMetadata(meta, ownerId), page = schedulePage(rows, ownerId);
      if (controller.signal.aborted || !guard.current.current(epoch)) return;
      setData({ epoch, metadata, page });
      const pointer = readPointer(ownerId);
      if (pointer) {
        const found = pointer.scheduleId ? scheduleSummary(await transport.current.inspect(pointer.scheduleId, controller.signal), ownerId, pointer.scheduleId) : scheduleSummary(await transport.current.recover(pointer.requestId, controller.signal), ownerId);
        if (controller.signal.aborted || !guard.current.current(epoch)) return;
        if (found && (pointer.scheduleId ? found.lastCommandId === pointer.requestId : found.requestId === pointer.requestId)) {
          setPending(undefined); intent.current = undefined; setError(''); setChosen({ epoch, row: found }); setCron(found.cron); setTimezone(found.timezone); setName(found.name); setPreview(undefined);
          try { window.localStorage.removeItem(pointerStorage(ownerId)); } catch { /* Original commit was independently read. */ }
        }
      }
    }).catch(() => { if (!controller.signal.aborted && guard.current.current(epoch)) { setData(undefined); setError('计划记录或当前管理权限无法核对。仅可重试读取，暂不提交变更。'); } }).finally(() => { if (!controller.signal.aborted && guard.current.current(epoch)) setBusy(false); });
    return () => controller.abort();
  }, [ownerId, epoch, after, refresh]);
  async function inspect(id: string, cursor?: string) {
    if (disabled || busy || !guard.current.claim(epoch)) return; setBusy(true); setError('');
    try {
      const [row, events] = await Promise.all([transport.current.inspect(id), transport.current.occurrences(id, cursor)]);
      const value = scheduleSummary(row, ownerId, id); const page = occurrencePage(events, ownerId, id);
      if (!active()) return; setChosen({ epoch, row: value }); setHistory({ epoch, page }); setCron(value.cron); setTimezone(value.timezone); setName(value.name); setPreview(undefined);
      if (value.lastCommandId === pending?.pointer.requestId) { remember(); intent.current = undefined; }
    } catch { if (active()) { setChosen(undefined); setHistory(undefined); setError('原计划或执行历史无法核对，未改变任何执行。'); } }
    finally { guard.current.release(epoch); if (active()) setBusy(false); }
  }
  async function previewTime() {
    if (!writable || !cron.trim() || !timezone.trim() || !guard.current.claim(epoch)) return; setBusy(true); setError(''); setPreview(undefined);
    const value = { cron: cron.trim().split(/\s+/).join(' '), timezone: timezone.trim() };
    try { const result = schedulePreview(await transport.current.preview(value), value.cron, value.timezone); if (active()) setPreview({ epoch, value: result }); }
    catch { if (active()) setError('Cron 表达式或 IANA 时区无法预览，请检查后重试。未保存任何变更。'); }
    finally { guard.current.release(epoch); if (active()) setBusy(false); }
  }
  async function mutate(kind: 'create' | 'edit' | 'enabled', enabled?: boolean) {
    if (!writable || kind !== 'create' && !selected || kind !== 'enabled' && !checkedPreview || kind === 'create' && (!seed || !name.trim()) || !guard.current.claim(epoch)) return;
    setBusy(true); setError('');
    try {
      const payload = kind === 'create' ? { kind, planId: seed!.planId, planFingerprint: seed!.planFingerprint, name: name.trim(), cron: cron.trim().split(/\s+/).join(' '), timezone: timezone.trim() }
        : kind === 'edit' ? { kind, scheduleId: selected!.id, expectedDefinitionFingerprint: selected!.definitionFingerprint, cron: cron.trim().split(/\s+/).join(' '), timezone: timezone.trim() }
        : { kind, scheduleId: selected!.id, expectedDefinitionFingerprint: selected!.definitionFingerprint, enabled: enabled === true };
      const key = await keys('schedule-management', payload); if (!active()) return;
      const value = { ...payload, requestId: key.requestId } as ScheduleMutation;
      intent.current = { epoch, value }; remember({ requestId: value.requestId, scheduleId: value.kind === 'create' ? null : value.scheduleId });
      const row = await sendScheduleOnce(transport.current, ownerId, value); if (!active()) return;
      remember(); intent.current = undefined; key.acknowledged(); setChosen({ epoch, row }); setHistory(undefined); setPreview(undefined); setAfter(undefined); setRefresh(n => n + 1);
    } catch (cause) { if (active()) {
      if (cause instanceof ApiError && ['SCHEDULE_NAME_EXISTS', 'SCHEDULE_EDITOR_STALE', 'SCHEDULE_CLOCK_INVALID'].includes(cause.code ?? cause.message)) { remember(); intent.current = undefined; setPreview(undefined); if ((cause.code ?? cause.message) === 'SCHEDULE_EDITOR_STALE') { setChosen(undefined); setHistory(undefined); } setError('服务端已拒绝此次变更：名称重复、定义已变化或时间无效。请重新读取并修改后再提交。'); }
      else setError('变更结果尚未确认。保留原请求并锁定编辑；刷新只读取原记录，不会重放变更。');
      setRefresh(n => n + 1);
    } }
    finally { guard.current.release(epoch); if (active()) setBusy(false); }
  }
  async function retryOriginal() {
    if (disabled || busy || !manages || !uncertain || intent.current?.epoch !== epoch || !guard.current.claim(epoch)) return;
    setBusy(true); const original = intent.current.value;
    try { const row = await sendScheduleOnce(transport.current, ownerId, original); if (!active()) return; remember(); intent.current = undefined; setChosen({ epoch, row }); setPreview(undefined); setRefresh(n => n + 1); }
    catch { if (active()) setError('原变更仍未确认；继续保留原标识，不能改成新的请求。'); }
    finally { guard.current.release(epoch); if (active()) setBusy(false); }
  }
  return <section aria-label="计划任务" className="schedules-panel" style={{ minWidth: 0, overflowWrap: 'anywhere' }}><h1>计划任务</h1>
    <p>复用已批准的不可变方案；每次触发仍检查当前权限和预算。计划准入成功不代表研究任务完成。</p>
    <p className="state-note">暂停只停止后续准入，不会取消已创建的任务。UNKNOWN 保留原执行记录，不能当作失败重新运行；请查看原任务核对。</p>
    <button type="button" className="secondary" disabled={disabled || busy} onClick={() => { setError(''); setAfter(undefined); setRefresh(n => n + 1); }}>刷新计划任务</button>
    {busy && <p role="status">正在核对计划记录…</p>}{error && <p role="alert" className="error-message">{error}</p>}
    {uncertain && <div className="policy-note"><p>原变更请求未确认：{pending.pointer.requestId}。刷新仅 GET 核对；重新打开页面后不保存或重建原输入。</p>{intent.current?.epoch === epoch && <button type="button" className="secondary" disabled={disabled || busy || !manages} onClick={() => void retryOriginal()}>显式重试原变更请求</button>}</div>}
    {state && <p className="quiet">单个调度轮询器；错过的时刻合并处理，不逐次补跑。允许任务重叠，但仍受当前预算准入限制（每用户 {state.metadata.policy.maxUserTasks}、总计 {state.metadata.policy.maxTotalTasks}）。IANA 时区和夏令时以服务端 Cron 计算为准，预览不是预约保证。</p>}
    {state && !manages && <p className="policy-note">当前身份只能读取自己的计划与历史；管理需要当前管理员权限。</p>}
    {state?.page.items.map(row => <article className="material-row" key={row.id}><div style={{ minWidth: 0 }}><h3>{row.name}</h3><p>{row.enabled ? '已启用' : '已暂停'} · {row.cron} · {row.timezone}</p><p>下次计算时刻：{row.nextRunAt ?? '尚未提供'}</p><button type="button" className="secondary" disabled={disabled || busy} onClick={() => void inspect(row.id)}>查看计划任务 {row.name}</button></div></article>)}
    {state?.page.items.length === 0 && <p>当前页没有计划任务。</p>}{state?.page.nextCursor && <button type="button" disabled={disabled || busy} onClick={() => setAfter(state.page.nextCursor!)}>读取下一页计划</button>}
    <p className="quiet">分页记录不是完整实时快照。</p>
    {manages && (selected || seed) && <fieldset disabled={!writable}><legend>{selected ? '调整原计划执行时间' : '从已批准方案创建计划'}</legend>
      {selected ? <p>原方案 {selected.planId}。调整时间不会替换原方案。</p> : <p>{seed?.goal}。新计划保存为暂停状态；启用需另行明确操作。</p>}
      <label>计划任务名称<input aria-label="计划任务名称" value={name} maxLength={120} disabled={!!selected} onChange={event => setName(event.target.value)}/></label>
      <label>Cron 表达式<input aria-label="Cron表达式" value={cron} maxLength={100} onChange={event => { setCron(event.target.value); setPreview(undefined); }}/></label>
      <label>IANA 时区<input aria-label="IANA时区" value={timezone} maxLength={100} onChange={event => { setTimezone(event.target.value); setPreview(undefined); }}/></label>
      <button type="button" className="secondary" onClick={() => void previewTime()}>预览下次执行时间</button>
      {checkedPreview && <div aria-label="执行时间预览"><p>仅预览；夏令时跳过或重复时刻由时区和 Cron 规则决定。</p><ol>{checkedPreview.nextRuns.map((run, index) => <li key={index}>{run.local} · UTC {run.utc} · 偏移 {run.utcOffsetSeconds} 秒</li>)}</ol></div>}
      <button type="button" className="primary" disabled={!writable || !checkedPreview || !!selected && !selected.allowedActions.includes('edit') || !selected && !name.trim()} onClick={() => void mutate(selected ? 'edit' : 'create')}>{selected ? '保存执行时间' : '保存计划任务'}</button>
    </fieldset>}
    {selected && <section aria-label="计划执行历史"><h2>{selected.name} · 执行历史</h2><p className="quiet">这里只显示已持久化的执行记录。触发前的权限、方案或时钟锁拒绝可能尚无可见记录；空列表不代表从未触发。</p>
      {manages && <button type="button" className="secondary" disabled={!writable || !selected.allowedActions.includes(selected.enabled ? 'disable' : 'enable')} onClick={() => void mutate('enabled', !selected.enabled)}>{selected.enabled ? '暂停计划任务' : '恢复计划任务'}</button>}
      <button type="button" className="text-button" disabled={disabled || busy} onClick={() => void inspect(selected.id)}>刷新执行历史</button>
      {history?.epoch === epoch && history.page.scheduleId === selected.id && <>{history.page.items.map(item => <article key={item.id}><h3>{occurrenceNames[item.status]}</h3><p>{item.createdAt} · 原任务状态 {item.taskStatus ?? '尚未确认'}</p>{item.status === 'unknown' && <p className="policy-note">准入结果未知，不能创建替代执行或推断容量已释放。</p>}{item.taskId && <button type="button" className="text-button" disabled={disabled || busy} onClick={() => onTask(item.taskId!)}>查看原任务</button>}</article>)}{history.page.items.length === 0 && <p>当前页没有触发记录。</p>}{history.page.nextCursor && <button type="button" disabled={disabled || busy} onClick={() => void inspect(selected.id, history.page.nextCursor!)}>读取下一页执行历史</button>}</>}
      <details className="technical-detail"><summary>原计划与不可变方案凭据</summary><span>计划 {selected.id}</span><span>方案 {selected.planId}</span><span>方案指纹 {selected.planFingerprint}</span><span>定义指纹 {selected.definitionFingerprint}</span></details>
      {seed && <button type="button" className="text-button" disabled={!writable} onClick={() => { setChosen(undefined); setHistory(undefined); setPreview(undefined); setName(''); }}>使用已选方案新建计划</button>}
    </section>}
    {manages && !selected && !seed && <p>请先在装配面板取得已批准的不可变方案，再选择创建计划任务。</p>}
  </section>;
}
