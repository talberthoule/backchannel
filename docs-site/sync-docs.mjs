// Copies ../docs/*.md into src/content/docs/ for Starlight.
// The repo docs/ folder stays plain GitHub-flavored markdown (the source of
// truth); this derives the required frontmatter title from each file's H1 and
// rewrites cross-links from "foo.md" to relative page URLs.
import { copyFileSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const SRC = join(import.meta.dirname, '..', 'docs');
const OUT = join(import.meta.dirname, 'src', 'content', 'docs');
const REPO_URL = 'https://github.com/talberthoule/backchannel';

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

for (const file of readdirSync(SRC).filter((f) => f.endsWith('.md'))) {
  const slug = file === 'README.md' ? 'index' : file.replace(/\.md$/, '');
  let text = readFileSync(join(SRC, file), 'utf8');

  // Drop the GitHub-only wordmark banner; Starlight has its own header.
  text = text.replace(/^<p align="center">[\s\S]*?<\/p>\s*/, '');

  const h1 = text.match(/^# (.+)$/m);
  if (!h1) throw new Error(`${file}: no H1 to derive a title from`);
  // Replace only the heading text, not the trailing newline: on Windows
  // checkouts the line ends \r\n, and "h1[0] + '\n'" would fail to match,
  // leaving a duplicate H1 under Starlight's own page title.
  text = text.replace(h1[0], '');

  // Links to repo files outside docs/ go to GitHub.
  text = text
    .replaceAll('](../README.md)', `](${REPO_URL}#readme)`)
    .replaceAll('](../architecture.svg)', '](./architecture.svg)');

  // "foo.md" / "foo.md#hash" -> relative page URL. Pages live at /<slug>/,
  // so siblings are one level up -- except from the index page.
  const prefix = slug === 'index' ? './' : '../';
  text = text.replace(
    /\]\(([\w-]+)\.md(#[^)]*)?\)/g,
    (_, name, hash = '') => `](${prefix}${name === 'README' ? '' : name + '/'}${hash})`
  );

  // Per-page meta description: first prose block (headings/tables/images/code
  // skipped), markdown stripped, truncated to ~155 chars at a word boundary.
  const block = text.split(/\n\s*\n/).map((b) => b.trim()).find((b) => b && !/^[#|<!`]/.test(b));
  const plain = (block ?? h1[1])
    .replace(/^\s*(?:[-*]|\d+\.)\s+/gm, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[`*]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  const description = plain.length > 155 ? plain.slice(0, 155).replace(/\s+\S*$/, '') : plain;

  writeFileSync(
    join(OUT, `${slug}.md`),
    `---\ntitle: ${JSON.stringify(h1[1])}\ndescription: ${JSON.stringify(description)}\n---\n\n${text}`
  );
}

// Referenced by architecture.md; lives at the repo root for the main README.
copyFileSync(join(SRC, '..', 'architecture.svg'), join(OUT, 'architecture.svg'));

// Screenshots and other images referenced by the docs as assets/<file>.
const ASSETS = join(SRC, 'assets');
mkdirSync(join(OUT, 'assets'), { recursive: true });
for (const file of readdirSync(ASSETS).filter((f) => /\.(png|svg|jpe?g|gif|webp)$/i.test(f))) {
  copyFileSync(join(ASSETS, file), join(OUT, 'assets', file));
}
console.log('Synced docs from', SRC);
