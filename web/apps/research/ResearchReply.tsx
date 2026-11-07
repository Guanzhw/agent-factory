import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function ResearchReply({ text }: { text: string }) {
  return <div className="rs-markdown"><Markdown remarkPlugins={[remarkGfm]} components={{ img: ({ alt }) => <span>{alt || '图片'}</span> }}>{text}</Markdown></div>;
}
