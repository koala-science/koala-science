/**
 * Renders markdown content with LaTeX math support.
 * Used for arguments and any user-generated markdown.
 *
 */

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { cn } from '@/lib/utils';

interface MarkdownProps {
  children: string;
  className?: string;
  compact?: boolean;
}


function getLinkText(children: React.ReactNode): string | null {
  if (typeof children === 'string') return children;
  if (Array.isArray(children) && children.length === 1 && typeof children[0] === 'string') {
    return children[0];
  }
  return null;
}

function shortenUrl(href: string, maxLen = 50): string {
  try {
    const u = new URL(href);
    const base = u.host + u.pathname;
    if (base.length > maxLen) return base.slice(0, maxLen - 1) + '…';
    return u.search || u.hash ? base + '…' : base;
  } catch {
    return href.length > maxLen ? href.slice(0, maxLen - 1) + '…' : href;
  }
}

export function Markdown({
  children,
  className,
  compact = false,
}: MarkdownProps) {
  return (
    <div className={cn(
      "prose prose-sm max-w-none",
      "prose-h2:text-sm prose-h3:text-sm prose-h2:font-semibold prose-h3:font-semibold",
      "prose-h2:mt-3 prose-h2:mb-1 prose-h3:mt-2 prose-h3:mb-1",
      // Long URLs / unbroken strings shouldn't blow out the column width on mobile.
      "[overflow-wrap:anywhere]",
      compact && "prose-p:my-0.5",
      className,
    )}>
      <ReactMarkdown
        remarkPlugins={[remarkMath, remarkGfm]}
        rehypePlugins={[rehypeKatex]}
        components={{
          p: ({ children, ...props }) => (
            <p {...props}>{children}</p>
          ),
          li: ({ children, ...props }) => (
            <li {...props}>{children}</li>
          ),
          a: ({ children, href, ...props }) => {
            const text = getLinkText(children);
            const isBareUrl = !!(href && text && text === href);
            const display = isBareUrl && href!.length > 50 ? shortenUrl(href!) : children;
            return (
              <a
                {...props}
                href={href}
                title={isBareUrl ? href : undefined}
                target="_blank"
                rel="noopener noreferrer"
              >
                {display}
              </a>
            );
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

