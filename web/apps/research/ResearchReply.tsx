import Markdown from 'react-markdown';

export function ResearchReply({ text }: { text: string }) {
  return <div className="rs-markdown"><Markdown components={{ img: ({ alt }) => <span>{alt || '图片'}</span> }}>{text}</Markdown></div>;
}
