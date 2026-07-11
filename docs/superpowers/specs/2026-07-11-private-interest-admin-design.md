# Private Interest Admin - Design

Date: 2026-07-11
Status: Approved

## Goal

Give one Backchannel operator a secure, read-only web page for reviewing the
early-access records already stored in Cloudflare D1. Keep the public landing
page and the self-hosted Backchannel application's unauthenticated local Admin
panel outside this security boundary.

Finish with the repository ready to build the Cloudflare site, Docker Compose
images, and portable Linux, macOS, and Windows desktop bundles. Publishing,
tagging, or changing installer visibility remains a separate release action.

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Admin location | `admin.backchannel.page` | A dedicated hostname gives Cloudflare Access one unambiguous protection boundary |
| Application host | Existing `docs-site` Cloudflare Worker | It already owns the D1 binding, public site assets, and deployment workflow |
| Identity provider | Cloudflare Access | Reuses managed login, session, and exact-email policy controls instead of owning passwords |
| Authorized operator | JWT `email` claim must equal the `ADMIN_EMAIL` Worker secret | Enforces the one-user requirement in code without committing the address |
| Defense in depth | Verify the Access JWT signature, issuer, audience, expiry, and email in the Worker | A missing or misrouted Access policy must not expose subscriber data |
| Data access | One read-only `GET /api/admin/interests` endpoint | The request is to render the stored data, not create an administrative workflow |
| UI | Static, accessible table with summary count and explicit states | No frontend framework or second application is needed for one read-only view |
| Linux distribution | `Backchannel-linux-x64.tar.gz` portable bundle | Matches the existing portable Windows/macOS packaging without adding DEB/RPM maintenance |
| Docker distribution | Validate source-built Compose images | The repository does not publish a container-registry image today |

## Architecture

The existing Worker continues to serve the public site and `POST
/api/interest` on `backchannel.page`. Requests for
`admin.backchannel.page` are routed to the same Worker but through a
Cloudflare Access self-hosted application whose Allow policy names one exact
email address.

The Worker recognizes only these private-host routes:

- `GET /` and the admin's static assets serve the private page.
- `GET /api/admin/interests` verifies the Access assertion and authorized
  email, then queries D1.
- Other private-host paths return a no-store `404`.

The public hostname does not serve the admin page or admin API. The existing
Backchannel product Admin panel remains unchanged because it is a local,
self-hosted surface without a user-authentication boundary and uses a separate
PostgreSQL database.

JWT verification uses Cloudflare Access's published JWKS and the existing
Workers runtime through the `jose` package. Deployment supplies:

- `ADMIN_EMAIL` as a Worker secret;
- `ACCESS_TEAM_DOMAIN` as a Worker secret; and
- `ACCESS_AUD` as a Worker secret.

No identity value, Access audience, or team domain is committed to Git.

## Data Contract

`GET /api/admin/interests` returns:

```json
{
  "items": [
    {
      "email": "person@example.com",
      "status": "interested",
      "source": "homepage",
      "consent_version": "2026-07-11",
      "consent_at": "2026-07-11 12:00:00",
      "created_at": "2026-07-11 12:00:00",
      "invited_at": null,
      "last_contacted_at": null
    }
  ]
}
```

The prepared D1 statement selects only the eight existing columns and orders
records by `created_at DESC`. There are no query parameters, mutation methods,
exports, joins, or new tables.

## Admin Experience

The private page uses the landing site's established visual tokens but adopts
a compact operator layout:

- Backchannel wordmark and `Early access` page title;
- total request count and last-refreshed time;
- a semantic table with Email, Status, Source, Requested, Consent, Invited,
  and Last contacted columns;
- native horizontal scrolling on narrow screens;
- visible loading rows, a concise empty state, and a retryable error state;
- a Refresh button with a visible keyboard focus state; and
- UTC timestamps rendered in the viewer's locale while retaining the original
  value in `datetime`/`title` attributes.

The page performs one same-origin fetch on load and on explicit refresh. It
does not store subscriber data in local storage, session storage, cookies, or
client logs.

## Security Boundary

- Protect the complete `admin.backchannel.page` hostname with a Cloudflare
  Access application and an exact-email Allow rule.
- Validate `Cf-Access-Jwt-Assertion` in the Worker using the configured issuer,
  audience, Cloudflare JWKS, and normal expiry checks.
- Compare the normalized JWT `email` claim to normalized `ADMIN_EMAIL` using
  exact equality.
- Fail closed when any binding, secret, token, claim, or verification step is
  missing or invalid.
- Require `GET` for the read endpoint and return `405` with `Allow: GET` for
  other methods.
- Use a prepared D1 statement with no caller-controlled SQL values.
- Return `Cache-Control: no-store` and a restrictive Content Security Policy
  on private HTML and API responses.
- Send `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and
  `X-Frame-Options: DENY` on the private page.
- Return generic authentication and service errors without token, identity,
  database, or stack details.
- Do not log subscriber records, Access tokens, or the configured admin email.
- Keep the existing public signup response duplicate-safe so the admin work
  does not introduce email enumeration.

## Data Flow

1. The operator opens `admin.backchannel.page`.
2. Cloudflare Access authenticates the operator and applies the exact-email
   Allow policy.
3. The Worker serves the private static page only after validating the Access
   JWT and `ADMIN_EMAIL` match.
4. The page requests `/api/admin/interests` on the same private hostname.
5. The Worker repeats JWT and one-user authorization, then reads D1 with a
   prepared statement.
6. The browser renders the returned records in a semantic table without
   persisting them.

## Error Handling

- Missing configuration: `503` generic unavailable response.
- Missing or invalid Access assertion: `401` generic unauthorized response.
- Valid assertion for another email: `403` generic forbidden response.
- Unsupported API method: `405` with `Allow: GET`.
- D1 failure: `503` generic retry message.
- Unknown private-host route: `404` without public asset fallback.
- Browser fetch failure: retain no stale rows, announce the error, and offer
  Refresh.

## Testing

Node's built-in test runner will cover:

- missing Access configuration and assertion;
- invalid signature/issuer/audience/expiry through an injected verifier;
- valid token for the wrong email;
- exact normalized email authorization;
- prepared D1 query and newest-first ordering;
- D1 failure without detail leakage;
- private/public hostname route isolation;
- no-store and private-page security headers;
- unsupported methods and unknown routes; and
- admin HTML semantics, states, and absence of committed secrets.

Build verification will cover the docs-site assembly, frontend production
build, backend and desktop unit suites, Compose configuration, backend and
frontend Docker image builds, workflow syntax, and the platform packaging
contract.

## Release-Build Readiness

The admin page is a Cloudflare site feature and is not embedded into the
self-hosted application binaries. Release readiness still covers all requested
distribution paths:

1. The site workflow builds the admin asset and Worker together.
2. Docker Compose continues to build the backend and frontend images from the
   checked-out source; no registry or auto-update mechanism is added.
3. The desktop release matrix retains Windows x64 and macOS arm64 and adds
   Linux x64.
4. Linux includes the PyInstaller Xorg backend and packages the one-directory
   bundle as `Backchannel-linux-x64.tar.gz` with executable bits preserved.
5. Workflow dispatch remains the non-publishing packaging check. A `v*` tag
   remains the only trigger that attaches artifacts to a GitHub release.
6. Release documentation names all three desktop assets and keeps private
   installer access unchanged.

The work stops before creating or pushing a version tag, deploying the Worker,
publishing release assets, changing repository visibility, or exposing private
downloads. Those actions require an explicit release decision and live
credentials.

## Deliberate Scope Cuts

- No status editing, invite workflow, export, search, pagination, or mailing
  provider integration.
- No admin-user table, password form, custom session cookie, recovery flow, or
  role system.
- No second Worker or frontend framework.
- No MSI, DMG, DEB, RPM, registry image, signing, notarization, or auto-update.
- No changes to the self-hosted Backchannel Admin panel.
