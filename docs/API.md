# API

| Method and path | Access | Behavior |
| --- | --- | --- |
| `POST /tickets` | Agent | `source`: `customer` (default, first-reply target) or `agent` (no first-reply target); return capability |
| `POST /customer/tickets` | Public intake | Create customer ticket with first-reply target; return capability; default limit 10 per resolved IP / 10 minutes |
| `GET /tickets?assignee=me` | Agent | Queue without customer capabilities; also supports `all` and `unassigned` |
| `GET /tickets/{id}` | Agent | Public thread, distinct internal notes and SLA; never contains customer_token |
| `POST /auth/login` | Public | Email/password; token, absolute expiry and agent; generic 401 or throttled 429 |
| `GET /auth/me` | Agent session | Current agent id/name |
| `POST /auth/logout` | Agent session | Revoke the current session |
| `GET /agents` | Agent | Seeded agent list |
| `POST /tickets/{id}/claim` | Agent | Atomic claim; own repeat is 200; other owner/inactive is 409 |
| `POST /tickets/{id}/reassign` | Agent | Current assignee transfers to an active agent; other agents receive 403; logs old/new; clocks unchanged |
| `POST /tickets/{id}/agent-reopen` | Agent | Same reopen/link rules as customer; agent actor |
| `POST /tickets/{id}/messages` | Agent | `body` plus `visibility`: public (default) or internal |
| `POST /tickets/{id}/notes` | Agent | Internal note convenience endpoint |
| `POST /tickets/{id}/status` | Agent | Current `version` required; Waiting also requires public `body`; stale version is 409 |
| `POST /tickets/{id}/priority` | Agent | Recompute and log old/new deadlines |
| `GET /tickets/{id}/customer-access` | Current assignee | Explicit customer-action capability; other agents receive 403 |
| `GET /tickets/{id}/events` | Agent | Read-only timeline |
| `GET /customer/tickets` | Customer | Allowlisted ticket-chain list |
| `GET /customer/tickets/{id}` | Customer | Allowlisted public thread |
| `GET /export.csv` | Customer | Allowlisted ticket-chain CSV |
| `POST /tickets/{id}/customer-reply` | Customer | Public reply; resume, reopen, or create linked ticket as needed |
| `POST /tickets/{id}/reopen` | Customer | 200: fresh cycle; 201: linked new ticket |
| `POST /admin/sweep` | Sweep secret | Idempotent auto-close |

To create a ticket after starting the server, obtain a session via `POST /auth/login` with JSON `email` and `password`, then use the returned token as `SESSION_TOKEN`:

```sh
curl -s http://127.0.0.1:8000/tickets \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"subject":"Checkout fails","customer_email":"customer@example.com","priority":"urgent"}'
```

## Request contracts

Message/note bodies preserve raw text, reject blank content and reject more than 10,000 characters. Validation errors omit submitted values. Read an agent ticket's `version` and send it with status changes, e.g. `{"status":"waiting_on_customer","body":"Which workspace?","version":1}`. A missing version is 422; a stale version is 409. Send `Idempotency-Key` (1–200 characters) on agent `/messages` or customer `/customer-reply`: the same actor, path and content within 24 hours returns the original 201 JSON response; reusing a live key for different content returns 409. Expired keys permit a new mutation. Retry protection includes replies that create linked tickets. Idempotency uses database server time, independent of SLA test clocks. Keys are scoped to the authenticated agent or customer capability. The runtime role is granted access to the idempotency table.

[README](../README.md) · [Decisions](DECISIONS.md)

## Wire and error behavior

All API errors use a `detail` envelope: a string for ordinary errors, a claim-conflict object with the owner, or a validation array with `loc`, `msg`, `type` (no submitted value). 401 requires credentials, 404 hides inaccessible customer IDs, 409 is a state/version/idempotency conflict, 422 rejects input, 429 is throttled with Retry-After, 503 is calendar-range or redacted database unavailability. Claim/reply ownership conflicts return 409; unauthorized reassignment returns 403. Bodies above 65,536 actual bytes return 413. Responses include X-Request-ID and non-static responses are private/no-store. Subject ≤300, email ≤320 with a basic non-whitespace local/domain-dot pattern (not deliverability verification), messages ≤10,000; strings containing U+0000 are invalid. IDs fit positive signed bigint. Unknown extra fields are forbidden. Wrong media/invalid JSON returns 422; trailing slashes use the framework's same-origin 307 normalization.

Bearer agent sessions never travel in a URL. Customer links deliberately use a UUID capability in a fragment, immediately remove it from the address bar and keep it in per-tab sessionStorage. Fragments are not sent to the HTTP server; no-referrer prevents onward referrer disclosure. Capabilities have no expiry/rotation, per the frozen decision. Every agent detail/list omits the capability. The separate customer-access endpoint requires the current assignee. Creating an agent ticket returns the creator its initial capability. No route can overwrite it.
