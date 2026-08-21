import fs from 'fs';
import path from 'path';
import ReactMarkdown from 'react-markdown';

export const metadata = {
  title: 'The Constitution — Koala Science',
};

const CONTENT = fs.readFileSync(
  path.join(process.cwd(), 'public', 'CONSTITUTION.md'),
  'utf-8',
);

export default function ConstitutionPage() {
  return (
    <article
      aria-label="The constitution of each check"
      className="prose prose-slate mx-auto max-w-3xl px-4 py-6 sm:py-10"
    >
      <ReactMarkdown>{CONTENT}</ReactMarkdown>
    </article>
  );
}
