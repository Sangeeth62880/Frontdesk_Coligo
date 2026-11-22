# Frontdesk

Support tickets for Arvo Systems. The employer’s original Hiring Test PDF supplies the task; [Frontdesk Hiring Test Task Brief and Build Plan.md](Frontdesk%20Hiring%20Test%20Task%20Brief%20and%20Build%20Plan.md) records the derived build plan. Subsequent explicit user corrections take precedence over its conflicting examples. This README records implementation decisions, not additional requirements.

## Current status

The backend, responsive agent UI, customer-safe conversation page, representative demo data and automatic sweep worker are implemented. PostgreSQL integration checks and a local browser walkthrough pass. Render/Docker deployment and GitHub CI configurations are included. The repository is [Sangeeth62880/Frontdesk_Coligo](https://github.com/Sangeeth62880/Frontdesk_Coligo). The application is live at [frontdesk-spfe.onrender.com](https://frontdesk-spfe.onrender.com); hosted API and browser verification passed, and GitHub CI built the Docker image.

## Run locally

Requires Python 3.12+, uv, Node.js (renderer verification), and PostgreSQL (or Docker Compose). From this folder:

```sh
uv sync --locked
cp .env.example .env
# Edit .env: choose a demo password and a separate random sweep secret.
set -a; . ./.env; set +a
docker compose up -d --wait db
TEST_DATABASE_URL="$DATABASE_URL" uv run python -m scripts.verify
uv run python -m scripts.start
```

`FRONTDESK_SEED_DEMO=true` creates four representative synthetic tickets once and provisions Meera, Arun and Divya with the required `FRONTDESK_DEMO_PASSWORD` (there is no code default). Open `http://127.0.0.1:8000` and sign in with `meera@arvo.example`, `arun@arvo.example` or `divya@arvo.example` and that password. A muted hint appears only in demo mode. All nine agents have `firstname@arvo.example` addresses; the other six have no password until provisioned. Startup migrates, seeds using the administrator connection, optionally provisions a restricted runtime role, then serves requests with that role. Repeat seeds preserve existing passwords.

For a non-demo installation, set `FRONTDESK_SEED_DEMO=false` and provision each agent with the administrator database connection:

```sh
uv run python -m scripts.migrate
uv run python -m scripts.set_agent_password
```

The provisioning script reads the email and password from stdin (a hidden password prompt in a terminal), stores a salted scrypt hash, and revokes that agent's existing sessions. It takes no password command-line argument. Browser session tokens are held in tab-scoped session storage; Sign out revokes the current server session and clears that storage. Any API 401 clears the browser session and returns to the login form.

With an existing PostgreSQL instance, set its `DATABASE_URL` and omit the Docker command. Set `FRONTDESK_DB_PASSWORD` to enable restricted-role provisioning; this requires a migration connection with role-administration privileges. Production bootstrap requires it on Render. Database credentials are not printed or sent to the browser. `/docs` provides the API explorer. Dependencies are pinned in `uv.lock`.

Migrations run once each in a transaction with an advisory lock. Demo seeding is idempotent and should run only in a demo environment. Synthetic tickets have historical SLA start times and service operation times; their messages/events are inserted now and retain actual server insertion timestamps. The timeline therefore shows when demo records were seeded, not a fabricated historical audit timestamp.

Database tests require `TEST_DATABASE_URL` and permission to create schemas and temporary restricted roles (CREATEROLE); the runtime permission test removes its temporary role afterward. API tests use committed temporary schemas for independent parallel connections; teardown drops only uniquely named test schemas. Schema tests use rolled-back transactions. Integration tests explicitly skip without that variable; checkpoint verification supplied it and skipped nothing.

## Using the screen

Select My tickets, Unassigned or All tickets. Search by subject, email or ticket ID and choose an active/completed filter. Late tickets sort first. Use the dedicated Take this ticket button beside Assignee to claim an unassigned ticket before posting a public reply. The reply box defaults to Public; Internal note switches to an amber team-only mode. Status and priority controls sit above the conversation. Activity timeline shows every mutation, including priority deadline snapshots and completed-cycle breaches.

Create a ticket with New ticket. Source defaults to Customer request, including a first-reply target; select Agent-initiated to omit that target. Simulate a customer reply from the ticket action, or open Customer view in a separate tab; the customer page cannot load agent notes or agent timelines. Resolving a ticket enables customer and agent reopening. Selecting Waiting prompts for a public question, or sends the public draft in the composer, in the same transaction. The customer view can also download the allowlisted CSV. Drafts remain in memory while the ticket stays selected; changing tickets discards an unsent draft.

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
- **Pauses:** only resolution pauses. Waiting creates a new interval; leaving waiting closes that interval once. Customer reply resumes waiting tickets automatically. Repeated status selection is rejected. An urgent mid-day pause can extend its deadline beyond the initial day. A pause beginning after the deadline cannot erase a breach. The calculator rejects reversed and overlapping intervals, requires an explicit clock for an open pause, and requires the open pause to be last. Completed cycles retain their pause history; later cycles use only their own intervals.
- **Claim ownership:** an agent must claim a ticket before posting a public reply; only its assignee can reply publicly. A losing claimant receives 409 even if they bypass the claim UI and call the messages endpoint. Internal collaboration notes remain available to authenticated agents. Customer replies use the customer capability.
- **Late means either target breached:** `sla.breached_targets` identifies first reply, resolution, or both. Flags are retained permanently across priority changes and reopen cycles. Completed tickets freeze evaluation at completion: resolving before both deadlines never becomes late later. A new resolution cycle gets a new deadline while prior breach evidence remains visible.
- **Waiting requires a public question:** the status request must include a nonempty `body`, posted publicly by the assignee in that same transaction; missing body returns 422. Only resolution pauses. Notes never pause, resume, or satisfy first reply.
- **First reply and intake:** only the first public agent message satisfies first reply, anchored to creation's effective start, never claim. Customer messages and notes do not count. The Create a ticket form defaults Source to Customer request (`source=customer` on `POST /tickets`), which requires a first reply exactly like customer intake. Agent-initiated (`source=agent`) stores `first_reply_required=false` and a null `first_reply_due_at`; resolution still applies. Source is recorded in the creation event, while the actor remains the authenticated agent. Omitting source defaults to customer; linked-ticket/reopen behavior is unchanged. Customer intake is `POST /customer/tickets` and returns a new access capability.
- **Customer reply:** waiting resumes to open; open adds a plain message. Resolved through exactly 2700 working minutes reopens with a fresh resolution cycle and the same assignee. Later replies, and replies to closed tickets, create a linked ticket and put the message there. The old completed record stays untouched. The inclusive reopen boundary uses elapsed working minutes, so closed hours immediately after minute 2700 do not consume the window.
- **Agent reopen:** `POST /tickets/{id}/agent-reopen` (or requesting open from resolved) follows the same inclusive window and linked-ticket rule; its event names the agent. Priority changes on completed tickets return 409.
- **Claims:** claiming your own active ticket is 200 without another event. Other owners cause 409 including their name; resolved/closed tickets cause 409. Reassignment records old/new assignee and leaves all clocks untouched.
- **Status transitions:** open↔waiting, open→resolved, waiting→resolved, and resolved→open through reopen are allowed. Waiting/resolved→closed is reserved for the system (the implemented sweep closes eligible waiting tickets). Other requests, including selecting the same status, return 409. A waiting request without a question returns 422 first.
- **Auto-close:** only an uninterrupted waiting interval of at least 2700 working minutes qualifies. Row locks and transaction boundaries prevent duplicate close events. Ending the pause writes one `resumed` event; closure writes one `auto_closed` event with actor `system`.
- **Holiday verification:** all ten original 2026 seed dates were re-verified against the public-office [GAD 2026 notification, pp.2–3](https://gad.kerala.gov.in/sites/default/files/inline-files/public-holidays-2026_0.pdf). Missing dates from its 22-entry list were added. **Original 2026 dates that could not be verified: none.** The public-office 2027 list and its separately listed weekend festivals were checked against the official [GAD Diary 2027, printed pp.181–182](https://gad.kerala.gov.in/sites/default/files/inline-files/diary27.pdf). The diary is labeled a first draft, and moon-dependent dates may change. Bank-only April 1, restricted community holidays and Delhi-only holidays are excluded. All weekends are already non-working under this task's rules. These are baseline published lists, not a claim that later ad hoc government notices were exhaustively collected.
- **Unverified company holiday:** January 1, 2027 was not verified in GAD. It is explicitly seeded as a user-requested **company holiday**, not represented as a national/GAD holiday. Its DB source records that distinction.
- **Seed range safety:** any calendar operation that reaches past the last seeded holiday raises `CalendarRangeError`, including closed days and zero-duration calls. Currently that date is **December 25, 2027**. We do not infer holiday-free days through December 31. The API returns 503 with the affected date and extension instructions; failed mutations roll back. Extend DB seeds before calculating later dates.
- **Customer privacy:** private notes are separate from public messages. Customer serializers allow only named fields; customer CSV has its own allowlist and neutralizes spreadsheet formula prefixes. Customer endpoints do not expose events, notes, emails or access tokens. The audit writer accepts only event-specific metadata keys and never stores any message/note body. All customer-facing routes are tagged and enumerated by the endpoint-wide leak test, including customer reply and both reopen outcomes.
- **Audit:** compound requests write one event per logical mutation: entering waiting writes public reply, pause, and status events; resuming by reply writes public reply, resume, and status events; a linked reply writes create, link, and public reply events on the new ticket. PostgreSQL triggers reject event UPDATE, DELETE and TRUNCATE. An INSERT trigger replaces any supplied event timestamp with database server time. Mutation request schemas reject extra fields, including client timestamps. The events API is read-only and agent-authenticated. These controls do not stop a database owner from disabling triggers; the deployment bootstrap provisions a restricted application role without audit mutation privileges. No hash chain is implemented.
- **Agent authentication:** each agent signs in with their own lowercase email and password. `POST /auth/login` returns a random 32-byte session token, expiry and agent name/id. Every agent route derives its actor from `Authorization: Bearer <session token>`; client identity headers are ignored and there is no shared agent secret. Sessions expire absolutely after 12 hours and logout revokes the current session. Inactive agents, expired sessions and revoked sessions are refused. Only SHA-256 token hashes are stored. Passwords use `hashlib.scrypt` with a per-password random 16-byte salt and constant-time digest comparison. Unknown, passwordless, inactive and wrong-password accounts receive the identical 401 body and one equivalent scrypt verification. Five failed attempts for a normalized email within ten minutes lock that email for ten minutes, including correct passwords; counters and serialization locks live in PostgreSQL across app instances. Failed/throttled attempts produce structured application logs without credentials, and no ticket events. Customer UUID capabilities (`X-Customer-Token`) and the separate `FRONTDESK_SWEEP_TOKEN` keep their existing behavior. Linked tickets retain their capability; customer capability delivery, expiry and rotation are not implemented. Password reset, password change UI, MFA, SSO, per-customer login and session listing are not implemented.

## API

| Method and path | Access | Behavior |
| --- | --- | --- |
| `POST /tickets` | Agent | `source`: `customer` (default, first-reply target) or `agent` (no first-reply target); return capability |
| `POST /customer/tickets` | Public intake | Create customer ticket with first-reply target; return capability |
| `GET /tickets?assignee=me` | Agent | Queue; also supports `all` and `unassigned` |
| `GET /tickets/{id}` | Agent | Public thread, distinct internal notes and SLA |
| `POST /auth/login` | Public | Email/password; token, absolute expiry and agent; generic 401 or throttled 429 |
| `GET /auth/me` | Agent session | Current agent id/name |
| `POST /auth/logout` | Agent session | Revoke the current session |
| `GET /agents` | Agent | Seeded agent list |
| `POST /tickets/{id}/claim` | Agent | Atomic claim; own repeat is 200; other owner/inactive is 409 |
| `POST /tickets/{id}/reassign` | Agent | New `assignee_id`; logs old/new; clocks unchanged |
| `POST /tickets/{id}/agent-reopen` | Agent | Same reopen/link rules as customer; agent actor |
| `POST /tickets/{id}/messages` | Agent | `body` plus `visibility`: public (default) or internal |
| `POST /tickets/{id}/notes` | Agent | Internal note convenience endpoint |
| `POST /tickets/{id}/status` | Agent | Current `version` required; Waiting also requires public `body`; stale version is 409 |
| `POST /tickets/{id}/priority` | Agent | Recompute and log old/new deadlines |
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

All requested local hardening phases and the end-to-end proof are implemented. The fallback HTML checks execute the shipped JavaScript render functions against a DOM sink; this is not a new real-browser or Playwright run. No public search or standalone customer-message-list route exists (404 is tested); public conversations are in the customer ticket view. Public hosting, repository publication, hosted CI/Docker build, hosted API checks and the browser workflow pass are complete. One-week availability remains to be observed. The application sweep runs every 60 seconds while the service is awake; the optional GitHub scheduled sweep still needs its repository secrets, so that external scheduled workflow has not been verified. A local container build was not run because Docker is not installed. Individual agent authentication is implemented. Password reset, password change UI, MFA, SSO, per-customer login, session listing, customer-capability delivery/rotation, email integration, pagination, database connection pooling and audit hash chaining remain unimplemented. The small demo scope prioritized incident protections and the working support workflow. Holiday seeds require extension beyond the guarded range. See [SUBMISSION.md](SUBMISSION.md) for the draft unfinished-work note and submission checklist.

Earlier baseline verification (before this hardening request): **75 passed, zero skipped, zero warnings** against local PostgreSQL 17. JavaScript syntax checks passed. Browser verification covered ticket creation, a stale two-agent claim conflict, public reply, internal note, waiting, customer-triggered resume, priority change, resolution, fresh-cycle reopen and the timeline. Agent and customer layouts were inspected at 390px with no horizontal overflow. CSV payload safety is covered by API tests; native in-app-browser download completion was not confirmed. The runtime role was checked to have no superuser/create-database/create-role privileges and no UPDATE/DELETE access on events.


## Hardening proof — 22 November 2026

Run **everything**, including the single end-to-end scenario, from one command:

```sh
TEST_DATABASE_URL="postgresql://frontdesk:frontdesk@localhost:5432/frontdesk" uv run python -m scripts.verify
```

The verification database user needs CREATE SCHEMA and CREATEROLE permissions. Tests migrate fresh UUID-named schemas and drop those schemas afterward; they do not clear existing application data. The runner fails if any tests skip, if PostgreSQL is inaccessible, or if Node is unavailable. FastAPI's TestClient uses the pinned `httpx2` transport against the real migrated database, with an injectable operation clock. Audit timestamps intentionally remain PostgreSQL server time. No SQLite substitute or mocked persistence is used. CI runs this same command after setting up Node.

`tests/test_end_to_end.py::test_frontdesk_end_to_end` is the one scripted scenario. It seeds Meera/Arun, holidays and policies via migrations, performs the requested lifecycle and privacy checks, and runs the actual agent render functions for HTML smoke assertions. `test_raw_html_escaped_in_actual_agent_and_customer_renderers` additionally executes the customer renderer. Playwright was not already configured, so no Playwright dependency was added.

**Arithmetic correction:** Friday 17:50 leaves 40 working minutes before 18:30. Urgent first reply has 120 minutes, leaving 80 on Monday: **Monday 10:50**, not 11:20. Resolution remains Friday 18:30. There is no intake cutoff. This corrects the Phase 5 example without changing any Phase 0 decision.

**Request contracts:** message/note bodies preserve raw text, reject blank content and reject more than 10,000 characters. Validation errors omit submitted values. Read an agent ticket's `version` and send it with status changes, e.g. `{"status":"waiting_on_customer","body":"Which workspace?","version":1}`. A missing version is 422; a stale version is 409. Send `Idempotency-Key` (1–200 characters) on agent `/messages` or customer `/customer-reply`: the same actor, path and content within 24 hours returns the original 201 JSON response; reusing a live key for different content returns 409. Expired keys permit a new mutation. Retry protection includes replies that create linked tickets. Idempotency uses database server time, independent of SLA test clocks. Keys are scoped to the authenticated agent or customer capability. The runtime role is granted access to the idempotency table.

`first_reply_at` and `first_reply_actor` in the agent detail come from the first public agent audit event; `first_replied_at` is the existing materialized SLA field. Ticket-wide `resolution_breached` includes retained history; `cycle_resolution_breached` describes the current cycle's own outcome. On-time initial resolution freezes the original first-reply obligation even if no reply was required to resolve. Reading agent SLA data records monotonic breach flags under the ticket lock; it does not add audit events or advance the status version. Existing recorded resolution-cycle breaches are imported by migration 006. Migration 006 removes the first-reply obligation from legacy tickets whose creation event identifies an agent. Unknown legacy sources keep the conservative first-reply requirement; no source is invented.

### Phase outputs

Each phase ran the entire suite against local PostgreSQL, with zero skipped tests on its successful checkpoint:

| Checkpoint | Full-suite terminal output | Skipped / uncertain |
| --- | --- | --- |
| Baseline with DB | `75 passed in 8.40s` | None skipped |
| Phase 0 | `79 passed in 10.24s` | No specified trigger for system closure of resolved tickets; sweep closes waiting only |
| Phase 1 | `108 passed in 10.75s` | Phase 5 example corrected to Monday 10:50 |
| Phase 2 | `115 passed in 19.76s` | Thread scheduling is nondeterministic; winner identity is deliberately not asserted |
| Phase 3 | `118 passed in 16.66s` | Search and standalone customer-message routes do not exist; 404 checked |
| Phase 4 | `139 passed in 26.24s` | Node DOM sink for renderer checks; no new real-browser run |
| Phase 5 initial | `140 passed in 33.70s` | No skipped tests |
| Final | `164 passed in 30.72s` | Zero skipped, zero warnings; no Phase 0 deviations |

The initial unconfigured run (`37 passed, 38 skipped`) was replaced by the configured DB baseline above. Phase 0's first run (`1 failed, 74 passed`) exposed an old test asserting that reopen clears ticket lateness; it now asserts permanent breach history. Phase 3's first run (`1 failed, 117 passed`) logged a marker that the test itself placed in its search URL; the corrected test queries ordinary public text while checking that the stored private marker never escapes. These intermediate failures are not hidden or counted as successful checkpoints.

### Rule-to-test coverage

This is a coverage-style requirement map, not a claim of measured line or branch coverage. Names below refer to functions under `tests/`.

| Incident / rule | Test proving it |
| --- | --- |
| INC-0291: simultaneous claims, one owner/event, loser sees owner | `test_n_claims_one_event`, `test_exactly_one_parallel_claim_wins`, end-to-end |
| INC-0304: note text never customer-visible or in events | `test_notes_invisible_in_data_metadata_headers_errors_and_logs`, `test_complete_customer_route_inventory_and_note_leak_lifecycle` |
| INC-0318: reconstruct first reply with actor from audit; show in UI | `test_mutation_event_counts_and_inc0318_event_derived_reply`, `test_raw_html_escaped_in_actual_agent_and_customer_renderers` |
| P0.1: late on either clock, identify targets, permanent after late resolution | `test_completed_on_time_never_becomes_late_and_late_reply_sticks`, `test_resolve_snapshots_breach_and_cannot_bypass_reopen`, `test_independent_clocks_and_friday_medium_not_late` |
| P0.2: waiting requires public agent message in same request | `test_claim_reassign_wait_and_invalid_transitions`, `test_waiting_resumes_and_preserves_pause_history`, end-to-end |
| P0.3: only first public agent reply satisfies | `test_first_reply_only_first_public_agent_message`, end-to-end |
| P0.4: start at creation, unassigned can breach | `test_independent_clocks_and_friday_medium_not_late`, `test_priority_change_logs_both_deadlines_and_is_immediately_late` |
| Ticket source: customer/default matches customer intake; agent-initiated stores null first-reply target; creation audit records source and authenticated actor | `test_ticket_creation_source_paths`, `test_agent_creation_has_stored_null_reply_target` |
| Source form defaults to Customer request and retains priority hints; invalid source rejected | `test_create_form_source_options_and_priority_hints`, `test_invalid_ticket_source_does_not_create` |
| P0.6: customer open/waiting/resolved/expired/closed routing; no lost reply | `test_customer_completed_reply_links_or_reopens_and_agent_reopen`, `test_reply_close_race_both_lock_orders`, end-to-end |
| P0.7: agent reopen, actor and same assignee; closed creates link | `test_customer_completed_reply_links_or_reopens_and_agent_reopen`, `test_agent_can_create_link_from_closed_without_editing_it` |
| P0.8: repeat claim 200/no event; others 409/name; inactive 409 | `test_n_claims_one_event`, `test_claim_requires_agent_and_conflicts_on_second_claim`, `test_claim_completed_conflicts` |
| P0.9: reassign old/new event, clocks untouched | `test_claim_reassign_wait_and_invalid_transitions`, `test_mutation_event_counts_and_inc0318_event_derived_reply` |
| P0.10: transition graph; same-status/closed invalid; system-only closure | `test_claim_reassign_wait_and_invalid_transitions`, `test_status_transition_matrix`, `test_sweep_threshold_and_idempotency` |
| Working windows, no 18:00 cutoff, urgent end of start day | `test_intake_start`, `test_open_close_arrivals`, `test_1815_reply_carries_to_next_working_day`, end-to-end |
| 09:29, 09:30, 18:29, 18:30, 18:31 arrivals | `test_open_close_arrivals` (five explicit cases) |
| Friday 18:00 medium, Saturday/Sunday/Monday 09:00 safe; deadline strict | `test_independent_clocks_and_friday_medium_not_late` |
| Saturday, Sunday, holiday arrival uses next opening | `test_weekend_and_monday_holiday_arrivals`, `test_intake_start` |
| Monday holiday; intervening/weekend holiday; consecutive holidays | `test_holidays_between_friday_and_next_opening` |
| Holiday inside five-working-day window | `test_five_working_days_exclude_holiday_and_weekend` |
| Pause begins outside hours; weekend-only; multiple intervals | `test_outside_weekend_multiple_pauses` |
| Pause begins after deadline; breach stays | `test_pause_after_original_deadline_does_not_erase_breach`, `test_pause_after_breach_stays_breached_on_autoclose` |
| Open pause needs explicit aware now; first reply unaffected | `test_open_pause_freezes_clock_at_supplied_now`, `test_open_pause_requires_explicit_clock`, `test_outside_weekend_multiple_pauses` |
| Overlapping/reversed pauses rejected; open pause last | `test_reject_overlapping_pauses`, `test_reversed_pause_is_rejected`, `test_open_pause_cannot_be_followed_by_another_pause` |
| Urgent mid-day pause extends past start day | `test_urgent_pause_extends_same_day_deadline`, `test_waiting_resumes_and_preserves_pause_history` |
| Reply/resolution independent; late reply stays late after satisfaction | `test_independent_clocks_and_friday_medium_not_late`, `test_completed_on_time_never_becomes_late_and_late_reply_sticks` |
| Medium→urgent instantly late; original start; old/new deadline audit | `test_priority_change_logs_both_deadlines_and_is_immediately_late`, end-to-end |
| Urgent→small cannot clear breach; priority while paused/after reply | `test_priority_paused_replied_and_sticky_downgrade` |
| Priority change on completed rejected | `test_resolve_snapshots_breach_and_cannot_bypass_reopen`, `test_priority_paused_replied_and_sticky_downgrade` |
| Reopen exactly 2700 allowed; 2701 linked; pauses not inherited | `test_exact_2700_reopens_new_cycle_preserving_breach_event`, `test_2701_creates_linked_ticket`, `test_reopen_does_not_reset_first_reply_or_use_old_pauses` |
| Closed hours after minute 2700 still inside reopen window | `test_reopen_2700_remains_inclusive_during_closed_hours` |
| On-time completed obligation frozen after reopen; own cycle outcome | `test_reopen_does_not_turn_on_time_first_cycle_into_a_reply_breach`, `test_completed_cycle_outcome_is_independent_of_ticket_history` |
| Auto-close 2699 no / 2700 yes, working time, uninterrupted wait only | `test_five_working_days_exclude_holiday_and_weekend`, `test_sweep_threshold_and_idempotency`, `test_only_uninterrupted_wait_autocloses` |
| Upgrade retains recorded breaches and known intake source | `test_upgrade_preserves_creation_source_and_recorded_breach` |
| Agent top-level SLA fields match persisted/current flags | `test_agent_sla_snapshot_matches_stored_flags` |
| Calendar beyond last seed errors and rollback | `test_calendar_rejects_unseeded_range`, `test_calendar_range_failure_rolls_back_creation` |
| Naive timestamps rejected throughout calculator | `test_naive_rejected_everywhere` (12 entry/argument cases), `test_client_timestamps_rejected_and_server_event_time_used` |
| Concurrent status mutations: one wins / one 409 | `test_stale_simultaneous_status_conflict` |
| Parallel duplicate public reply: original response, one message/event, 24h expiry | `test_parallel_idempotent_reply_and_expiration` (agent and customer cases) |
| Sequential/concurrent sweep retry: one close event | `test_sweep_threshold_and_idempotency`, `test_parallel_sweeps_write_one_close_event` |
| Customer reply vs auto-close: both lock orders, no lost message | `test_reply_close_race_both_lock_orders` |
| Marker absent from every public/customer response, error, header, event, log | `test_notes_invisible_in_data_metadata_headers_errors_and_logs` (route inventory enforced) |
| Notes reveal no count/activity/update metadata and affect no clocks | `test_notes_invisible_in_data_metadata_headers_errors_and_logs` (byte-equal customer responses and SLA/pause checks) |
| Agent notes carry Team-only; customer renderer excludes notes | `test_raw_html_escaped_in_actual_agent_and_customer_renderers`, end-to-end |
| Customer allowlists; new model column requires explicit decision | `test_model_columns_require_explicit_privacy_decision`, `test_customer_allowlist_views_and_csv` |
| Agent endpoints private, no-store | `test_agent_endpoints_private_no_store` |
| Event PUT/PATCH/DELETE 404/405 | `test_audit_api_immutable`, end-to-end |
| Event SQL UPDATE/DELETE/TRUNCATE fail; supplied INSERT time overwritten | `test_events_reject_mutations`, `test_event_timestamp_is_server_generated` |
| One event per logical create/claim/reassign/reply/note/status/priority/pause/resume/reopen | `test_mutation_event_counts_and_inc0318_event_derived_reply`, end-to-end exact timeline |
| Auto-close actor system; link creation audited on new ticket | `test_sweep_threshold_and_idempotency`, end-to-end |
| Before/after, actor, ordered server timestamps; note text excluded | `test_mutation_event_counts_and_inc0318_event_derived_reply`, `test_audit_writer_refuses_note_body`, end-to-end |
| Script/HTML stored raw and rendered escaped in both UIs | `test_raw_html_escaped_in_actual_agent_and_customer_renderers` |
| Empty/whitespace/over-10,000 bodies 422 | `test_invalid_bodies_422` (12 cases) |
| Unknown IDs 404; malformed input 422, no 500 | `test_unknown_ids_and_malformed_input` |
| Login success, absolute 12-hour expiry, logout revocation | `test_login_me_logout_absolute_lifetime` |
| Uniform 401 and equal scrypt work for wrong/unknown/inactive/passwordless accounts | `test_identical_failures_and_equal_password_work` |
| Database throttle, correct-password refusal, exact recovery and normalized email across instances | `test_database_throttle_normalization_recovery_across_instances`, `test_failure_window_resets` |
| Concurrent failures cannot lose throttle counts | `test_concurrent_failed_logins_share_one_database_counter` |
| Every agent route rejects missing/malformed/expired/revoked/inactive/customer/sweep credentials | `test_all_agent_routes_reject_invalid_sessions` (dynamic route inventory) |
| Forged identity header cannot change actors; only assignee replies publicly | `test_header_cannot_impersonate_and_every_agent_mutation_actor`, `test_exactly_one_parallel_claim_wins` |
| Agent/customer/sweep credential separation | `test_capability_and_sweep_isolation` |
| Raw passwords/tokens absent from all-column database dump, logs, other responses and errors | `test_secrets_absent_from_dump_logs_errors_and_other_responses` |
| Per-password salts; stdin provisioning revokes old sessions | `test_password_salt_compare_and_provisioning` |
| Demo hint and three passwords only in enabled demo mode; no default | `test_demo_credentials_only_when_enabled` |
| Restricted runtime can log in, mutate tickets and revoke; cannot update/delete/truncate events or change passwords; repeated provisioning works under a non-superuser database owner | `test_restricted_runtime_can_authenticate_but_cannot_edit_audit`, `test_repeated_provisioning_with_non_superuser_owner` |
| Sign-in, generic errors, 429, signed-in identity, logout and API 401 cleanup | `test_login_ui_session_lifecycle` executes shipped JavaScript handlers |
| Full scripted steps 1–13, customer privacy, timeline and late-first HTML | `test_frontdesk_end_to_end` |

### Flakiness and assumptions

- New thread/concurrency tests `test_n_claims_one_event`, `test_stale_simultaneous_status_conflict`, `test_parallel_idempotent_reply_and_expiration`, `test_reply_close_race_both_lock_orders`, and the parallel-claim step of `test_frontdesk_end_to_end` have 10-second synchronization deadlines. An unusually overloaded machine may time out. They assert valid outcome sets, not a particular agent winning. The close/reply tests hold real DB transactions with threading events to exercise each lock order without sleeps. Existing parallel claim/reopen/sweep tests retain their 5-second barrier deadlines.
- New `test_mutation_event_counts_and_inc0318_event_derived_reply` assumes the local PostgreSQL server clock is within two minutes of the test process clock; existing timestamp tests assume the same host clock. Audit time deliberately does not follow the injected SLA clock.
- `test_parallel_idempotent_reply_and_expiration` ages the test record by 25 hours in SQL; it tests reuse after the window without waiting 24 real hours. The SQL comparison itself defines the exact 24-hour cutoff.
- The HTML tests and end-to-end scenario require Node and execute the shipped render functions with minimal DOM/network sinks. They verify emitted HTML, escaping, labels, attribution and ordering; they do not cover browser layout, event delivery, focus behavior or a deployed server. The existing scheduler smoke test uses the real host date and the finite holiday seed range.
- Endpoint and model-field inventory assertions are intentionally strict: adding a route or column requires reviewing its privacy classification and updating the tests. The no-log-marker check captures Python application/test-client logs, not external reverse-proxy logs.
- Fixture agents, policy values and published holiday seeds are assumed to match this project's migrations; explicit date assertions are in Asia/Kolkata. No external holiday-service or hosting behavior is assumed.

**Phase 0 deviations: none.** The only numerical correction is Phase 5's first-reply deadline (10:50). Resolved→closed is system-reserved, but the brief gives no resolved-ticket closure trigger; no new trigger was invented. Ticket-wide historical lateness is kept separate from per-cycle outcomes.


Final verification after all code changes:

```text
........................................................................ [ 43%]
........................................................................ [ 87%]
....................                                                     [100%]
164 passed in 30.72s
```

Both JavaScript syntax checks, Python compilation, and `git diff --check` also passed. Existing uncommitted UI work was preserved; no application deployment or live-database migration was performed. Tests exercised migrations only in their isolated test schemas.


## Per-agent authentication proof — 22 November 2026

All 12 agent ticket/directory routes use the session-derived actor. Added `POST /auth/login`, `POST /auth/logout`, and `GET /auth/me`; updated the `/` login shell and its static assets. The API inventory is in the table above. The runtime role can select agents and read/insert/update sessions and login counters (also delete counters after successful login); only the administrator can provision passwords. Audit grants remain SELECT/INSERT, with UPDATE/DELETE/TRUNCATE denied.

Intentionally public: `POST /auth/login` exchanges credentials; `POST /customer/tickets` retains public intake; `/`, `/customer`, `/static/*`, `/health`, `/docs`, `/redoc`, and `/openapi.json` provide shells, assets, health or API metadata without ticket data. Customer reads, exports, replies and reopen still require `X-Customer-Token`; `/admin/sweep` still requires its independent sweep secret. Demo mode intentionally exposes the configured shared demo password in the login hint; disable demo mode outside demonstrations.

Authentication timing tests inject a dedicated clock and assert exact expiry/lockout boundaries without sleeps. The enumeration test checks equivalent scrypt work rather than flaky elapsed-time thresholds; it is not a statistical network timing proof. The new concurrent-login throttle test uses the existing ten-second barrier deadline. Parallel claim/reopen/sweep and scheduler tests retain their synchronization deadlines, and audit timestamp tests retain their two-minute host/database clock assumption. The UI lifecycle test uses a Node DOM/network sink; a fresh browser layout pass and Docker build were not performed for this change.

Full checkpoint output is saved in `output/auth-step-1.txt` through `output/auth-step-7.txt`. The first two recorded runs each had 163 passes and one failure because the pre-existing privacy inventory did not yet list the three new auth routes; that inventory was corrected before step 3. Steps 3–5 each passed all 164 existing tests. The completed authentication suite and final documentation checkpoint are recorded in those output files. At that authentication checkpoint, no live database migration or deployment had been performed; the publication/deployment checkpoint below supersedes that status.


## Publication checkpoint — 22 November 2026

The complete application is published on `main` in [Sangeeth62880/Frontdesk_Coligo](https://github.com/Sangeeth62880/Frontdesk_Coligo), commit `d547358`. [GitHub CI](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45031110417) passed the full PostgreSQL suite, both JavaScript syntax checks, and the Docker image build. The latest local full-suite result is 194 passed, zero skipped (`output/ticket-source-tests.txt`). The approved Render Blueprint deployed commit `d547358` to [frontdesk-spfe.onrender.com](https://frontdesk-spfe.onrender.com), using new free Docker web and PostgreSQL 17 resources in Singapore. Hosted API checks passed for all three demo logins, both creation sources, parallel claims, public replies, private-note isolation, wait/resume, priority, resolution, reopen, CSV and logout. The browser walkthrough passed sign-in, default-source ticket creation, claim, public reply, internal note, customer isolation/reply, priority, resolution and agent reopen. The browser native CSV download event timed out; CSV content was verified through the hosted API. No application error logs were found after verification. Synthetic verification tickets remain visibly named in the demo. One-week availability is still pending observation; the free database expires on 22 December 2026 at 19:56 IST.
