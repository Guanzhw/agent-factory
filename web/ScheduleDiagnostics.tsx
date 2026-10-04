import { useEffect, useRef, useState } from 'react';
import { diagnosticCatalog, diagnosticPage, diagnosticReasons, DiagnosticsEpoch,
  type DiagnosticCatalog, type DiagnosticPage, type ScheduleDiagnosticsApi } from './scheduleDiagnosticsState.js';

export interface ScheduleDiagnosticsProps { ownerId: string; api: ScheduleDiagnosticsApi }
export function ScheduleDiagnostics({ ownerId, api }: ScheduleDiagnosticsProps) {
  const ownerGuard = useRef(new DiagnosticsEpoch()); const ownerEpoch = ownerGuard.current.enter(ownerId);
  const transport = useRef(api); transport.current = api;
  const [selection, setSelection] = useState<{ epoch: number; id: string }>();
  const selected = selection?.epoch === ownerEpoch ? selection.id : '';
  const pageGuard = useRef(new DiagnosticsEpoch()); const pageEpoch = pageGuard.current.enter(ownerId, selected);
  const [catalog, setCatalog] = useState<{ epoch: number; value: DiagnosticCatalog }>();
  const [page, setPage] = useState<{ epoch: number; value: DiagnosticPage }>();
  const [catalogCursor, setCatalogCursor] = useState<{ epoch: number; after: string }>();
  const [pageCursor, setPageCursor] = useState<{ epoch: number; after: string }>();
  const [catalogRefresh, setCatalogRefresh] = useState(0), [pageRefresh, setPageRefresh] = useState(0);
  const [catalogBusy, setCatalogBusy] = useState(true), [pageBusy, setPageBusy] = useState(false);
  const [catalogError, setCatalogError] = useState<{ epoch: number; text: string }>();
  const [pageError, setPageError] = useState<{ epoch: number; text: string }>();
  const currentCatalog = catalog?.epoch === ownerEpoch ? catalog.value : undefined;
  const currentPage = page?.epoch === pageEpoch ? page.value : undefined;
  const afterCatalog = catalogCursor?.epoch === ownerEpoch ? catalogCursor.after : undefined;
  const afterPage = pageCursor?.epoch === pageEpoch ? pageCursor.after : undefined;
  useEffect(() => {
    const controller = new AbortController(); setCatalogBusy(true); setCatalogError(undefined); setCatalog(undefined);
    void transport.current.list(afterCatalog, controller.signal).then(raw => {
      const value = diagnosticCatalog(raw, ownerId);
      if (!controller.signal.aborted && ownerGuard.current.current(ownerEpoch)) setCatalog({ epoch: ownerEpoch, value });
    }).catch(() => {
      if (!controller.signal.aborted && ownerGuard.current.current(ownerEpoch)) setCatalogError({ epoch: ownerEpoch, text: '诊断计划目录无法读取或核对。可重试只读查询，未改变任何执行。' });
    }).finally(() => { if (!controller.signal.aborted && ownerGuard.current.current(ownerEpoch)) setCatalogBusy(false); });
    return () => controller.abort();
  }, [ownerId, ownerEpoch, afterCatalog, catalogRefresh]);
  useEffect(() => {
    const controller = new AbortController(); setPage(undefined); setPageError(undefined); setPageBusy(!!selected);
    if (selected) void transport.current.page(selected, afterPage, controller.signal).then(raw => {
      const value = diagnosticPage(raw, ownerId, selected);
      if (!controller.signal.aborted && pageGuard.current.current(pageEpoch)) setPage({ epoch: pageEpoch, value });
    }).catch(() => {
      if (!controller.signal.aborted && pageGuard.current.current(pageEpoch)) setPageError({ epoch: pageEpoch, text: '拒绝诊断无法读取或核对。不能据此判断是否触发；可重试只读查询。' });
    }).finally(() => { if (!controller.signal.aborted && pageGuard.current.current(pageEpoch)) setPageBusy(false); });
    return () => controller.abort();
  }, [ownerId, selected, pageEpoch, afterPage, pageRefresh]);
  return <section aria-label="计划触发拒绝诊断" className="schedule-diagnostics" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>计划触发拒绝诊断</h2>
    <p>独立只读查询，不需要计划编辑权限；执行时间修改尚未确认时仍可查看。查询不会触发任务或重放请求。</p>
    <p className="quiet">这是尽力记录的前置拒绝诊断，不是运行成功证明。这里的记录没有创建执行记录或任务；已准入任务请查看原执行历史。</p>
    <button type="button" className="secondary" disabled={catalogBusy} onClick={() => { setCatalogCursor(undefined); setCatalogRefresh(value => value + 1); }}>刷新诊断计划</button>
    {catalogBusy && <p role="status">正在读取诊断计划目录…</p>}
    {catalogError?.epoch === ownerEpoch && <p role="alert">{catalogError.text}</p>}
    <label>选择诊断计划<select aria-label="选择诊断计划" value={selected} disabled={catalogBusy || !currentCatalog} onChange={event => setSelection(event.target.value ? { epoch: ownerEpoch, id: event.target.value } : undefined)}>
      <option value="">请选择原计划</option>
      {selected && !currentCatalog?.items.some(item => item.id === selected) && <option value={selected}>{selected}（已选原计划）</option>}
      {currentCatalog?.items.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
    </select></label>
    {currentCatalog?.items.length === 0 && <p>当前页没有可读取的计划；这不表示计划从未触发。</p>}
    {currentCatalog?.nextCursor && <button type="button" className="secondary" disabled={catalogBusy} onClick={() => setCatalogCursor({ epoch: ownerEpoch, after: currentCatalog.nextCursor! })}>读取下一页诊断计划</button>}
    {selected && <div aria-label="原计划拒绝记录"><p>原计划：{selected}</p>
      <button type="button" className="secondary" disabled={pageBusy} onClick={() => { setPageCursor(undefined); setPageRefresh(value => value + 1); }}>刷新拒绝诊断</button>
      {pageBusy && <p role="status">正在读取保留的拒绝记录…</p>}
      {pageError?.epoch === pageEpoch && <p role="alert">{pageError.text}</p>}
      {currentPage && <><p aria-label="诊断保留范围">保留范围：最近 {currentPage.retention.days} 天，每个计划最多 {currentPage.retention.maxRecords} 条。仅保留的拒绝记录，不是完整触发历史或实时快照。</p>
        {currentPage.items.map(item => <article key={item.id}><h3>{diagnosticReasons[item.reasonCode]}</h3><p><time dateTime={item.observedAt}>{item.observedAt}</time> · {item.source === 'native' ? '原生调度' : '手动触发'}</p><p className="quiet">前置检查未准入；本记录没有创建任务。</p><details><summary>诊断凭据</summary><p>记录 {item.id}</p><p>原因码 {item.reasonCode}</p></details></article>)}
        {currentPage.items.length === 0 && <p>当前页没有保留的拒绝诊断；不能据此判断计划从未触发。</p>}
        {currentPage.nextCursor && <button type="button" className="secondary" disabled={pageBusy} onClick={() => setPageCursor({ epoch: pageEpoch, after: currentPage.nextCursor! })}>读取下一页拒绝诊断</button>}
      </>}
    </div>}
  </section>;
}
