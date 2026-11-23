# Deployment

## Render and Docker

`Dockerfile` runs one FastAPI instance serving both the static UI and API. `render.yaml` declares a free web service and PostgreSQL database, generated secrets, startup demo data and health checking. The container starts with administrator DB credentials for migrations, provisions `frontdesk_app`, and then switches requests and the sweep worker to that restricted role.

1. Publish this repository to GitHub and connect it to Render as a Blueprint using `render.yaml`.
2. Confirm the generated secrets in the Render dashboard. Keep the migration DB credentials out of browser/client configuration. Supply the demo login emails and password with the submission.
3. Verify the deployed `/health`, sign into the UI and repeat the manual workflow below.
4. For automatic sweeps while the free instance is asleep, configure GitHub repository secrets `FRONTDESK_BASE_URL` (the HTTPS app URL) and `FRONTDESK_SWEEP_TOKEN` (the same secret as Render). The included scheduled workflow calls the sweep every 15 minutes; `workflow_dispatch` supports manual triggering. GitHub schedule execution may be delayed and is not an exact timer.
5. Confirm hosted tests and the first scheduled sweep succeed. Record the actual deployment and database expiry dates, and keep the service available for at least seven days after submission.

The built-in sweep runs immediately on application startup and every 60 seconds while the process is alive; `FRONTDESK_SWEEP_INTERVAL_SECONDS=0` disables it. Independent workers coordinate through database row locks. A failure rolls back the sweep and retries next interval. **Free Render services can sleep after 15 idle minutes and free databases expire after 30 days**, so the in-process worker alone cannot guarantee scheduled execution while asleep. See [Render free-tier documentation](https://render.com/docs/free). On wake, the startup sweep catches up; configure the external workflow to cover idle periods. Do not promise exact sweep timing or one-week uptime before verifying the deployed service. GitHub CI, the Docker image build and the hosted deployment are verified; the optional GitHub scheduled sweep has not been configured.

## Local configuration and provisioning

`FRONTDESK_SEED_DEMO=true` creates eight representative synthetic tickets once and provisions Meera, Arun and Divya with the required `FRONTDESK_DEMO_PASSWORD` (there is no code default). Open `http://127.0.0.1:8000` and sign in with `meera@arvo.example`, `arun@arvo.example` or `divya@arvo.example` and that password. A muted hint appears only in demo mode. All nine agents have `firstname@arvo.example` addresses; the other six have no password until provisioned. Startup migrates, seeds using the administrator connection, optionally provisions a restricted runtime role, then serves requests with that role. Repeat seeds preserve existing passwords.

For a non-demo installation, set `FRONTDESK_SEED_DEMO=false` and provision each agent with the administrator database connection:

```sh
uv run --env-file .env python -m scripts.migrate
uv run --env-file .env python -m scripts.set_agent_password
```

The provisioning script reads the email and password from stdin (a hidden password prompt in a terminal), stores a salted scrypt hash, and revokes that agent's existing sessions. It takes no password command-line argument. Browser session tokens are held in tab-scoped session storage; Sign out revokes the current server session and clears that storage. Any API 401 clears the browser session and returns to the login form.

With an existing PostgreSQL instance, set its `DATABASE_URL` and omit the Docker command. Set `FRONTDESK_DB_PASSWORD` to enable restricted-role provisioning; this requires a migration connection with role-administration privileges. Production bootstrap requires it on Render. Database credentials are not printed or sent to the browser. `/docs` provides the API explorer. Dependencies are pinned in `uv.lock`.

Migrations run once each in a transaction with an advisory lock. Demo seeding is idempotent and should run only in a demo environment. Synthetic tickets have historical SLA start times and service operation times; their messages/events are inserted now and retain actual server insertion timestamps. The timeline therefore shows when demo records were seeded, not a fabricated historical audit timestamp.

To build and run the deployment image locally after configuring `.env` and a database reachable from the container:

```sh
docker build -t frontdesk .
docker run --rm --env-file .env -e PORT=8000 -p 8000:8000 frontdesk
```

A database URL using `localhost` inside the container refers to that container; use a database hostname reachable from Docker.

## Using the screen

Select My tickets, Unassigned or All tickets. Search by subject, email or ticket ID and choose an active/completed filter. Late tickets sort first. Use the dedicated Take this ticket button beside Assignee to claim an unassigned ticket before posting a public reply. The reply box defaults to Public; Internal note switches to an amber team-only mode. Status and priority controls sit above the conversation. Activity timeline shows every mutation, including priority deadline snapshots and completed-cycle breaches.

Create a ticket with New ticket. Source defaults to Customer request, including a first-reply target; select Agent-initiated to omit that target. Simulate a customer reply from the ticket action, or open Customer view in a separate tab; the customer page cannot load agent notes or agent timelines. Resolving a ticket enables customer and agent reopening. Selecting Waiting prompts for a public question, or sends the public draft in the composer, in the same transaction. The customer view can also download the allowlisted CSV. Drafts remain in memory while the ticket stays selected; changing tickets discards an unsent draft.

## Manual browser verification

On the deployed URL:

1. Create a ticket; open it as two different agents in separate tabs.
2. Claim from one then attempt the stale claim from the other; confirm the loser sees the owner's name and cannot reply.
3. Send a public reply and unique-marker internal note, switch to customer view, and verify the marker is absent from the page and CSV.
4. Enter Waiting, reply as the customer, verify Open and the resumed deadline.
5. Change priority, inspect the timeline's old/new deadlines, resolve, and reopen to confirm cycle two.

The automated PostgreSQL tests cover exact working-time boundaries and concurrent races that are harder to reproduce manually.

## Verified hosted deployment — 22 November 2026

The initial verified application was published on `main` in [Sangeeth62880/Frontdesk_Coligo](https://github.com/Sangeeth62880/Frontdesk_Coligo), commit `d547358`. [GitHub CI](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45031110417) passed the full PostgreSQL suite, both JavaScript syntax checks, and the Docker image build. The ticket-source checkpoint passed 194 tests; the current suite passes 195 tests, zero skipped. The approved Render Blueprint deployed commit `d547358` to [frontdesk-spfe.onrender.com](https://frontdesk-spfe.onrender.com), using new free Docker web and PostgreSQL 17 resources in Singapore. Hosted API checks passed for all three demo logins, both creation sources, parallel claims, public replies, private-note isolation, wait/resume, priority, resolution, reopen, CSV and logout. The browser walkthrough passed sign-in, default-source ticket creation, claim, public reply, internal note, customer isolation/reply, priority, resolution and agent reopen. The browser native CSV download event timed out; CSV content was verified through the hosted API. No application error logs were found after verification. Synthetic verification tickets remain visibly named in the demo. One-week availability is still pending observation; the free database expires on 22 December 2026 at 19:56 IST.

The current deployed application commit is `c20a8c4`. The dedicated Take this ticket button was verified on the live site, and repeated provisioning was verified under a non-superuser PostgreSQL owner. [Current CI](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45034482014) passed the full suite and Docker image build. The optional external sweep still requires the repository secrets described above; free-tier cold starts and one-week availability remain operational limitations.

[README](../README.md) · [Testing](TESTING.md)

## External auto-close schedule

The existing GitHub Actions sweep workflow needs exactly two repository Actions secrets: `FRONTDESK_BASE_URL=https://frontdesk-spfe.onrender.com` and `FRONTDESK_SWEEP_TOKEN` equal to the current service environment value in Render → frontdesk-spfe → Environment. Never put the token in workflow source or logs. Run the workflow manually after configuration and inspect **Close expired customer waits** for success rather than relying on a green job with that step skipped. Dispatch run 45097076317 verified successful execution. No Render cron service is needed.

## Explicit demo maintenance

Normal startup never resets data. For the authorized final demo reset, the migration owner can set `FRONTDESK_ADMIN_ACTION=reset-demo`, a fresh UUID in `FRONTDESK_ADMIN_NONCE`, and the exact database name in `FRONTDESK_ADMIN_CONFIRM_DATABASE`, with demo mode/password configured. Startup atomically drops/recreates the public schema, applies migrations and seeds eight cases. It never updates/deletes events. A private `frontdesk_operations.completed` ledger survives the schema reset and prevents repeating an already completed nonce. Incorrect database confirmation and non-owner roles are refused; a failed seed rolls back the entire reset.

After read-only verification, use `FRONTDESK_ADMIN_ACTION=rotate-demo-password` with a fresh nonce and a new securely stored `FRONTDESK_DEMO_PASSWORD`. This changes only the three demo password hashes and revokes their sessions; tickets/events stay intact. Set `FRONTDESK_DEMO_HINT=false` to hide the public hint. Credential-aware verification commands accept the password from environment, so an ignored mode-0600 `.env.demo-release` can supply it without terminal output. Leave the completed nonce in place for safe restart retries, or clear the action after completion. These settings are private operator controls, with no HTTP maintenance endpoint.
