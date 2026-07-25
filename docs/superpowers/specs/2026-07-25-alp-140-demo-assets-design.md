# ALP-140 Demo Data and Showcase Asset Replacement

## Problem

The public showcase is not reproducible end to end. The Offerings Catalog
capture is empty, Knowledge Sources shows only its built-in placeholder, and
`showcase/capture.mjs` does not regenerate the live-call or chat images. The
current Northwind story therefore survives in assets that the documented
pipeline cannot fully replace.

## Scenario

Use one wholly fictional client-sales meeting for a distributed services
integrator / value-added reseller account team:

- Customer: **Alderwake Health Network**
- Meeting: **Alderwake Health Network - recovery readiness review**
- Internal participants: a remote account lead and solutions architect
- Customer participants: an infrastructure director and security lead
- Stakes: a ransomware recovery exercise exposed an eight-hour restoration
  gap; the board risk committee and cyber-insurance renewal create a fixed
  deadline; clinical systems cannot tolerate a disruptive cutover
- Commercial shape: a tightly scoped recovery-readiness pilot, a separate
  managed-service option, procurement constraints, named owners, and a
  follow-on implementation path

Every company, person, number, product note, and quote in the demo remains
invented. Real vendor names may remain only in the generic sample catalog,
where they are already presented as products rather than customers or
testimonials.

## Data

`showcase/seed_demo.py` becomes the single source of truth for:

- group, sessions, meeting context, speakers, transcript, and canned insights;
- a completed deterministic briefing;
- a populated sample offerings catalog;
- a small fictional delivery-playbook knowledge collection;
- stable durations and counts used by the public site.

The canned dataset is the default showcase path. Running an LLM analysis stays
available as an optional development path, but committed screenshots must not
depend on model availability or variable wording.

## Capture and Assets

`showcase/capture.mjs` must capture all twelve product surfaces in both light
and dark themes:

1. live call
2. post-call briefing
3. post-call insights
4. post-call transcript
5. post-call speakers
6. post-call chat
7. admin agents
8. admin transcription
9. admin API keys
10. admin about
11. offerings catalog
12. knowledge sources

The live call uses the real Active Call surface over seeded transcript and
insight rows. Chat uses the product's real session-storage rendering with a
deterministic fictional exchange. No screenshot is generatively edited or
assembled from fake UI rectangles.

`showcase/encode.py` regenerates all full WebP assets. `showcase/crops.py`
regenerates the three focused crops in both themes from the new full captures.
Crop boxes may change only after visual inspection confirms the intended card
or header is fully visible.

## Public Site and Documentation

Update the screenshot README, capture selectors, homepage statistics,
figcaptions, alt text, and declared image dimensions to match the new
deterministic fixture. Remove tracked references to the retired Northwind
names and story, except historical archive documentation that explicitly
identifies retired assets.

## Validation

Add one stdlib/Pillow-based showcase check that fails when:

- an expected full capture or derived WebP is absent;
- an asset has the wrong dimensions;
- a current tracked showcase/site source retains a retired story marker;
- the expected light/dark and crop manifest is incomplete.

Run the showcase check, frontend build, backend unittest suite, six focused
docs-site suites, aggregate docs-site suite, docs-site build, Sentrux checks,
and `git diff --check`. Visually inspect the complete light/dark asset set and
the assembled homepage at desktop and mobile widths.

## Editorial and Release Gate

After the implementation and assets are complete, send the branch diff,
homepage copy, screenshot manifest, and representative captures to the
existing Herdr tab `claude-2` (`w2:pG`) for an editorial review and enhancement
workflow. Implement actionable findings, rerun affected checks, and obtain a
clear review verdict before publication.

Push the reviewed branch, merge it into `master`, and let the existing
Cloudflare deploy workflow publish the exact merged commit. Verify the GitHub
workflow, homepage text, and representative production assets before marking
ALP-140 done.
