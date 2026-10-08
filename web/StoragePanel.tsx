import { useEffect, useState } from 'react';
import { api } from './api.js';
import { useCommandKeys } from './commandKeys.js';
import { retentionState, storageHeadroom, type RetentionReceipt, type StorageSummary } from './storageState.js';

const bytes = (value?: number) => value === undefined ? '尚未完整观测' : value < 1024 * 1024 ? `${value.toLocaleString('zh-CN')} B` : `${(value / 1024 / 1024).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} MiB`;
export function StoragePanel({ ownerId, busy, act, onNotice }: { ownerId: string; busy: string; act: (name: string, work: () => Promise<void>) => Promise<void>; onNotice: (message: string) => void }) {
  const [value, setValue] = useState<StorageSummary>();
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [confirmed, setConfirmed] = useState('');
  const keyFor = useCommandKeys(ownerId);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try { const next = await api.storage(ownerId, controller.signal); if (!controller.signal.aborted) { setValue(next); setError(''); } }
      catch (error) { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : '磁盘观测不可用'); }
      if (!controller.signal.aborted) timer = setTimeout(() => void read(), 10000);
    }
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [ownerId, refresh]);
  function action(plan: RetentionReceipt, selected: 'quarantine' | 'restore' | 'purge') {
    void act('storage-' + selected, async () => {
      try {
        const result = await api.retentionAction(ownerId, plan.id, selected);
        onNotice(retentionState(result.state)); setConfirmed('');
      } finally { setRefresh(n => n + 1); }
    });
  }
  return <section className="storage-panel">
    <div className="page-heading"><div><h1>磁盘与回收</h1><p>先核对用量和保护状态，再记录回收计划。隔离后的目录可恢复，隔离本身不释放磁盘。</p></div><button className="secondary" onClick={() => setRefresh(n => n + 1)}>刷新观测</button></div>
    {error && <p role="alert">{error}</p>}
    {!value ? <p role="status">正在读取磁盘与任务记录…</p> : <>
      <section className="storage-card"><h2>共享文件系统准入</h2>
        {value.filesystems.map(mount => <dl className="storage-metrics" key={mount.filesystem}><div><dt>实际可用</dt><dd>{bytes(mount.freeBytes)}</dd></div><div><dt>实际已用</dt><dd>{bytes(mount.usedBytes)}</dd></div><div><dt>总容量</dt><dd>{bytes(mount.totalBytes)}</dd></div></dl>)}
        <p>未释放预留 {bytes(value.reservedBytes)} · 安全低水位 {bytes(value.lowWaterBytes)} · 每个新任务预留 {bytes(value.taskReserveBytes)}</p>
        <p role="status">{storageHeadroom(value) < value.taskReserveBytes ? '当前空间不足以接受新任务。已有任务和不确定预留继续受到保护。' : `扣除预留和低水位后，准入余量 ${bytes(storageHeadroom(value))}。`}</p>
        <p className="quiet">共享空间包含宿主机与 Docker 数据。这里不会清理其他用户目录或执行全局 prune。磁盘预留用于准入，不等同于操作系统硬配额。</p>
      </section>
      <section className="storage-card"><h2>我的数据与预留</h2><p>数据库证据产物：{value.databaseArtifacts.count} 项，{bytes(value.databaseArtifacts.bytes)}。证据不进入自动回收。</p>
        <p className="quiet">本次最多展示 {value.observationLimits.objects} 个目录、{value.observationLimits.plans} 个计划和 {value.observationLimits.orxDirectories} 个 ORX 证据目录；不是完整历史导出。</p>
        <p>{value.ownerHolds.filter(hold => hold.state === 'HELD').length} 项磁盘预留仍占用；UNKNOWN 和未回收的资源租约不会被当作空闲。</p>
        {value.protectedDirectories.map(directory => <p className="quiet" key={directory.taskId}>ORX 证据目录 · {directory.taskId} · {bytes(directory.logicalBytes)} · 保留保护</p>)}
        {value.protectedContainers.map(container => <p className="quiet" key={container.taskId}>原任务容器 · {container.taskId} · {container.complete ? `可写层 ${bytes(container.writableLayerBytes)}，逻辑根文件系统 ${bytes(container.rootFilesystemLogicalBytes)}` : '归属或用量未确认'} · 保留停止证据，不进入目录回收。逻辑大小不能相加作为 vfs 实占。</p>)}
      </section>
      <section className="storage-card"><h2>可观测的任务目录</h2>
        {!value.retentionSupported && <p>本机尚未通过安全目录操作验收，回收功能不可用。</p>}
        {!value.objects.length && <p className="quiet">尚无平台登记的任务目录。历史目录不会被自动接管。</p>}
        <ul className="storage-list">{value.objects.map(object => <li key={object.id}><div><strong>{object.evidence ? '受保护证据' : '可重建任务临时目录'}</strong><p>{bytes(object.logicalBytes)} · {object.state}</p><small>任务 {object.task_id}</small></div>
          <button className="secondary" disabled={!!busy || object.evidence || !object.availableOnThisHost || object.state !== 'AVAILABLE' || !value.retentionSupported} onClick={() => void act('storage-plan', async () => {
            const key = await keyFor('storage-retention', { objectId: object.id });
            try { const plan = await api.retentionPlan(ownerId, object.id, key.requestId); key.acknowledged(); onNotice(`回收计划已记录：${bytes(plan.logicalBytes)}。尚未移动或删除文件。`); }
            finally { setRefresh(n => n + 1); }
          })}>生成回收 dry-run</button></li>)}</ul>
      </section>
      <section className="storage-card"><h2>我的回收计划</h2><p className="quiet">隔离保护期 {value.quarantineGraceSeconds} 秒。{value.purgeEnabled ? '永久回收仅适用于已确认停止的可重建目录；回收后不能从隔离区恢复。' : '永久回收策略尚未启用，可先隔离并恢复。'}</p>
        <ul className="storage-list">{value.plans.map(plan => <li key={plan.id} data-retention-id={plan.id}><div><strong>{retentionState(plan.state)}</strong><p>{bytes(plan.logicalBytes)} · 已移除登记内容 {bytes(plan.reclaimedLogicalBytes)}</p><details><summary>计划引用</summary><span>{plan.id}</span><br/><span>{plan.fingerprint}</span></details></div><div className="button-row">
          <button className="secondary" disabled={!!busy} onClick={() => void act('storage-inspect', async () => { const receipt = await api.retention(ownerId, plan.id); onNotice(retentionState(receipt.state)); setRefresh(n => n + 1); })}>核对原计划</button>
          {['PLANNED', 'MOVING'].includes(plan.state) && <button className="secondary" disabled={!!busy} onClick={() => action(plan, 'quarantine')}>确认隔离</button>}
          {['QUARANTINED', 'RESTORING'].includes(plan.state) && <button className="secondary" disabled={!!busy} onClick={() => action(plan, 'restore')}>恢复原目录</button>}
          {value.purgeEnabled && ['QUARANTINED', 'PURGING'].includes(plan.state) && <><label><input type="checkbox" checked={confirmed === plan.id} onChange={event => setConfirmed(event.target.checked ? plan.id : '')}/>确认仅回收可重建文件</label><button className="secondary danger" disabled={!!busy || confirmed !== plan.id} onClick={() => action(plan, 'purge')}>永久回收</button></>}
        </div></li>)}</ul>
      </section>
    </>}
  </section>;
}
