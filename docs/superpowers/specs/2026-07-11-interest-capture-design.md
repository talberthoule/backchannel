# Secure Interest Capture - Design

Date: 2026-07-11
Status: Approved

## Goal

Replace the landing page's inaccessible anonymous desktop-download path with
a clear early-access request flow. Store the smallest useful consent record in
Cloudflare D1 so invites and future release/news updates can be tracked without
adding a mailing-service dependency.

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| System of record | Cloudflare D1 | The site already runs as a Cloudflare Worker; D1 is private, queryable, and exportable without another vendor |
| Abuse protection | Cloudflare Turnstile with mandatory server verification | Protects the public write endpoint without a user account or visible CAPTCHA in the normal case |
| Data collected | Email plus operational and consent metadata | Name, company, IP address, and free text are unnecessary for invites and updates |
| Hero action | `Request early access` anchor | Matches the private installer policy and is more honest than an anonymous download link |
| Form placement | Dedicated final-page section | Keeps the hero legible, avoids modal code, and gives the consent copy room to be clear |
| List operations | D1 dashboard/Wrangler queries and export | An internet-facing admin/export endpoint would add risk and is not needed yet |

## Experience

The hero keeps two actions:

1. `Request early access` (primary) jumps to `#early-access`.
2. `Self-host in minutes` (secondary) keeps the public Docker path.

The redundant hero GitHub action is removed because GitHub remains available
in the navigation. The proof line describes the desktop build as a private
preview rather than an anonymous download.

The final CTA becomes a compact early-access section with:

- one visibly labeled `email` input using native email validation and
  `autocomplete="email"`;
- a `Request access` submit button;
- Turnstile;
- an `aria-live` status region; and
- concise consent copy saying the address will receive access information,
  meaningful product releases, and occasional Backchannel news, with an
  unsubscribe option on every future update.

No modal, animation dependency, multi-step form, or optional profile fields are
introduced.

## Architecture

The existing `docs-site/worker.js` handles `POST /api/interest` before falling
back to static assets. The Worker receives the same-origin form request,
validates it, calls Turnstile Siteverify, and writes a prepared D1 statement.

The `INTEREST_DB` D1 binding points at a dedicated Backchannel interest
database. `TURNSTILE_SECRET_KEY` is a Worker secret. The public Turnstile site
key is committed in the static HTML because it is intentionally public; the
matching secret never leaves the Worker environment.

The D1 migration creates one table:

| Column | Purpose |
| --- | --- |
| `email` | Lowercased primary key; duplicate-safe list identity |
| `status` | `interested`, `invited`, `active`, or `unsubscribed` |
| `source` | Bounded acquisition source, initially `homepage` |
| `consent_version` | Version of the text the visitor accepted |
| `consent_at` | UTC consent timestamp |
| `created_at` | UTC first-submission timestamp |
| `invited_at` | Nullable UTC invite timestamp |
| `last_contacted_at` | Nullable UTC timestamp of the latest update |

Duplicate submissions return the same success result as new submissions and
do not silently reactivate an unsubscribed address.

## Security Boundary

- Accept only `POST` at the exact API path.
- Require a same-site `Origin` matching the request host in production.
- Reject oversized request bodies before parsing.
- Normalize and validate email server-side; cap all accepted strings.
- Validate every Turnstile token server-side and require the configured
  hostname and `interest` action.
- Bind values through a D1 prepared statement.
- Return generic success for both new and duplicate addresses to avoid email
  enumeration.
- Do not log or store the email, IP address, Turnstile token, or secret.
- Return `Cache-Control: no-store` on API responses.
- Keep D1 and the Turnstile secret available only to the Worker binding.
- Do not add a public read, export, invite, or status-update endpoint.

## Data Flow

1. Visitor follows the hero anchor and submits an email.
2. Native browser validation runs first; Turnstile supplies a short-lived
   token.
3. The Worker verifies origin, size, fields, Turnstile token, hostname, and
   action.
4. A prepared `INSERT ... ON CONFLICT DO NOTHING` stores the consent record.
5. The page reports the same success state for a new or existing address.
6. The owner uses D1 queries to mark invites/contact and uses Wrangler export
   when a mailing workflow is needed.

## Error Handling

- Invalid email: `400` with a safe field-level message.
- Invalid/expired Turnstile token: `400`; reset the widget so the visitor can
  retry.
- Wrong origin or oversized body: `403`/`413` without processing the record.
- D1 or Siteverify outage: `503` with a retry message; no false success.
- Unknown API route/method: `404`/`405` with no asset fallback.

## Operations and Documentation

Deployment documentation includes the one-time commands/dashboard steps to:

1. create the D1 database;
2. apply migrations locally and remotely;
3. create the hostname-restricted Turnstile widget;
4. store the Turnstile secret with Wrangler/Cloudflare;
5. query pending interests, mark invited records, and export the table; and
6. rotate the Turnstile secret without changing application code.

Production resource IDs belong in Wrangler configuration. Secret values never
enter Git, documentation, browser output, or test fixtures.

## Testing

- Node's built-in test runner covers method/path/origin validation, malformed
  requests, Turnstile failure, duplicate-safe inserts, D1 failure, and generic
  success responses with fake bindings.
- Worker tests use a fake Siteverify response and fake D1 binding; the deployed
  production smoke test exercises the hostname-restricted widget and real D1.
- Site build verifies the form survives the existing assembly pipeline.
- Browser checks cover desktop/mobile layout, keyboard focus, native email
  validation, status announcements, success, failure, and retry.

## Deliberate Scope Cuts

- No mailing-service synchronization until a real sending workflow is chosen.
- No double-opt-in email until a mail provider exists; this phase records the
  explicit on-page consent and preserves its version.
- No public unsubscribe endpoint until update emails are sent. Every future
  sender must include unsubscribe handling and write `unsubscribed` back to D1.
- No custom admin UI; D1's authenticated dashboard and Wrangler are enough.
