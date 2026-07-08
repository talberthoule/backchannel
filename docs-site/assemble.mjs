// Assembles the deployable site: the site/ landing page at /, the built
// Starlight docs at /docs/. wrangler deploys dist-site/ as Worker assets.
import { cpSync, rmSync } from 'node:fs';
import { join } from 'node:path';

const root = import.meta.dirname;
const out = join(root, 'dist-site');
rmSync(out, { recursive: true, force: true });
cpSync(join(root, '..', 'site'), out, { recursive: true });
cpSync(join(root, 'dist'), join(out, 'docs'), { recursive: true });
console.log('Assembled', out);
