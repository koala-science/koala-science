import katex from 'katex';
import 'katex/dist/katex.min.css';

/**
 * Renders text with inline ($...$) and display ($$...$$) LaTeX math,
 * plus common text-mode commands (\emph, \textbf, \textit, \texttt, \url, ...).
 * Works in both server and client components.
 */
export function LaTeX({ children, className }: { children: string; className?: string }) {
  const html = renderLatex(children);
  return <span className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderLatex(text: string): string {
  const tokens: string[] = [];
  const hold = (html: string) => {
    const i = tokens.length;
    tokens.push(html);
    return `\x00${i}\x00`;
  };

  let out = text
    .replace(/\$\$([^$]+?)\$\$/g, (_, tex) => {
      try {
        return hold(katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }));
      } catch {
        return `$$${tex}$$`;
      }
    })
    .replace(/\$([^$]+?)\$/g, (_, tex) => {
      try {
        return hold(katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }));
      } catch {
        return `$${tex}$`;
      }
    });

  out = escapeHtml(out);

  const wrap = (s: string, cmd: string, open: string, close: string) => {
    const re = new RegExp(`\\\\${cmd}\\s*\\{([^{}]*)\\}`, 'g');
    return s.replace(re, (_, inner) => `${open}${inner}${close}`);
  };

  for (let i = 0; i < 4; i++) {
    out = wrap(out, 'emph', '<em>', '</em>');
    out = wrap(out, 'textit', '<em>', '</em>');
    out = wrap(out, 'textsl', '<em>', '</em>');
    out = wrap(out, 'textbf', '<strong>', '</strong>');
    out = wrap(out, 'textmd', '', '');
    out = wrap(out, 'textrm', '', '');
    out = wrap(out, 'textsf', '', '');
    out = wrap(out, 'textup', '', '');
    out = wrap(out, 'texttt', '<code>', '</code>');
    out = wrap(out, 'textsc', '<span style="font-variant:small-caps">', '</span>');
    out = wrap(out, 'underline', '<u>', '</u>');
    out = wrap(out, 'mbox', '', '');
    out = wrap(out, 'text', '', '');
  }

  out = out.replace(/\\href\s*\{([^{}]+)\}\s*\{([^{}]+)\}/g, (_, url, txt) =>
    `<a href="${url}" target="_blank" rel="noreferrer" class="underline">${txt}</a>`,
  );
  out = out.replace(/\\url\s*\{([^{}]+)\}/g, (_, url) =>
    `<a href="${url}" target="_blank" rel="noreferrer" class="underline">${url}</a>`,
  );

  out = out
    .replace(/\\%/g, '%')
    .replace(/\\&/g, '&amp;')
    .replace(/\\_/g, '_')
    .replace(/\\#/g, '#')
    .replace(/\\\$/g, '$')
    .replace(/\\\{/g, '{')
    .replace(/\\\}/g, '}')
    .replace(/\\ldots\b/g, '&hellip;')
    .replace(/\\dots\b/g, '&hellip;')
    .replace(/~/g, '&nbsp;');

  out = out
    .replace(/---/g, '&mdash;')
    .replace(/--/g, '&ndash;')
    .replace(/``/g, '&ldquo;')
    .replace(/''/g, '&rdquo;');

  out = out.replace(/\x00(\d+)\x00/g, (_, i) => tokens[Number(i)]);

  return out;
}
