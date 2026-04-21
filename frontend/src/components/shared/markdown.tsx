/**
 * Renders markdown content with LaTeX math support.
 * Used for reviews, comments, and any user-generated markdown.
 *
 * Also intercepts inline `[[comment:<uuid>]]` citation tokens and
 * renders them as anchors pointing to `#comment-<uuid>`. Malformed
 * tokens fall through as plain text. This matches the server-side
 * parser in `backend/app/core/verdict_citations.py`.
 *
 * Limitation: citations are rendered as anchors only when they appear
 * as direct text children of `<p>` or `<li>`. Tokens inside headings,
 * blockquotes, tables, or emphasized spans render as plain text. The
 * backend still validates them regardless of placement.
 */

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { cn } from '@/lib/utils';

interface MarkdownProps {
  children: string;
  className?: string;
  compact?: boolean;
}

const COMMENT_CITATION_RE =
  /\[\[comment:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\]\]/g;

function renderCitations(text: string): React.ReactNode {
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  COMMENT_CITATION_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = COMMENT_CITATION_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const commentId = match[1].toLowerCase();
    nodes.push(
      <a
        key={match.index}
        href={`#comment-${commentId}`}
        className="text-primary hover:underline"
      >
        [[comment:{commentId}]]
      </a>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes.length === 1 ? nodes[0] : nodes;
}

export function Markdown({ children, className, compact = false }: MarkdownProps) {
  return (
    <div className={cn(
      "prose prose-sm max-w-none",
      "prose-h2:text-sm prose-h3:text-sm prose-h2:font-semibold prose-h3:font-semibold",
      "prose-h2:mt-3 prose-h2:mb-1 prose-h3:mt-2 prose-h3:mb-1",
      compact && "prose-p:my-0.5",
      className,
    )}>
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          p: ({ children, ...props }) => (
            <p {...props}>{renderChildrenWithCitations(children)}</p>
          ),
          li: ({ children, ...props }) => (
            <li {...props}>{renderChildrenWithCitations(children)}</li>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

function renderChildrenWithCitations(children: React.ReactNode): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === 'string') {
      return renderCitations(child);
    }
    return child;
  });
}
