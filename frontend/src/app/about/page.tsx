import fs from 'fs';
import path from 'path';
import ReactMarkdown from 'react-markdown';

export const metadata = {
  title: 'About — Koala Science',
};

const CONTENT = fs.readFileSync(
  path.join(process.cwd(), 'public', 'ABOUT.md'),
  'utf-8',
);

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-6 sm:py-10">
      <article className="prose prose-slate max-w-none">
        <ReactMarkdown>{CONTENT}</ReactMarkdown>
      </article>
    </div>
  );
}
