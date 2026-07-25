# Comparison-page inventory and linking rules

Date: 2026-07-24. Internal planning record for `site/`; not published.
Shipped in commits 476422b and 10da057, live on Cloudflare.

The comparison surface went from 4 pages to 12 in one project. This document is
the current inventory, the internal-linking rule those pages follow, and the
checklist for adding a thirteenth page. The checklist exists because three of
the touch points are easy to miss and two of them break the build.

---

## 1. Inventory (12 pages, 5 clusters)

Clusters are the editorial grouping used by the internal-linking rule below.
`/open-source-meeting-assistants/` is both the hub for the whole surface and the
landscape page for the open-source cluster.

| Cluster | Page | Angle |
| --- | --- | --- |
| Open-source / local | `/open-source-meeting-assistants/` **(hub)** | The self-hosted landscape (Meetily, Anarlog, Amurex, Vibe, Buzz, Backchannel) compared honestly, including when to pick something else |
| Open-source / local | `/vs-meetily/` | Two open-source meeting assistants compared |
| Open-source / local | `/vs-anarlog/` | Local-first Mac notetaker (formerly Hyprnote) vs a live agent server |
| Cloud notetakers | `/otter-alternative/` | Self-hosted transcripts and insights without minute caps |
| Cloud notetakers | `/fireflies-alternative/` | Live assistance on your own hardware, no bot in the room |
| Cloud notetakers | `/granola-alternative/` | Bot-free capture, but self-hosted and real-time |
| Cloud notetakers | `/fathom-alternative/` | What a generous free tier does and does not cover |
| Cloud notetakers | `/read-ai-alternative/` | Meeting intelligence without the auto-join governance problem |
| Revenue intelligence | `/gong-and-backchannel/` | Not a Gong replacement -- where a live seller-side layer fits underneath |
| Revenue intelligence | `/vs-clari-copilot/` | Responses generated against the objection actually raised vs pre-written battlecards |
| Hardware | `/plaud-alternative/` | Bot-free capture without buying hardware or shipping audio to a vendor cloud |
| Platform incumbents | `/teams-premium-alternative/` | One assistant across every meeting platform instead of one per platform |

Pre-existing before this project: `/otter-alternative/`, `/fireflies-alternative/`,
`/granola-alternative/`, `/vs-meetily/`. The other eight are new.

---

## 2. Internal-linking rule (hub and spoke)

Two mechanisms, and they are not the same list. This trips people up.

**A. The shared `footer-compare` block -- 7 links, identical on every page.**
Verified byte-identical across all 28 HTML files that carry it. Order is fixed,
hub first:

1. `/open-source-meeting-assistants/` (hub)
2. `/otter-alternative/`
3. `/fireflies-alternative/`
4. `/granola-alternative/`
5. `/fathom-alternative/`
6. `/gong-and-backchannel/`
7. `/teams-premium-alternative/`

This is a curated head-traffic set, not one-per-cluster: four cloud notetakers,
one revenue-intelligence page, one platform-incumbent page, plus the hub. Five
pages (`/read-ai-alternative/`, `/plaud-alternative/`, `/vs-anarlog/`,
`/vs-clari-copilot/`, `/vs-meetily/`) are deliberately NOT in the footer -- they
are reached through the hub and through same-cluster doc-lists. Keeping the
footer at 7 is what stops it becoming a 12-link sitemap strip on every page.

**B. Per-page "Other comparisons" doc-list -- same-cluster siblings + the hub.**
Each page closes with a `.doc-list` of its own cluster's siblings, with the hub
always last. Observed shape:

| Page | doc-list targets |
| --- | --- |
| `/otter-alternative/` | fireflies, granola, fathom, **hub** |
| `/read-ai-alternative/` | fathom, otter, fireflies, **hub** |
| `/vs-meetily/` | vs-anarlog, **hub**, granola |
| `/plaud-alternative/` | granola, otter, **hub** |
| `/gong-and-backchannel/` | vs-clari-copilot, teams-premium, **hub** |

Net effect: the hub is the only page every spoke links to, cross-cluster leakage
happens through the footer rather than the body, and no page carries all eleven
siblings.

**Rule of thumb for new pages:** put the page in a cluster, link it to its
cluster siblings plus the hub, add it to the hub, and only add it to
`footer-compare` if it is displacing something -- not in addition.

---

## 3. Adding a thirteenth page: required touch points

The page directory itself is the easy part. These are the ones that get missed.
The last two are build-breaking.

| # | Touch point | What changes | Breaks if missed? |
| --- | --- | --- | --- |
| 1 | `site/<new-page>/index.html` | The page. | n/a |
| 2 | `footer-compare` block across **28 HTML files** | Only if the new page joins the footer set. Every one of the 28 must stay identical -- the block is copy-pasted, not templated. | No, but a drifted footer is a silent inconsistency across 28 pages |
| 3 | Same-cluster `.doc-list` blocks | Add the new page to its siblings, and the siblings to it. | No |
| 4 | `site/sitemap.xml` | Add a `<loc>`. Currently 28 `<url>` entries, 12 of them comparison pages. | No, but the page will not be discovered |
| 5 | `site/llms.txt` | Add a bullet to the comparison list (currently 12 bullets). | No, but AI-search surfaces lose it |
| 6 | `docs-site/site.test.js` -> `customerFiles` array | Add the path. | **Yes** |
| 7 | `docs-site/site.test.js` -> inline array in the `customer download entry points use the authenticated Backchannel portal` test | Add the path. | **Yes** |

The two `site.test.js` lists are **separate hardcoded arrays** and both enumerate
all 12 comparison pages independently. There is no shared constant. Miss either
one and `npm run test:site` fails or, worse, silently stops covering the new
page for the forbidden-content and download-portal assertions.

The 28 files carrying `footer-compare` are: `site/index.html`, the 12 comparison
pages, `site/releases/index.html`, and the 14 versioned release pages.
`site/style.css` holds the `.footer-compare` rule itself (styling only, no links).

**Verification after any change:**

```bash
# every footer-compare block should print one unique line
for f in $(grep -rl "footer-compare" site/ --include=*.html); do
  sed -n '/footer-compare/,/<\/div>/p' "$f" | grep -o 'href="/[a-z0-9-]*/"' | tr '\n' ' '; echo
done | sort -u

cd docs-site && npm run test:site && npm run build
```

---

## 4. Content-accuracy notes from this project

Corrections applied to previously published pages on 2026-07-24, recorded here
so the same claims do not get reintroduced:

- Removed a false "no open-source tool other than Backchannel" claim.
- Removed a false "Meetily has no diarization" claim.
- Added Otter Live Assist (Otter does have a live-assistance surface).
- Otter user count corrected 40M -> 35M.
- Corrected an undersell of the agent roster (four agents -> nine).

The nine-agent roster is authoritative in `backend/app/services/seed_agents.py`
and `docs-site/site.test.js` already asserts the landing page's agent slugs
against it. Claims about competitors carry no such test -- they are prose, and
the honest-comparison tone is the asset. Verify before publishing, not after.
