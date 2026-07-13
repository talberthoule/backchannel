## Product purpose

Explain Backchannel's self-hosted meeting analysis and let visitors request private desktop access or choose the public self-hosting path.

## Primary user

A privacy-conscious sales, discovery, or client-facing professional evaluating an AI meeting assistant on a desktop before using it in a call.

## Principles

1. **Truth before conversion.** Access language must match the private preview; a conversion is not worth a misleading promise.
2. **Ask for the minimum.** Collect only an email address and explicit consent for access and meaningful product updates.
3. **Privacy is visible, not implied.** State what is stored, what may be sent to providers, and what remains self-hosted.
4. **The product is the proof.** Prefer specific capabilities and real product screenshots over ornamental marketing patterns.
5. **One path, one promise.** Keep `Request early access` consistent from the hero through the completed request.

## Success metric for the surface

A visitor can distinguish private desktop access from public self-hosting and submit one valid, consented email without confusion, horizontal overflow, or keyboard and screen-reader barriers.

## Out of scope

- Does not send email or synchronize with a mailing service.
- Does not expose a public subscriber list, export, status, or administrative endpoint.
- Does not collect a name, company, IP address, or free-text message.
- Does not redesign the rest of the landing page.
- Does not change the public Docker Compose self-hosting path.

## Surface: Private admin console (2026-07-13)

### Product purpose

Let the single authorized Backchannel operator review early-access requests,
manage recipient identity and security, and manage release authorization in
separate, predictable work areas.

### Primary user

One trusted operator working repeatedly with download-recipient accounts.
Recipient identity is normalized email; operator identity remains external in
Cloudflare Access.

### Principles

1. Separate request, identity/security, and authorization ownership.
2. Keep security state explicit and destructive actions deliberate.
3. Prefer dense scan-and-detail workflows over wide command tables.
4. Update the affected record immediately after a successful command.
5. Preserve privacy: no identity or credential persistence, URLs, or logs.

### Success metric

At desktop and 320 CSS pixels, the operator can approve a request, inspect a
user's identity/security state, reset credentials or sessions, and edit grants
without password and authorization commands sharing a surface.

### Out of scope

- Admin accounts, roles, permissions, organizations, or generic policy rules.
- Recipient reactivation, deletion, email changes, merge, or bulk operations.
- Audit export, saved filters, server-side search, or pagination.
- A frontend framework, component library, client router, or second Worker.
