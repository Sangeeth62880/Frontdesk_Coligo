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
cp .env.example .env
docker compose up -d --wait db
uv run --env-file .env python -m scripts.verify
uv run --env-file .env python -m scripts.start
```

Edit `.env` to set `DATABASE_URL`, `FRONTDESK_DEMO_PASSWORD` and `FRONTDESK_SWEEP_TOKEN`, and check `TEST_DATABASE_URL` points to the verification database; `FRONTDESK_DB_PASSWORD` enables restricted-role provisioning.

## Architecture

Buildless HTML/CSS/JavaScript served from FastAPI and PostgreSQL, with plain SQL migrations and a pure business-time module. Serving the UI and API together avoids a second hosting service and cross-origin configuration. Each request commits its mutation and audit events together before returning success. Row locks serialize mutations, conditional UPDATE handles claims, and `FOR UPDATE SKIP LOCKED` coordinates sweeps. Public messages and private notes occupy separate tables; customer views and CSV use explicit field allowlists.

## Key decisions

- Working hours are Monday–Friday, 09:30–18:30 Asia/Kolkata, excluding holidays; no intake cutoff, because weekends are excluded and the full working window applies.
- SLA targets in working minutes: urgent first reply 120; medium reply/resolution 270/1620; small reply/resolution 540/2700.
- Urgent resolution is due at 18:30 on the effective start day.
- Waiting pauses resolution only; a public assignee question starts the pause, and customer replies resume it.
- Priority changes recompute deadlines from the original applicable start, retaining pauses and recorded breaches.
- A ticket is late if either first-reply or resolution target is breached; breach history remains recorded.
- Claims use an atomic conditional UPDATE; only the assignee can post public replies.
- Reopen within 2700 working minutes is inclusive and starts a new resolution cycle; later or closed-ticket requests create a linked ticket.
- Auto-close requires an uninterrupted customer wait of at least 2700 working minutes and writes one system closure event.
- Private notes live separately from public messages and never appear in customer responses, CSV or event bodies.
- Audit events are append-only: database triggers reject UPDATE, DELETE and TRUNCATE, and assign server timestamps.
- Per-agent email/password login uses salted scrypt hashes, hashed 12-hour bearer sessions, logout revocation and database-backed throttling.

Full detail: docs/DECISIONS.md

## Incidents

| Incident | How it is prevented | Test name |
| --- | --- | --- |
| INC-0291 | Atomic claims allow one winner; the loser sees the owner and cannot reply. | `test_exactly_one_parallel_claim_wins` |
| INC-0304 | Separate private-note storage and customer allowlists prevent leaks. | `test_notes_invisible_in_data_metadata_headers_errors_and_logs` |
| INC-0318 | First-reply time and actor are reconstructed from audit events. | `test_mutation_event_counts_and_inc0318_event_derived_reply` |

## What I did not finish

- Free-tier cold starts remain; sweeps depend on the awake service or the GitHub schedule, whose secrets still need configuring.
- No password reset, password-change UI, MFA, SSO or session listing.
- No authenticated customer portal or token delivery; only a capability-based customer conversation page.
- No pagination or database connection pooling.
- No audit hash chain.
- Holiday seeds end December 25, 2027 and need extending before later dates can be calculated.
- Real-browser tests are manual, not automated; native CSV download completion remains unconfirmed.
- One-week uptime has not yet been observed.

## Documentation

- [API](docs/API.md)
- [Deployment](docs/DEPLOY.md)
- [Decisions](docs/DECISIONS.md)
- [Testing](docs/TESTING.md)
