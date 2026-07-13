# Admin Identity, Security, and Authorization - Design

Date: 2026-07-13

Status: Approved (design presented and user directed continuation)

Branch: `agent/alp-71-admin-identity`

Linear: `ALP-71`

## Goal

Expand `admin.backchannel.page` from one overloaded early-access table into a
modular operator console. The first expansion covers release-recipient users,
identity lifecycle, password and session security, and release authorization.

Identity and authorization must be separate in the interface, API, and D1
read/write paths. Password commands must never share a surface with release
grants. Existing Cloudflare Access protection, exact operator authorization,
one-time credentials, recipient downloads, and release-access security
contracts remain intact.

## Scope and user definition

In this phase, a **user** is a recipient identity for
`downloads.backchannel.page`. The identity is still keyed by normalized email
and originates from an approved early-access request.

The sole admin operator remains external to this model. Cloudflare Access and
the Worker's exact `ADMIN_EMAIL` comparison continue to authenticate and
authorize that operator. This phase does not add admin accounts, roles,
permissions, organizations, or generic RBAC.

## Existing foundation

Production `master` already provides:

- a public Turnstile-protected interest form;
- an Access-protected admin hostname with independent Worker verification;
- D1 release accounts, password material, sessions, version grants, and audit
  events;
- atomic approve, reject, grant, reset-password, and revoke mutations;
- a one-time credential dialog;
- a recipient login, forced-password-change, release catalog, and private R2
  downloads; and
- 118 passing docs-site tests.

The current admin page joins consent, identity, password state, grants, and all
commands into one 11-column row. The backend mirrors part of that coupling by
storing `include_latest` beside password fields in `release_accounts` and by
grouping every operator mutation below `/api/admin/access/*`.

## Design decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Managed identities | Download-portal recipients only | Matches the implemented D1 boundary without inventing an admin account system |
| Admin structure | Shared static shell with Early access, Users, and Authorization routes | Gives each responsibility a durable destination and leaves room for later modules |
| Frontend stack | Existing HTML, CSS, and browser ES modules | Reuses the deployed stack; no framework or build dependency is needed |
| User workflow | Searchable list plus focused detail workspace | Supports scanning many users and safe commands without a very wide table |
| Identity ownership | Users route | Account state and lifecycle are identity concerns |
| Security ownership | Users route, separate Security section | Passwords and sessions belong to the user but never to Authorization |
| Authorization ownership | Authorization route | Latest and historical release access are managed independently |
| Initial policy | Approval creates the default Latest policy atomically | Preserves a usable account and the current safe transaction boundary without placing a grant editor in approval |
| Authorization storage | New `release_access_policies` table plus existing version grants | Removes `include_latest` from active identity reads/writes with the smallest safe migration |
| Operator authorization | Existing Access JWT plus exact `ADMIN_EMAIL` | A generic role system has no current consumer |
| Motion | Hover/focus and immediate state changes only | This is a high-frequency operational tool where speed is the feature |

## Information architecture

The private hostname recognizes these page routes:

```text
/                 Users (default)
/early-access     Request and consent review
/users            Identity and security management
/authorization    Release grant management
```

All routes serve the same protected HTML shell. Navigation uses normal links,
not a client router. A small bootstrap module selects and imports the matching
route module from `location.pathname`. This keeps deep links and browser
navigation native while avoiding repeated page chrome.

The static module boundary is:

```text
site/admin/index.html              shared semantic shell and dialogs
site/admin/admin.css               shell and route styles
site/admin/admin.js                route selection and shell state
site/admin/admin-core.js           safe DOM, fetch, format, dialog helpers
site/admin/early-access.js         request queue
site/admin/users.js                identity and security
site/admin/authorization.js        grant management
```

This is the complete modularity layer. No component framework, plugin system,
registry, or generic page-definition abstraction is added.

## Shared admin shell

Desktop uses a restrained 208-pixel navigation rail and a full-width work
area. The rail contains the Backchannel identity, `Private admin` state, and
the three destinations. The active destination uses the existing accent once;
inactive navigation remains neutral.

Below 760 pixels, the rail becomes a horizontally scrollable route tab row.
Below 640 pixels, list and detail views display one at a time. Selecting a row
opens its detail view; a visible Back command returns to the list. No essential
mobile workflow depends on a 1,680-pixel table or horizontal page scrolling.

The page header contains:

- route title and concise scope description;
- a result count or selected-user context;
- last-refreshed time;
- Refresh; and
- at most one route-specific primary command.

The visual language stays operational: existing neutral tokens, one green
accent, hairline borders, restrained shadows, tabular numbers, 6-8 pixel
radii, 44-pixel targets, and no decorative cards or animation.

## Early access route

Early access owns request and consent review only.

The queue exposes:

- email;
- interest status;
- source;
- requested time;
- consent time and version;
- release decision; and
- Approve or Reject.

It does not show account state, password state, sessions, Latest, versions,
Edit grants, Reset password, or Revoke.

### Approval

Approve uses one labelled native confirmation dialog. It does not contain a
grant editor. On confirmation, one D1 batch:

1. creates the release identity with a temporary password;
2. creates its default Latest authorization policy;
3. marks the request approved/active; and
4. records the approval event.

The response contains the one-time identity credential only. The credential
dialog supports Copy and Save, clears plaintext on close/pagehide, and offers
plain navigation links to Users and Authorization after the credential is
handled. The credential text does not enumerate editable grants.

Reject changes only the request decision and retains the consent record.

## Users route

Users owns recipient identity and security. It contains no release names,
Latest state, version count, or grant controls.

### Directory

The directory provides client-side search over the bounded loaded result set.
It displays:

- email;
- identity state (`Active` or `Revoked`);
- password state (`Temporary`, `Permanent`, or `Expired`);
- active session count; and
- last security change.

Search is case-insensitive and matches normalized email. A server-side search
or pagination contract is deferred until observed account volume makes the
single bounded response unsuitable.

### Detail workspace

Selecting a user opens two unframed sections.

**Identity** shows email, originating request time/source, approval time,
state, and revocation time. Revoke identity lives here because it changes the
account lifecycle. A labelled destructive dialog explains that active
sessions will end while request and audit history remain.

**Security** shows password state, temporary-password expiry, last password
change, active session count, and the newest session expiry. It owns:

- Reset password;
- Sign out all sessions; and
- the one-time credential dialog returned by reset.

Reset rotates the password, requires a new password change, and deletes all
sessions atomically. Sign out all sessions deletes sessions without changing
the password or account state.

Reactivation is deliberately absent. Reset password must not reactivate a
revoked identity. A later explicit reactivation workflow must define its own
credential and authorization review before it is added.

## Authorization route

Authorization owns release entitlement policy. It contains no password state,
temporary expiry, session data, Approve, Reject, Reset password, Sign out, or
Revoke command.

### Directory

The directory provides client-side search and displays:

- email;
- account state;
- Latest enabled/disabled; and
- historical-version count.

### Grant editor

Selecting a user opens one focused editor with:

- a Latest toggle;
- the trusted release catalog as historical-version checkboxes;
- current selection summary; and
- Save grants.

At least Latest or one explicit version is required. Saving replaces the
complete policy and explicit-version set in one D1 batch and records one grant
event. Revoked accounts remain visible for audit context, but their editor is
read-only and explains that identity state must be resolved before grants can
change.

If the R2 catalog is unavailable, existing policy remains visible while all
grant mutations are disabled. The UI never guesses versions from saved rows.

## API boundaries

Every admin request still passes Access JWT and exact-email authorization
before route dispatch or body parsing. Emails remain in JSON request bodies,
never URL paths or query strings.

### Read endpoints

```text
GET /api/admin/interests
GET /api/admin/users
GET /api/admin/authorization
GET /api/admin/releases
```

`/api/admin/interests` returns only request, consent, and decision fields.

`/api/admin/users` returns identity and security fields:

```json
{
  "items": [
    {
      "email": "recipient@example.com",
      "state": "active",
      "source": "homepage",
      "requested_at": "2026-07-13 12:00:00",
      "approved_at": "2026-07-13 12:10:00",
      "must_change_password": true,
      "password_expires_at": "2026-07-16 12:10:00",
      "password_changed_at": null,
      "revoked_at": null,
      "active_session_count": 1,
      "latest_session_expires_at": "2026-07-13 12:40:00"
    }
  ]
}
```

`/api/admin/authorization` returns authorization fields only:

```json
{
  "items": [
    {
      "email": "recipient@example.com",
      "account_state": "active",
      "include_latest": true,
      "versions": ["v0.2.1"],
      "updated_at": "2026-07-13 12:15:00"
    }
  ]
}
```

### Mutation endpoints

```text
POST /api/admin/interests/approve
POST /api/admin/interests/reject
POST /api/admin/users/reset-password
POST /api/admin/users/sign-out
POST /api/admin/users/revoke
PUT  /api/admin/authorization/grants
```

The old `/api/admin/access/*` routes are removed when the matching admin
assets and Worker deploy together. They have no public or third-party client.
Keeping aliases would preserve the conceptual coupling and duplicate tests
without a compatibility requirement.

Mutation responses return the updated route-specific record when it is safe
to do so. The browser patches the current list/detail state immediately and
announces success; it does not tell the operator to Refresh.

## D1 authorization separation

Migration `0003_release_access_policies.sql` adds:

```sql
CREATE TABLE release_access_policies (
  email TEXT PRIMARY KEY COLLATE NOCASE,
  include_latest INTEGER NOT NULL DEFAULT 1
    CHECK (include_latest IN (0, 1)),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (email) REFERENCES release_accounts(email) ON DELETE CASCADE
);

INSERT INTO release_access_policies (email, include_latest, updated_at)
SELECT email, include_latest, approved_at FROM release_accounts;
```

Explicit versions remain in `release_account_versions`. All active Worker
reads and writes use `release_access_policies` plus
`release_account_versions`. `release_accounts.include_latest` remains as an
unused legacy column because rebuilding the table solely to remove it adds
migration risk without changing behavior. Tests make accidental reuse fail.

Account deletion continues to cascade policy, version, and session rows while
retaining audit events.

## Security corrections

Two current defects are fixed as part of the security surface:

1. Forced password change derives and compares the proposed password against
   the current temporary credential. Reusing the temporary password returns a
   bounded validation error and does not rotate the session.
2. Logout reports success only after D1 deletes the presented session. If D1
   deletion fails, the Worker returns a generic retryable service error and
   retains the cookie so the browser can retry rather than orphaning a valid
   server session.

All existing boundaries remain:

- exact public/admin/download hostname allowlist;
- disabled `workers.dev` and preview URLs;
- exact Origin, JSON media type, strict UTF-8, and streamed 8 KiB mutation
  bodies;
- prepared D1 statements and atomic batches;
- hashed passwords and session tokens only;
- generic authentication and service errors;
- no credentials, identities, grants, Access assertions, hashes, salts,
  tokens, cookies, D1 rows, or R2 bodies in logs; and
- no-store, self-only CSP, no-referrer, nosniff, and frame-denial headers.

## State and error contract

Each route implements:

- loading with `aria-busy` and stable dimensions;
- empty state with a route-specific explanation;
- loaded list and no-selection detail state;
- selected detail state;
- mutation-in-progress with only the relevant controls disabled;
- inline validation without clearing valid selections;
- immediate success announcement and local record update;
- recoverable fetch/mutation error with Retry; and
- degraded catalog state that preserves identity/security usability while
  disabling only authorization changes.

Unknown admin page and API routes remain private no-store `404` responses.
Missing Access, D1, or R2 configuration fails closed. D1 failures do not leak
SQL, bindings, rows, or internal exception details.

## Accessibility and responsive behavior

- Navigation uses semantic links with `aria-current="page"`.
- Each route has one `h1`; list and detail regions have labelled `h2`
  headings.
- Search inputs have persistent labels and a result-count live region.
- Lists use semantic tables on desktop and preserve header association.
- Below 640 pixels, table rows reflow into labelled vertical fields; data is
  neither hidden nor dependent on horizontal scrolling.
- Mobile list/detail switching moves focus to the detail heading and restores
  it to the originating row on Back.
- Native dialogs have labelled headings, descriptive text, Cancel/Escape,
  focus containment, and focus restoration.
- Destructive dialogs name the affected action and use verb-specific buttons.
- Status never relies on color alone.
- All controls remain at least 44 pixels and expose visible keyboard focus.
- High-frequency list selection and form input do not animate.
- Existing dark mode, reduced-motion, and forced-colors behavior remains.
- Text fits at 320 CSS pixels without page-level horizontal overflow.

## Testing and verification

Node's built-in test runner covers:

- migration creation, backfill, constraints, foreign keys, cascades, and
  absence of active Worker references to the legacy Latest column;
- separated interest, user/security, and authorization response shapes;
- route ownership and removal of `/api/admin/access/*`;
- authorization before mutation parsing;
- atomic approval with default Latest policy and no editable grant input;
- atomic password reset, session sign-out, revoke, and grant replacement;
- proposed-password comparison and temporary-password reuse rejection;
- logout D1 failure returning retryable failure without clearing the cookie;
- revoked identity behavior and read-only authorization state;
- safe admin DOM construction with no HTML insertion, browser persistence,
  cookies, console logging, or embedded Access configuration;
- route navigation, active state, loading/empty/error/degraded states;
- command separation: password/session commands absent from Authorization and
  grant commands absent from Users/Early access;
- native dialog labels, cancellation, plaintext clearing, and focus restore;
  and
- responsive shell and mobile list/detail contracts.

Verification commands:

```text
cd docs-site
node --test *.test.js
npm run build

cd ..
C:/Users/thoule/.local/bin/sentrux.exe check .
C:/Users/thoule/.local/bin/sentrux.exe gate .
```

Visual verification uses the built admin shell with deterministic mocked
responses at desktop and 320-pixel mobile widths. It checks page framing,
nonblank content, no overlap or clipping, keyboard navigation, focus return,
dark mode, reduced motion, and forced colors.

## Rollout

1. Apply migration 0003 to the preview D1 database.
2. Deploy the Worker and all admin shell modules together.
3. Verify Early access approve/reject, one-time credentials, Users security
   actions, and Authorization grant replacement with test recipients.
4. Confirm recipient login, forced password change, release visibility,
   session sign-out, revocation, and downloads remain correct.
5. Apply the migration and deploy to production.
6. Keep the previous Worker deployment available only for rollback before the
   first production grant mutation. After the new Worker writes policy state,
   the legacy account column may be stale; recovery then requires a forward
   fix or an explicit policy-to-legacy data sync before rollback.

## Deliberate exclusions

- Admin identities, teams, roles, permissions, or a generic policy engine.
- Recipient creation without an early-access request.
- Reactivation, deletion, email change, account merge, or bulk actions.
- Per-device session metadata, IP tracking, location, user-agent collection,
  or device trust.
- Audit-event UI, export, saved filters, server-side search, or pagination.
- Email delivery, password-recovery email, mailing-provider integration, or
  notification preferences.
- A frontend framework, component library, icon dependency, client router,
  second Worker, or separate admin service.
- Changes to the self-hosted Backchannel application's local Admin panel or
  PostgreSQL schema.

These additions require observed operational need or a separate approved
design. The current work establishes the smallest durable boundary: requests,
identity/security, and authorization are independently understandable and
testable without inventing a general identity platform.
