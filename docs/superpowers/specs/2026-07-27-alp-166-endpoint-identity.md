# ALP-166: Endpoint identity

- **Requested by:** shepherd lane w1:pP ("fable-root"), relaying the ALP-166 assignment
- **Performed by:** Claude Opus 5 (1M context) via Claude Code, lane w1
- **Date:** 2026-07-27
- **Scope:** Design only. One additive spec file. No code, schema, or git changes.

> **Provenance caveat.** The ALP-166 assignment comment was not readable from the
> authoring session: the Linear MCP tools were denied under `don't ask mode`, for
> the main session and for a dispatched subagent alike. This spec is therefore
> derived from the post-train source rather than from the brief. The problem
> statement below is what the code shows; if the brief scoped ALP-166 more
> narrowly (or at a different layer), treat the mismatched sections as surplus
> and reconcile before implementing.

Sources read at authoring time: `backend/app/services/custom_endpoints.py`,
`backend/app/services/llm_endpoint.py`, `backend/app/routers/privacy.py`,
`backend/app/services/local_fit.py` (admission call sites only).

## 1. What endpoint identity is today

`CustomEndpoint.id` is a slug minted from the endpoint's display name
(`_unique_slug` -> `slugify`, capped at `MAX_ENDPOINT_SLUG = 24`). That slug is
the table's primary key, and it is embedded in every model id the endpoint
exposes:

```
endpoint:<endpoint slug>:<wire model name>
```

Those model ids are not ephemeral. They are persisted in
`agent_configs.model_id` (varchar(160)) and in `session_agent_overrides`, and
they are handed to the frontend pickers through `to_dict` and `endpoint_models`.

So the slug is a durable, cross-table, user-selected foreign key that was
derived from a mutable display string. Every finding below follows from that
one sentence.

## 2. Findings

### F1 - Identity is minted from a mutable name, then frozen

`update_endpoint` (`custom_endpoints.py:262-301`) assigns `endpoint.name` but
never `endpoint.id`. That is the right call - rewriting the id would orphan every
saved `model_id` - but the consequence is permanent drift. An endpoint created as
"LM Studio" and later renamed "Lab box" keeps serving ids that read
`endpoint:lm-studio:...`. The picker shows one name; the stored configuration,
the logs, and any exported artifact show another.

Severity: cosmetic, but it is the reason F2 is surprising rather than obvious.

### F2 - Freed slugs are recycled, so a model id can silently rebind

`_unique_slug` (`custom_endpoints.py:219-226`) probes only for a *live* row:

```python
while await db.get(CustomEndpoint, slug) is not None:
```

`delete_endpoint` (`:304-307`) is a bare `db.delete`. So the sequence

1. endpoint "LM Studio" exists, slug `lm-studio`, agents point at
   `endpoint:lm-studio:llama3`
2. operator deletes it
3. operator later adds an unrelated server, also named "LM Studio"

issues the slug `lm-studio` a second time. Every agent still holding
`endpoint:lm-studio:llama3` now resolves - with no error and no log line - to a
different host, a different key, and possibly a different privacy class.

This is the sharpest correctness issue in the area, because the existing guard
cannot fire. `_from_target` (`llm_endpoint.py:133-144`) raises
`EndpointUnavailable` only when the row is missing or disabled; here the row
exists and is enabled. The stale reference is indistinguishable from a live one.

Severity: silent misrouting of model traffic. Under Privacy First this can also
be a perimeter break (see F3).

### F3 - The privacy class of a stable id is mutable

`is_on_prem` is recomputed from `base_url` on every read and never stored -
`to_dict:201`, `_registry_entry:359`, `resolve_target:431`. Privacy First
admission filters live on the resulting `runs_locally`
(`routers/privacy.py:19`, `local_fit.py:474`, `local_fit.py:591`).

Nothing gates a base-URL edit against that boundary. Repointing an endpoint from
`http://localhost:1234/v1` to a public proxy flips a model the operator vetted as
on-prem into an off-prem model, under an unchanged model id, with no
re-verification and no notice to any agent already pinned to it.

There is a useful precedent one function over: `update_endpoint:285-290` already
treats a base-URL change as invalidating, clearing `last_status`, `last_error`,
and `last_checked_at`. It invalidates the *reachability* verdict but not the
*privacy* verdict - and the privacy verdict is the more consequential of the two.

Severity: transcript and prompt text can leave the perimeter under an identity
that was approved while it pointed inward.

### F4 - Truncation makes the collision suffix unsound at the margin

The collision path builds `f"{base[:MAX_ENDPOINT_SLUG - 2]}-{suffix}"`
(`custom_endpoints.py:224`). Two distinct names sharing a 22-character prefix
converge on the same base, which is fine - the loop terminates. But `suffix`
climbs `2, 3, ... 10, 11`, and at two digits the result is 25 characters, one
over `MAX_ENDPOINT_SLUG`. Nothing enforces the cap after the suffix is appended.

Severity: low. Requires 10+ endpoints with a shared 22-character name prefix.

### F5 - Deletion orphans references at runtime rather than at edit time

Because `delete_endpoint` neither blocks nor rewrites referring agents, an agent
pointed at a deleted endpoint keeps an unresolvable `model_id` and fails on its
next call with `EndpointUnavailable`. The message is well written and actionable.
The *timing* is the problem: the operator learns during a live call, not while
editing Connections, which is the moment they still had the context to fix it.

Severity: operational. No data loss, but the failure lands in the worst place.

## 3. Design

The organizing principle: **an endpoint id must be a stable handle to a stable
set of properties.** Today it is a stable handle to a mutable set. Two changes
restore that, and they are independent.

### D1 - Retire slugs instead of freeing them (fixes F2 and F5)

Replace the hard delete with a tombstone: add a nullable `deleted_at` column to
`custom_endpoints`. `delete_endpoint` sets it and clears `api_key`; every listing
path (`list_endpoints`, and therefore `endpoint_models`, `to_dict`, the pickers)
filters tombstoned rows out.

Two properties fall out for free, which is why this is the recommended shape:

- `_unique_slug` needs **no change**. It already probes the primary key with
  `db.get`, which still finds the tombstoned row, so the slug is never reissued.
- `resolve_target` can distinguish "deleted" from "never existed" and return a
  precise error - which turns F5's late runtime failure into an accurate one, and
  makes a pre-delete blast-radius warning possible ("3 agents reference this
  endpoint").

Cost: one nullable column, one filter in `list_endpoints`, one branch in
`resolve_target`. No new table, no id-format change, no migration of existing
rows or existing `model_id` values.

*Alternative considered:* append a short random suffix at creation
(`lm-studio-a7f3`), making recycling statistically impossible with no schema
change at all. Cheaper, but it fixes only F2 - deletion still orphans silently -
and it makes ids less legible in logs. Prefer it only if the schema change is
unacceptable.

### D2 - Treat an on-prem boundary crossing as a re-verification event (fixes F3)

In `update_endpoint`, when `base_url` changes, compare `is_on_prem(old)` against
`is_on_prem(new)`. Both values are already in hand; no stored verdict is needed.

- Crossing **on-prem -> off-prem** while Privacy First is on: reject. The operator
  turns Privacy First off first, deliberately, or picks a different URL.
- Crossing **on-prem -> off-prem** while Privacy First is off: require an explicit
  confirmation flag on the request. Absent it, raise `EndpointError`, which the
  routers already translate to a 400 and the UI can render as a confirm dialog
  naming what changes.
- Crossing **off-prem -> on-prem**: allow silently. Tightening the perimeter needs
  no ceremony.

This deliberately extends the invalidation that `update_endpoint:285` already
performs for the probe result, rather than introducing a parallel mechanism.

### D3 - Cap the slug after suffixing (fixes F4)

Build the candidate, then truncate to `MAX_ENDPOINT_SLUG`, rather than reserving
a fixed two characters up front. One line.

### D4 - Present the slug as an identifier (mitigates F1)

No behavior change. Surface the endpoint's id in the Connections card as a
read-only "identifier" field, so the drift in F1 is visible rather than
surprising, and so operators reading a `model_id` in a log can map it back to the
endpoint they renamed. Documentation should stop implying the slug tracks the
name; it tracks the name *at creation*.

## 4. Out of scope

- Rewriting existing `endpoint:<slug>:<wire>` ids. D1 makes the current id format
  safe as it stands; a format migration would orphan saved agent configuration
  for no additional benefit.
- The `MAX_MODEL_ID_LENGTH` budget shared between endpoint name and wire model
  name. Real (long Ollama digests can exhaust it), but a separate concern from
  identity.
- The deliberate strict/lenient split between `endpoint_model_entry` and
  `resolve_target`. Documented at `custom_endpoints.py:393-402` and correct.

## 5. Open questions for the brief

1. Does ALP-166 cover F3, or is the Privacy First boundary a separate issue? It
   is identity-adjacent rather than identity proper, and D2 is separable from D1.
2. Is a schema change (D1's `deleted_at`) acceptable in this issue's scope, or
   should the no-migration alternative be taken instead?
3. Should pre-delete blast-radius reporting count `session_agent_overrides` as
   well as `agent_configs`, or only the latter?
