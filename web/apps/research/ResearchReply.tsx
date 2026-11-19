import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Children, useState, type ReactElement, type ReactNode } from 'react';
import { CopyButton } from './CopyButton.js';

function CodeBlock({ children }: { children?: ReactNode }) {
  const code = Children.only(children) as ReactElement<{ className?: string; children?: string }>;
  const text = (code.props.children ?? '').replace(/\n$/, '');
  const [wrap, setWrap] = useState(true);
  return <div className="rs-code-block"><header><span>{code.props.className?.replace('language-', '') || '代码'}</span>
    <label><input type="checkbox" checked={wrap} onChange={event => setWrap(event.target.checked)}/>自动换行</label>
    <CopyButton text={text} label="复制代码"/></header>
    <pre className={wrap ? 'rs-code-wrap' : undefined}>{children}</pre>
  </div>;
}

export function ResearchReply({ text, sessionId }: { text: string; sessionId?: string }) {
  function artifact(href?: string) {
    if (!sessionId || !href || /^([a-z][a-z\d+.-]*:|[/#?])/i.test(href)) return;
    try {
      const path = decodeURIComponent(href).replace(/^\.\//, '');
      if (path.split(/[\\/]/).some(part => !part || part === '..')) return;
      return `/api/factory/research/sessions/${encodeURIComponent(sessionId)}/files/download?path=${encodeURIComponent(path)}`;
    } catch { return; }
  }
  return <div className="rs-markdown"><Markdown remarkPlugins={[remarkGfm]} components={{ pre: CodeBlock, table: ({ children }) => <div className="rs-table-scroll"><table>{children}</table></div>, a: ({ href, children }) => {
    const url = artifact(href);
    return <a href={url ?? href} download={url ? true : undefined}>{children}</a>;
  }, img: ({ alt, src }) => {
    const url = typeof src === 'string' && /\.(?:png|jpe?g|gif|webp|avif)$/i.test(src) && artifact(src);
    return url ? <img loading="lazy" src={url} alt={alt ?? ''}/> : <span>{alt || '图片'}</span>;
  } }}>{text}</Markdown></div>;
}
