/**
 * Renders markdown content with consistent, compact typography.
 * Used for reviews, comments, and any user-generated markdown.
 */

import ReactMarkdown from 'react-markdown';
import { cn } from '@/lib/utils';

interface MarkdownProps {
  children: string;
  className?: string;
  compact?: boolean;
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
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}
