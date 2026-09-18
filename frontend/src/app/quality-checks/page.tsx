import fs from 'fs';
import path from 'path';
import ReactMarkdown from 'react-markdown';
import { PageShell } from '@/components/shared/page';

export const metadata = {
  title: 'Quality Checks — Koala Science',
};

export default function QualityChecksPage() {
  // Read per render, not at module scope: the markdown is not a module
  // dependency, so a module-level read leaves `next dev` serving whatever the
  // file said when the page was first compiled, however often it is edited.
  const content = fs.readFileSync(
    path.join(process.cwd(), 'public', 'CONSTITUTION.md'),
    'utf-8',
  );

  return (
    <PageShell>
      <article
        aria-label="The quality checks"
        // The typography plugin opens and closes every blockquote with a quote
        // mark of its own, which lands before "Fails:" and reads as a stray
        // character next to examples that carry their own quotes.
        className={
          'prose prose-slate max-w-none ' +
          '[&_blockquote_p:first-of-type]:before:content-none '+
          '[&_blockquote_p:last-of-type]:after:content-none'
        }
      >
        <ReactMarkdown>{content}</ReactMarkdown>
      </article>
    </PageShell>
  );
}
