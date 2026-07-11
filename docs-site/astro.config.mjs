// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Deployed as a Cloudflare Worker (see wrangler.jsonc) with the site/
// landing page at / and these docs at /docs/. Markdown cross-links are
// rewritten to relative URLs by sync-docs.mjs, so they work at any base.
export default defineConfig({
  site: 'https://backchannel.page',
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
        // ponytail: absolute path escapes the /docs base back to the landing page
        { label: '← Back to homepage', link: 'https://backchannel.page/' },
        {
          label: 'Getting started',
          items: [
            { label: 'Overview', link: '/' },
            'quickstart',
            'architecture',
          ],
        },
        {
          label: 'Reference',
          items: [
            'agents',
            'audio-pipeline',
            'websocket-protocol',
            'rest-api',
            'configuration',
            'deployment',
            'releasing',
          ],
        },
      ],
      customCss: ['./src/styles/custom.css'],
    }),
  ],
});
