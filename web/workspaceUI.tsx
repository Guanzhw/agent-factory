import { statusNames } from './models.js';
export function time(value?: string) {
  if (!value) return '未知';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '未知' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
export function Badge({ value, label }: { value: string; label?: string }) { return <span className={`badge status-${value}`}>{label ?? statusNames[value] ?? value}</span>; }
export function ErrorMessage({ message, retry }: { message: string; retry?: () => void }) {
  return message ? <div className="error-message" role="alert"><span>{message}</span>{retry && <button className="text-button" onClick={retry}>重新连接</button>}</div> : null;
}
