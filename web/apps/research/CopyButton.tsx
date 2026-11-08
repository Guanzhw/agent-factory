import { useState } from 'react';
import { IconCheck, IconCopy } from '@tabler/icons-react';

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  async function copy() {
    setFailed(false);
    try { await navigator.clipboard.writeText(text); setCopied(text); }
    catch { setFailed(true); }
  }
  const Icon = copied === text ? IconCheck : IconCopy;
  return <span className="rs-copy"><button type="button" aria-label={label} title={copied === text ? '已复制' : label} onClick={() => void copy()}><Icon size={15}/></button>
    <span className="sr-only" role="status">{copied === text ? '已复制' : ''}</span>
    {failed && <span role="alert">复制失败，请手动选择文本。</span>}
  </span>;
}
