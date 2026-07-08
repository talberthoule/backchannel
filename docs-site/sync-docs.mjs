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
  text = text.replace(h1[0] + '\n', '');

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

  writeFileSync(join(OUT, `${slug}.md`), `---\ntitle: ${JSON.stringify(h1[1])}\n---\n\n${text}`);
}

// Referenced by architecture.md; lives at the repo root for the main README.
copyFileSync(join(SRC, '..', 'architecture.svg'), join(OUT, 'architecture.svg'));
console.log('Synced docs from', SRC);
