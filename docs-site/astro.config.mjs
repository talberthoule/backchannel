// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Deployed as a Cloudflare Worker (see wrangler.jsonc) with the site/
// landing page at / and these docs at /docs/. Markdown cross-links are
// rewritten to relative URLs by sync-docs.mjs, so they work at any base.
export default defineConfig({
  site: 'https://backchannel-site.lavender-zebu.workers.dev',
  base: '/docs',
  integrations: [
    starlight({
      title: 'Backchannel',
      description:
        'Real-time meeting transcription with AI agents that surface questions, objections, opportunities, and action items as the conversation happens.',
      logo: { src: './src/assets/mark.svg' },
      favicon: '/favicon.svg',
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/talberthoule/backchannel',
        },
      ],
      sidebar: [
        { label: 'Overview', link: '/' },
        'quickstart',
        'architecture',
        'agents',
        'audio-pipeline',
        'websocket-protocol',
        'rest-api',
        'configuration',
        'deployment',
      ],
      customCss: ['./src/styles/custom.css'],
    }),
  ],
});
