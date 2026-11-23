# Frontdesk

Support tickets with working-time SLAs, private notes and an immutable audit trail.

## Demo

- Live: [frontdesk-spfe.onrender.com](https://frontdesk-spfe.onrender.com)
- Repository: [Sangeeth62880/Frontdesk_Coligo](https://github.com/Sangeeth62880/Frontdesk_Coligo)
- Demo logins: `meera@arvo.example`, `arun@arvo.example`, `divya@arvo.example`; the demo password is supplied with the submission.
- Demo mode (`FRONTDESK_SEED_DEMO=true`) seeds synthetic tickets and these three accounts; only demo mode shows the password hint, and repeat seeds preserve existing passwords.

## Run locally

Prerequisites: Python 3.12+, uv, Node.js, and Docker Compose (or PostgreSQL 17).

```sh
uv sync --locked
npm ci --ignore-scripts
uv run playwright install chromium
cp .env.example .env
docker compose up -d --wait db
uv run --env-file .env python -m scripts.verify
uv run --env-file .env python -m scripts.start
```

Before verification, edit `.env` to set `DATABASE_URL`, `FRONTDESK_DEMO_PASSWORD` and `FRONTDESK_SWEEP_TOKEN`, and check `TEST_DATABASE_URL` points to the verification database; `FRONTDESK_DB_PASSWORD` enables restricted-role provisioning.

## Architecture

Buildless HTML/CSS/JavaScript served from FastAPI and PostgreSQL, with plain SQL migrations and a pure business-time module. Serving the UI and API together avoids a second hosting service and cross-origin configuration. Each request commits its mutation and audit events together before returning success. Row locks serialize mutations, conditional UPDATE handles claims, and `FOR UPDATE SKIP LOCKED` coordinates sweeps. Public messages and private notes occupy separate tables; customer views and CSV use explicit field allowlists.

## Key decisions

- Working hours are Monday–Friday, 09:30–18:30 Asia/Kolkata, excluding holidays; no intake cutoff, because weekends are excluded and the full working window applies.
- SLA targets in working minutes: urgent first reply 120; medium reply/resolution 270/1620; small reply/resolution 540/2700.
- Urgent resolution is due at 18:30 on the effective start day.
- Waiting pauses resolution only; a public assignee question starts the pause, and customer replies resume it.
- Priority changes recompute deadlines from the original applicable start, retaining pauses and recorded breaches. Restarting at the change time was rejected because it discards elapsed customer wait and permits deadline extension through repeated changes.
- A ticket is late if either first-reply or resolution target is breached; breach history remains recorded.
- Claims use an atomic conditional UPDATE; only the current assignee can reply, resolve or wait. Claim an unassigned ticket before resolving it. Any agent may re-triage priority while unassigned; once claimed, only its assignee may change priority.
- “About one week” means five working days: 2700 working minutes for both reopen and auto-close. Reopen through that inclusive boundary deliberately starts a fresh resolution cycle, retaining prior cycles and breaches; later or closed-ticket requests create a linked ticket.
- Only the system closes tickets. Auto-close requires an uninterrupted customer wait of at least 2700 working minutes and writes one system closure event.
- Customers choose initial priority, a known gap; agents can re-triage under the ownership rules.
- Creation requires a Description stored as the first public customer message; it never counts as first reply or changes SLA clocks.
- Resolution optionally includes a public message in the API and requires Message to customer in the inline UI; retries are idempotent and the first such agent message satisfies first reply.
- The Late filter identifies breached targets and working-time overshoot; its agent-only CSV excludes note text and capabilities, neutralizes formulas and is private/no-store.
- Private notes live separately from public messages and never appear in customer responses, CSV or event bodies.
- Audit events are append-only: database triggers reject UPDATE, DELETE and TRUNCATE, and assign server timestamps. Only the table owner with an explicit transaction-local seed setting may supply historical INSERT times; an owner could always bypass triggers.
- Per-agent email/password login uses salted scrypt hashes, hashed 12-hour bearer sessions, logout revocation and database-backed throttling.

Priority changes retain elapsed time because the customer has already waited. Restarting at the change time would hide lateness and allow the clock to be gamed; that alternative was rejected. Customer capabilities are absent from every agent list/detail response. Customer actions fetch their capability through a separate current-assignee-only endpoint. Only the current assignee can transfer ownership, preventing reassignment from bypassing capability isolation. An agent who creates a ticket receives its initial capability; capabilities already shared cannot be recalled without rotation.

Full detail: [Decisions](docs/DECISIONS.md). Final audit evidence and open operational checks: [Audit](docs/AUDIT.md), [requirement traceability](docs/TRACEABILITY.md). The earlier audit release is hosted; the subsequent live-test fixes await their release and final clean demo reset.

## Incidents

| Incident | How it is prevented | Test name |
| --- | --- | --- |
| INC-0291 | Atomic claims allow one winner; the loser sees the owner and cannot reply. | `test_exactly_one_parallel_claim_wins` |
| INC-0304 | Separate private-note storage and customer allowlists prevent leaks. | `test_notes_invisible_in_data_metadata_headers_errors_and_logs` |
| INC-0318 | First-reply time and actor are reconstructed from audit events. | `test_mutation_event_counts_and_inc0318_event_derived_reply` |

## What I did not finish

- Free-tier cold starts remain. In-process sweeps require an awake service; the GitHub schedule uses only FRONTDESK_BASE_URL and FRONTDESK_SWEEP_TOKEN. Both secrets are configured; workflow_dispatch run [45097076317](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45097076317) completed the sweep step successfully (not skipped).
- No password reset, password-change UI, MFA, SSO or session listing.
- No authenticated customer portal, token delivery, capability expiry or rotation UI; only a capability-based customer intake/conversation page. Customer-selected priority still needs an urgency-verification policy.
- No pagination or database connection pooling.
- No audit hash chain.
- Holiday seeds end December 25, 2027 and need extending before later dates can be calculated.
- Chromium lifecycle, accessibility, responsive screenshots and native CSV download passed locally for the live-test fixes and against the preceding hosted release; the new hosted run is pending; natural 12-hour expiry and live-account lockout remain local deterministic coverage. See [release evidence](docs/RELEASE.md).
- One-week uptime has not yet been observed.

## Documentation

- [API](docs/API.md)
- [Deployment](docs/DEPLOY.md)
- [Decisions](docs/DECISIONS.md)
- [Testing](docs/TESTING.md)

## Audit commands and limits

The verification command runs PostgreSQL integration tests, 2,000 deterministic Hypothesis/reference cases, 150 OpenAPI-generated request cases, stress replay and headless Chromium with axe. PostgreSQL needs CREATE SCHEMA and CREATEROLE for isolated test schemas/roles. Run `uv run ruff check frontdesk scripts tests`, `uv run mypy --explicit-package-bases --check-untyped-defs frontdesk scripts`, `uv run pip-audit`, and `npm audit` for separate static/security checks. Dependencies are exactly resolved in `uv.lock` and `package-lock.json`; direct Python constraints intentionally permit compatible updates only when the lock is refreshed.

Public intake permits 10 tickets per resolved client IP per ten-minute window (`FRONTDESK_INTAKE_LIMIT`), shared across processes in PostgreSQL. Uvicorn resolves trusted proxy addresses; never accept arbitrary forwarded identity headers. Configure `FORWARDED_ALLOW_IPS` for a known reverse proxy if needed; absent trusted proxy resolution, a shared proxy may share a quota. Request bodies are limited to 65,536 streamed bytes (`FRONTDESK_MAX_BODY_BYTES`); subject is 300 characters, messages 10,000, and null characters are rejected. DB connects time out in five seconds and statements in 10,000 ms (`FRONTDESK_STATEMENT_TIMEOUT_MS`). Startup emits structured request records with server request IDs and omits query strings, bodies and access tokens; `FRONTDESK_LOG_LEVEL` defaults to INFO.

Explicit load command: `uv run --env-file .env pytest tests/audit_load.py -q -s` (requires `TEST_DATABASE_URL` in `.env`). This runs for 60 seconds and is separate from routine verification. Hosted check: `uv run python -m scripts.audit_hosted --browser --load`; it uses the enabled demo hint only in memory, caps reads at five/second across 50 virtual users and creates ten clearly labeled tickets. Do not repeat it casually on a free tier. Synthetic records remain intentionally labeled because deleting or rewriting their event history would defeat immutability.

For a **fresh empty migrated schema only**, `uv run --env-file .env python -m scripts.seed_review_demo --as-of 2026-11-23T10:00:00+05:30` creates six deterministic cases (late, waiting, Friday evening, near reopen, urgent, unassigned). Reruns preserve their events; a populated unrelated schema is refused. This does not rewrite the shared hosted demo.
