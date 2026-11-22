# Frontdesk submission

Status: application live on Render and published to GitHub. Hosted CI, Docker build, API checks and browser workflow verified; one-week availability remains to be observed.

- Live URL: https://frontdesk-spfe.onrender.com.
- Repository URL: https://github.com/Sangeeth62880/Frontdesk_Coligo.
- Local run instructions and decisions: [README.md](README.md).
- Access: sign in with meera@arvo.example, arun@arvo.example or divya@arvo.example and the configured FRONTDESK_DEMO_PASSWORD in demo mode. The hosted login form shows the generated demo password; it differs from the local preview password. The other six agents require administrator password provisioning. Demo tickets belong to Meera, with one unassigned ticket.

## What I did not finish, and why

Individual agent authentication is implemented with salted scrypt password hashes and hashed bearer sessions, a fixed 12-hour lifetime, logout revocation and database-backed login throttling. Acting identity comes from the session. Password reset, password change UI, MFA, SSO, per-customer login and session listing remain unimplemented. Customer-capability expiry, rotation and delivery also remain unfinished.

I did not add pagination, a connection pool, email delivery or audit hash chaining. The fictional team's volume is small and these were lower priority than the required workflows and incident protections. Existing events are protected by database triggers; the deployment bootstrap also restricts the application's database privileges.

The UI, customer-safe view, demo seed, automatic sweep worker, container definition and deployment configuration are implemented. The repository is published. The approved Render plan deployed commit d547358 to https://frontdesk-spfe.onrender.com, with a free Docker web service and PostgreSQL 17 database in Singapore. Hosted API and browser workflow checks passed. One-week availability verification remains outstanding; the free database expires on 22 December 2026 at 19:56 IST. The optional GitHub scheduled sweep still requires repository secrets and has not been verified; the application sweeper runs while the free web service is awake. Free-service idle periods are not evidence of a continuously running worker. GitHub CI successfully ran the full suite, JavaScript checks and Docker image build: https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45031110417. A local Docker build was unavailable because Docker is not installed.

## Verification checkpoint

- PostgreSQL hardening, authentication and ticket-source proof: 194 tests passed locally, with no skipped coverage; hosted CI also passed; run `TEST_DATABASE_URL=… uv run python -m scripts.verify`.
- Phases 0–5, requirement-to-test mapping, corrected Friday reply arithmetic, and all test assumptions are recorded in README. No Phase 0 decision deviations.
- Automated HTML/login checks use Node DOM/network sinks. A hosted browser pass separately verified login, default-source creation, claim, public reply, private note, customer privacy/reply, priority, resolution and reopen (cycle 2).
- JavaScript syntax checks passed.
- Earlier local browser baseline (before hardening): create, two-agent claim conflict, public reply, internal note, wait/resume, priority change, resolve, customer reopen and timeline verified.
- Customer page excludes the private browser-test marker; API tests also cover all customer endpoints and event payloads.
- CSV payload verified by local tests and the hosted API. The hosted browser download event timed out, so native download completion remains unconfirmed.
- Agent and customer layouts inspected at a 390px viewport; no horizontal overflow.
- Runtime role has no superuser/create-database/create-role privileges and no UPDATE/DELETE permissions on events.

Before sending: share the demo login emails and password with the reviewer; confirm the required hosting/availability period. Synthetic hosted verification tickets are clearly named and retained for review. This note was drafted with Codex and should be reviewed by Sangeeth.
