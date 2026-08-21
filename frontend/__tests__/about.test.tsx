import fs from 'fs';
import path from 'path';

const ABOUT = fs.readFileSync(
  path.join(process.cwd(), 'public', 'ABOUT.md'),
  'utf-8',
);

describe('ABOUT.md', () => {
  it('says arguments come from AI agents and must pass every check to count', () => {
    expect(ABOUT).toMatch(/AI agents/i);
    expect(ABOUT).toMatch(/passes all four/i);
  });

  it('introduces the constitution before the first check section', () => {
    const constitution = ABOUT.toLowerCase().indexOf('constitution');
    const firstCheck = ABOUT.indexOf('## 1.');
    expect(constitution).toBeGreaterThan(-1);
    expect(firstCheck).toBeGreaterThan(-1);
    expect(constitution).toBeLessThan(firstCheck);
  });

  it('gives every check a passing and a failing example', () => {
    const sections = ABOUT.split(/^## \d+\. /m).slice(1);
    expect(sections).toHaveLength(4);
    for (const section of sections) {
      expect(section).toMatch(/passes:/i);
      expect(section).toMatch(/fails:/i);
    }
  });

  it('keeps every example in its own paragraph', () => {
    // A `> **Fails:**` line directly after another blockquote line is joined to
    // it by a soft break, which renders the pair as one run-on paragraph.
    const lines = ABOUT.split('\n');
    const runOn = lines.filter(
      (line, i) =>
        /^> \*\*(Fails|Passes):/.test(line) &&
        lines[i - 1].startsWith('>') &&
        lines[i - 1].trim() !== '>',
    );
    expect(runOn).toEqual([]);
  });
});
