'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose prose-xs max-w-none text-slate-600
      prose-headings:text-slate-200 prose-headings:font-semibold
      prose-h1:text-sm prose-h2:text-xs prose-h3:text-xs prose-h4:text-xs
      prose-p:text-xs prose-p:leading-relaxed
      prose-li:text-xs prose-li:leading-relaxed
      prose-code:text-[10px] prose-code:bg-slate-700 prose-code:px-1 prose-code:py-0.5 prose-code:rounded
      prose-pre:bg-slate-700 prose-pre:text-[10px] prose-pre:rounded-lg prose-pre:border prose-pre:border-slate-700
      prose-table:text-[10px] prose-th:font-medium prose-th:text-slate-400
      prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline
      prose-strong:text-slate-200 prose-strong:font-semibold
      prose-blockquote:border-l-slate-300 prose-blockquote:text-slate-400 prose-blockquote:text-xs">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
