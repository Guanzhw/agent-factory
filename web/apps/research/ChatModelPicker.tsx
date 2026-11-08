import { useId, useRef } from 'react';
import { IconChevronDown, IconSettings } from '@tabler/icons-react';
import type { SessionOptions } from './researchSessionsClient.js';
import './modelPicker.css';

export function ChatModelPicker({ models, modelConnectionRef, reasoningEffort, onChange, onManage }: {
  models: SessionOptions['models']; modelConnectionRef: string; reasoningEffort?: string;
  onChange: (connectionRef: string, reasoningEffort?: string) => void; onManage: () => void;
}) {
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  const selected = models.find(model => model.connectionRef === modelConnectionRef);
  const efforts = selected?.reasoningEfforts ?? [];
  return <div className="rs-model-picker">
    <button type="button" className="rs-composer-model" aria-label="选择模型" popoverTarget={id}>
      <span>{selected?.model ?? '选择模型'}{reasoningEffort ? ` · ${reasoningEffort}` : ''}</span><IconChevronDown size={14}/>
    </button>
    <div ref={panel} id={id} popover="auto" className="rs-model-popover" aria-label="模型选择">
      <div role="listbox" aria-label="已配置模型" onKeyDown={event => {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        const options = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
        if (!options.length) return;
        event.preventDefault();
        const current = options.indexOf(document.activeElement as HTMLButtonElement);
        const index = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
          : (current + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
        options[index].focus();
      }}>{models.map(model => <button type="button" role="option"
        key={model.connectionRef} aria-selected={model.connectionRef === modelConnectionRef} disabled={!model.available}
        onClick={() => {
          onChange(model.connectionRef, model.connectionRef === modelConnectionRef ? reasoningEffort : undefined);
          panel.current?.hidePopover();
        }}><span>{model.model}</span>{!model.available && <small>不可用</small>}</button>)}</div>
      {!models.length && <p>请先配置一个模型。</p>}
      {efforts.length > 0 && <label>推理强度<select aria-label="推理强度" value={reasoningEffort ?? ''}
        onChange={event => onChange(modelConnectionRef, event.target.value || undefined)}>
        <option value="">自动</option>{efforts.map(effort => <option key={effort} value={effort}>{effort}</option>)}
      </select></label>}
      <button type="button" className="rs-model-manage" onClick={() => { panel.current?.hidePopover(); onManage(); }}><IconSettings size={16}/>管理模型</button>
    </div>
  </div>;
}
