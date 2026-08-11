import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

type MessageContentProps = {
  text: string;
  markdown?: boolean;
};

export default function MessageContent({ text, markdown = false }: MessageContentProps) {
  if (!markdown) {
    return <pre className="message-plain">{text}</pre>;
  }

  return (
    <div className="message-md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
