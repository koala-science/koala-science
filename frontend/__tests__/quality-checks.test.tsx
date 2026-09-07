import fs from 'fs';
import path from 'path';

const CONSTITUTION = fs.readFileSync(
  path.join(process.cwd(), 'public', 'CONSTITUTION.md'),
  'utf-8',
);

function _documentedChecks(): string[] {
  return [...CONSTITUTION.matchAll(/^## \d+\.\s*(.+?)\s*$/gm)].map((m) =>
    m[1].toLowerCase(),
  );
}

describe('CONSTITUTION.md', () => {
  it('says what the checks are for and that an argument must pass every one', () => {
    expect(CONSTITUTION).toMatch(/quality of the arguments/i);
    expect(CONSTITUTION).toMatch(/passes all five/i);
  });

  it('titles the page and introduces it before the first check section', () => {
    const title = CONSTITUTION.indexOf('# Quality Checks');
    const firstCheck = CONSTITUTION.indexOf('## 1.');
    expect(title).toBe(0);
    expect(firstCheck).toBeGreaterThan(-1);
    expect(title).toBeLessThan(firstCheck);
  });

  it('shows every check a worked example of failing it', () => {
    const sections = CONSTITUTION.split(/^## \d+\. /m).slice(1);
    expect(sections).toHaveLength(5);
    for (const section of sections) {
      expect(section).toMatch(/^Example:$/m);
      expect(section).toMatch(/^> \*\*Argument/m);
    }
  });

  it('shows the evidence behind every example except uniqueness', () => {
    // An argument is a claim and the evidence for it, so an example carrying
    // only the claim is not an example of what an agent submits. Uniqueness is
    // the exception: it compares two arguments, so its example is a pair.
    const names = _documentedChecks();
    const sections = CONSTITUTION.split(/^## \d+\. /m).slice(1);
    for (const [i, section] of sections.entries()) {
      if (names[i] === 'uniqueness') {
        expect(section).toMatch(/^> \*\*Argument 1:\*\*/m);
        expect(section).toMatch(/^> \*\*Argument 2:\*\*/m);
        expect(section).not.toMatch(/Evidence:/);
      } else {
        expect(section).toMatch(/^> \*\*Evidence:\*\*/m);
      }
    }
  });

  it('follows every `Example:` with the quoted example itself', () => {
    // `Example:` is a plain paragraph, so a blockquote that does not start on
    // the line after it renders as a heading with nothing under it.
    const lines = CONSTITUTION.split('\n');
    const orphaned = lines.filter(
      (line, i) => line === 'Example:' && !lines[i + 2]?.startsWith('> '),
    );
    expect(orphaned).toEqual([]);
  });
});
