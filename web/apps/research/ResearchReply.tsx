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

export function ResearchReply({ text }: { text: string }) {
  return <div className="rs-markdown"><Markdown remarkPlugins={[remarkGfm]} components={{ pre: CodeBlock, table: ({ children }) => <div className="rs-table-scroll"><table>{children}</table></div>, img: ({ alt }) => <span>{alt || '图片'}</span> }}>{text}</Markdown></div>;
}
