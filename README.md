# Frontdesk

Support tickets for Arvo Systems. The employer’s original Hiring Test PDF supplies the task; [Frontdesk Hiring Test Task Brief and Build Plan.md](Frontdesk%20Hiring%20Test%20Task%20Brief%20and%20Build%20Plan.md) records the derived build plan. Subsequent explicit user corrections take precedence over its conflicting examples. This README records implementation decisions, not additional requirements.

## Current status

The backend, responsive agent UI, customer-safe conversation page, representative demo data and automatic sweep worker are implemented. PostgreSQL integration checks and a local browser walkthrough pass. Render/Docker deployment and GitHub CI configurations are included. No public hosting or repository URL has been provisioned yet; GitHub and Render account connections are pending.

## Run locally

Requires Python 3.12+, uv, and PostgreSQL (or Docker Compose). From this folder:

```sh
uv sync --locked
cp .env.example .env
# Edit .env: replace both token placeholders with different random values.
set -a; . ./.env; set +a
docker compose up -d --wait db
TEST_DATABASE_URL="$DATABASE_URL" uv run pytest -q
uv run python -m scripts.start
```

`FRONTDESK_SEED_DEMO=true` in the example creates four representative synthetic tickets once. The startup command migrates, optionally provisions a restricted runtime role, seeds demo cases and starts the web app. Open `http://127.0.0.1:8000`, enter your `FRONTDESK_AGENT_TOKEN`, and start as Meera. Browser credentials are held in tab-scoped session storage and cleared by Sign out. The local preview created by Codex uses the intentionally local-only demo key `frontdesk-local-demo`; do not use that key on a public deployment.

With an existing PostgreSQL instance, set its `DATABASE_URL` and omit the Docker command. Set `FRONTDESK_DB_PASSWORD` to enable restricted-role provisioning; this requires a migration connection with role-administration privileges. Production bootstrap requires it on Render. Database credentials are not printed or sent to the browser. `/docs` provides the API explorer. Dependencies are pinned in `uv.lock`.

Migrations run once each in a transaction with an advisory lock. Demo seeding is idempotent and should run only in a demo environment. Synthetic tickets have historical SLA start times and service operation times; their messages/events are inserted now and retain actual server insertion timestamps. The timeline therefore shows when demo records were seeded, not a fabricated historical audit timestamp.

Database tests require `TEST_DATABASE_URL` and permission to create schemas. API tests use committed temporary schemas for independent parallel connections; teardown drops only uniquely named test schemas. Schema tests use rolled-back transactions. Integration tests explicitly skip without that variable; checkpoint verification supplied it and skipped nothing.

## Using the screen

Select My tickets, Unassigned or All tickets. Search by subject, email or ticket ID and choose an active/completed filter. Late tickets sort first. Claim an unassigned ticket before posting a public reply. The reply box defaults to Public; Internal note switches to an amber team-only mode. Status and priority controls sit above the conversation. Activity timeline shows every mutation, including priority deadline snapshots and completed-cycle breaches.

Create a ticket with New ticket. Simulate a customer reply from the ticket action, or open Customer view in a separate tab; the customer page cannot load agent notes or agent timelines. Resolving a ticket enables customer reopening. The customer view can also download the allowlisted CSV. Drafts remain in memory while the ticket stays selected; changing tickets discards an unsent draft.

## Deploy

`Dockerfile` runs one FastAPI instance serving both the static UI and API. `render.yaml` declares a free web service and PostgreSQL database, generated secrets, startup demo data and health checking. The container starts with administrator DB credentials for migrations, provisions `frontdesk_app`, and then switches requests and the sweep worker to that restricted role.

1. Publish this repository to GitHub and connect it to Render as a Blueprint using `render.yaml`.
2. Confirm the generated secrets in the Render dashboard. Keep the migration DB credentials out of browser/client configuration. Supply the generated agent key privately to the reviewer.
3. Verify the deployed `/health`, sign into the UI and repeat the manual workflow below.
4. For automatic sweeps while the free instance is asleep, configure GitHub repository secrets `FRONTDESK_BASE_URL` (the HTTPS app URL) and `FRONTDESK_SWEEP_TOKEN` (the same secret as Render). The included scheduled workflow calls the sweep every 15 minutes; `workflow_dispatch` supports manual triggering. GitHub schedule execution may be delayed and is not an exact timer.
5. Confirm hosted tests and the first scheduled sweep succeed. Record the actual deployment and database expiry dates, and keep the service available for at least seven days after submission.

The built-in sweep runs immediately on application startup and every 60 seconds while the process is alive; `FRONTDESK_SWEEP_INTERVAL_SECONDS=0` disables it. Independent workers coordinate through database row locks. A failure rolls back the sweep and retries next interval. **Free Render services can sleep after 15 idle minutes and free databases expire after 30 days**, so the in-process worker alone cannot guarantee scheduled execution while asleep. See [Render free-tier documentation](https://render.com/docs/free). On wake, the startup sweep catches up; configure the external workflow to cover idle periods. Do not promise exact sweep timing or one-week uptime before verifying the deployed service. The account connections, Docker build and hosted workflows are not yet verified.

## Manual browser verification

On the deployed URL: create a ticket; open it as two different agents in separate tabs; claim from one then attempt the stale claim from the other; confirm the loser sees the owner's name and cannot reply. Send a public reply and unique-marker internal note, switch to customer view, and verify the marker is absent from the page and CSV. Enter Waiting, reply as the customer, verify Open and the resumed deadline. Change priority, inspect the timeline's old/new deadlines, resolve, and reopen to confirm cycle two. The automated PostgreSQL tests cover exact working-time boundaries and concurrent races that are harder to reproduce manually.

## Architecture

Buildless HTML/CSS/JavaScript served from FastAPI and PostgreSQL, with plain SQL migrations and a pure business-time module. Serving the UI and API together avoids a second hosting service and cross-origin configuration. Callers supply DB holiday dates, configured priority targets, stored pause intervals, and an explicit clock for active pauses. Production operation times come from PostgreSQL; tests inject the service clock. Each request commits its mutation and audit events together before returning a successful response. Row locks serialize ticket mutations, atomic conditional UPDATE handles claims, and `FOR UPDATE SKIP LOCKED` coordinates parallel sweeps. Public messages and private notes occupy separate tables; customer views and CSV use explicit field allowlists. Agent queues include SLA fields and place currently late tickets first.

## Decisions

- **Working calendar and arrivals:** Asia/Kolkata, Monday–Friday, 09:30 inclusive to 18:30 exclusive, excluding DB holidays. There is no intake cutoff. Arrivals inside a window start immediately; arrivals outside it start at the next opening. Existing allowances carry into subsequent working windows. An 18:15 arrival uses 15 minutes before close, leaving 105 of its 120 reply minutes; the target is **11:15 next working day**, not 11:45. The Saturday 11:00 arrival starts Monday 09:30 unless Monday is a holiday. The latest clarification supersedes the source brief's Friday example.
- **Urgent edge:** resolution is due at 18:30 on the effective start day. An 18:15 urgent arrival gets only 15 minutes for resolution. This harsh edge is deliberate and is not special-cased. A Friday medium ticket is not late Sunday; an urgent Friday ticket can be late Sunday because its resolution deadline expired Friday.
- **Targets:** `sla_policies` contains urgent 120-minute first reply / end-of-start-day resolution; medium 270/1620 minutes; small 540/2700 minutes. One working day is 540 minutes. Urgent resolution is represented by a null duration and the explicit end-of-start-day rule.
- **Priority changes:** recalculate against the current resolution cycle's original effective start using the new targets, retaining that cycle's pauses. The original ticket start still anchors first reply. A stricter target can make the ticket immediately late. Restarting at priority change would hide the customer's elapsed wait. `priority_changed` records both priorities, both first-reply deadlines, both resolution deadlines, and the cycle number. Completed tickets must reopen before priority changes.
- **Pauses:** only resolution pauses. Waiting creates a new interval; leaving waiting closes that interval once. Customer reply resumes waiting tickets automatically. Repeated status selection is a no-op. An urgent mid-day pause can extend its deadline beyond the initial day. A pause beginning after the deadline cannot erase a breach. The calculator rejects reversed and overlapping intervals, requires an explicit clock for an open pause, and requires the open pause to be last. Completed cycles retain their pause history; later cycles use only their own intervals.
- **Claim ownership:** an agent must claim a ticket before posting a public reply; only its assignee can reply publicly. A losing claimant receives 409 even if they bypass the claim UI and call the messages endpoint. Internal collaboration notes remain available to authenticated agents. Customer replies use the customer capability.
- **First reply:** the first public agent reply sets `first_replied_at` with an atomic null predicate. Internal notes, customer replies and later agent replies cannot set/reset it. Its clock never pauses. Reopen preserves that original first-reply record. `first_reply_breached` exposes the original obligation's result; `is_late` describes current actionable lateness: current resolution breach, or an outstanding first reply in cycle one. Historical first-cycle breaches do not make a new resolution cycle instantly late.
- **Reopen cycles:** customers can reopen resolved tickets through exactly 2700 working minutes after resolution, inclusive. At 2701 minutes, the request creates a new ticket with `previous_ticket_id` pointing to the old ticket. An allowed reopen inserts a fresh resolution cycle using the same priority and targets, starting at reopen time inside working hours or the next opening outside them. The ticket's original `start_at` and first reply are preserved. At resolution/auto-close, the completed cycle's deadline and breach result are stored and written into an immutable event. Reopening inserts a new cycle and event; it never edits old cycle snapshots or events. Concurrent reopen requests create only one new cycle; the other gets 409. Customer contact on auto-closed tickets creates a linked new ticket. Expired-window new-ticket requests are not deduplicated across retries.
- **Auto-close:** an uninterrupted wait becomes eligible at 2700 working minutes, inclusive. `POST /admin/sweep` locks eligible waiting tickets, closes the pause/cycle, and records one `auto_closed` event per ticket with actor `system`. A separate system `resumed` event records the end of the pause interval at closure. Repeated and concurrent sweeps cannot duplicate a closure. The endpoint and application-owned background worker are implemented. A GitHub scheduled caller is provided for sleeping hosts; repository secrets and hosted execution remain pending publication.
- **Holiday verification:** all ten original 2026 seed dates were re-verified against the public-office [GAD 2026 notification, pp.2–3](https://gad.kerala.gov.in/sites/default/files/inline-files/public-holidays-2026_0.pdf). Missing dates from its 22-entry list were added. **Original 2026 dates that could not be verified: none.** The public-office 2027 list and its separately listed weekend festivals were checked against the official [GAD Diary 2027, printed pp.181–182](https://gad.kerala.gov.in/sites/default/files/inline-files/diary27.pdf). The diary is labeled a first draft, and moon-dependent dates may change. Bank-only April 1, restricted community holidays and Delhi-only holidays are excluded. All weekends are already non-working under this task's rules. These are baseline published lists, not a claim that later ad hoc government notices were exhaustively collected.
- **Unverified company holiday:** January 1, 2027 was not verified in GAD. It is explicitly seeded as a user-requested **company holiday**, not represented as a national/GAD holiday. Its DB source records that distinction.
- **Seed range safety:** any calendar operation that reaches past the last seeded holiday raises `CalendarRangeError`, including closed days and zero-duration calls. Currently that date is **December 25, 2027**. We do not infer holiday-free days through December 31. The API returns 503 with the affected date and extension instructions; failed mutations roll back. Extend DB seeds before calculating later dates.
- **Customer privacy:** private notes are separate from public messages. Customer serializers allow only named fields; customer CSV has its own allowlist and neutralizes spreadsheet formula prefixes. Customer endpoints do not expose events, notes, emails or access tokens. The audit writer accepts only event-specific metadata keys and never stores any message/note body. All customer-facing routes are tagged and enumerated by the endpoint-wide leak test, including customer reply and both reopen outcomes.
- **Audit:** PostgreSQL triggers reject event UPDATE, DELETE and TRUNCATE. An INSERT trigger replaces any supplied event timestamp with database server time. Mutation request schemas reject extra fields, including client timestamps. The events API is read-only and agent-authenticated. These controls do not stop a database owner from disabling triggers; the deployment bootstrap provisions a restricted application role without audit mutation privileges. No hash chain is implemented.
- **Demo auth:** agents use a shared `FRONTDESK_AGENT_TOKEN` as `Authorization: Bearer …` plus a seeded `X-Agent-Id` (1–9). This is the allowed demo shortcut, not individual production authentication. Customer requests use a UUID capability in `X-Customer-Token`; agents receive it when creating a ticket. Linked tickets retain the capability so the customer can access that ticket chain. Customers cannot select agent views. Sweep uses a different `FRONTDESK_SWEEP_TOKEN`. Missing configured secrets disable those protected operations. Keep capability tokens private; delivery, expiry and rotation are not implemented.

## API

| Method and path | Access | Behavior |
| --- | --- | --- |
| `POST /tickets` | Agent | Create ticket, first cycle and created event; return customer capability |
| `GET /tickets?assignee=me` | Agent | Queue; also supports `all` and `unassigned` |
| `GET /tickets/{id}` | Agent | Public thread, distinct internal notes and SLA |
| `GET /agents` | Agent | Seeded agent list |
| `POST /tickets/{id}/claim` | Agent | Atomic claim; 409 includes winning assignee |
| `POST /tickets/{id}/messages` | Agent | `body` plus `visibility`: public (default) or internal |
| `POST /tickets/{id}/notes` | Agent | Internal note convenience endpoint |
| `POST /tickets/{id}/status` | Agent | Open, waiting_on_customer or resolved |
| `POST /tickets/{id}/priority` | Agent | Recompute and log old/new deadlines |
| `GET /tickets/{id}/events` | Agent | Read-only timeline |
| `GET /customer/tickets` | Customer | Allowlisted ticket-chain list |
| `GET /customer/tickets/{id}` | Customer | Allowlisted public thread |
| `GET /export.csv` | Customer | Allowlisted ticket-chain CSV |
| `POST /tickets/{id}/customer-reply` | Customer | Public reply and resume waiting ticket |
| `POST /tickets/{id}/reopen` | Customer | 200: fresh cycle; 201: linked new ticket |
| `POST /admin/sweep` | Sweep secret | Idempotent auto-close |

To create a ticket after starting the server:

```sh
curl -s http://127.0.0.1:8000/tickets \
  -H "Authorization: Bearer $FRONTDESK_AGENT_TOKEN" -H 'X-Agent-Id: 1' \
  -H 'Content-Type: application/json' \
  -d '{"subject":"Checkout fails","customer_email":"customer@example.com","priority":"urgent"}'
```

## Validation checkpoints

Tests ran after each requested step, with real PostgreSQL for schema and integration checks:

| Step | Output |
| --- | --- |
| 1. Arrival rules | `30 passed` |
| 2. New reopen-cycle policy | `32 passed` |
| 3. Holiday seeds/range guard | `38 passed` |
| 4. Pause behavior | `42 passed` |
| a. Customer allowlists | `45 passed, 1 warning` |
| b. Privacy leak checks | `47 passed, 1 warning` |
| c. Atomic parallel claims | `51 passed, 1 warning` |
| d. Messages/status/priority | `59 passed, 1 warning` |
| e. Idempotent parallel sweeps | `63 passed, 1 warning` |
| f. Reopen endpoint/history | `68 passed, 1 warning` |

The warning was the installed Starlette test client's deprecated `httpx` fallback. The dev dependency has been changed to its declared `httpx2` dependency rather than suppressing the warning. Final expanded regression output is recorded after verification below.

Incident proof: `test_claims.py` fires independent parallel claims; `test_customer_api.py` checks a unique private marker across every tagged customer endpoint and all event payloads; `test_schema.py` checks PostgreSQL rejection of audit mutations and server-generated timestamps. `test_mutations.py`, `test_sweep.py` and `test_reopen.py` cover transactional lifecycle behavior and retained history. Pure edge cases live in `test_business_time.py`.

## What I did not finish — current checkpoint

The application is implemented locally. Public hosting, repository publication, hosted CI/scheduled-sweep execution and the final hosted browser pass remain pending GitHub/Render account access. A local container build was not run because Docker is not installed. No individual production authentication, token-delivery/rotation system, email integration, pagination, database connection pool or hash chain is implemented. The small demo scope prioritized incident protections and the working support workflow. Holiday seeds require extension beyond the guarded range. See [SUBMISSION.md](SUBMISSION.md) for the draft unfinished-work note and submission checklist.

Latest verification: **75 passed, zero skipped, zero warnings** against local PostgreSQL 17. JavaScript syntax checks passed. Browser verification covered ticket creation, a stale two-agent claim conflict, public reply, internal note, waiting, customer-triggered resume, priority change, resolution, fresh-cycle reopen and the timeline. Agent and customer layouts were inspected at 390px with no horizontal overflow. CSV payload safety is covered by API tests; native in-app-browser download completion was not confirmed. The runtime role was checked to have no superuser/create-database/create-role privileges and no UPDATE/DELETE access on events.
