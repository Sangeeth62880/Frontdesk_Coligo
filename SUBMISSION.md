# Frontdesk submission

Status: application implemented and verified locally; publication pending account access.

- Live URL: pending deployment.
- Repository URL: https://github.com/Sangeeth62880/Frontdesk_Coligo.
- Local run instructions and decisions: [README.md](README.md).
- Access: sign in with meera@arvo.example, arun@arvo.example or divya@arvo.example and the configured FRONTDESK_DEMO_PASSWORD in demo mode. The other six agents require administrator password provisioning. Demo tickets belong to Meera, with one unassigned ticket.

## What I did not finish, and why

Individual agent authentication is implemented with salted scrypt password hashes and hashed bearer sessions, a fixed 12-hour lifetime, logout revocation and database-backed login throttling. Acting identity comes from the session. Password reset, password change UI, MFA, SSO, per-customer login and session listing remain unimplemented. Customer-capability expiry, rotation and delivery also remain unfinished.

I did not add pagination, a connection pool, email delivery or audit hash chaining. The fictional team's volume is small and these were lower priority than the required workflows and incident protections. Existing events are protected by database triggers; the deployment bootstrap also restricts the application's database privileges.

The UI, customer-safe view, demo seed, automatic sweep worker, container definition and deployment configuration are implemented. Public hosting, repository publication, the final hosted browser pass and one-week availability verification are still pending account access. Those are outstanding submission requirements, not completed work. The Docker image and hosted CI workflows have not run in this local environment.

## Verification checkpoint

- PostgreSQL hardening and authentication proof: see output/auth-step-7.txt for the final full-suite result, with no skipped coverage; run `TEST_DATABASE_URL=… uv run python -m scripts.verify`.
- Phases 0–5, requirement-to-test mapping, corrected Friday reply arithmetic, and all test assumptions are recorded in README. No Phase 0 decision deviations.
- HTML smoke and login lifecycle checks execute shipped JavaScript with Node DOM/network sinks; no new real-browser/Playwright or hosted pass was performed.
- JavaScript syntax checks passed.
- Earlier local browser baseline (before hardening): create, two-agent claim conflict, public reply, internal note, wait/resume, priority change, resolve, customer reopen and timeline verified.
- Customer page excludes the private browser-test marker; API tests also cover all customer endpoints and event payloads.
- CSV payload verified by API tests. Native download completion was not confirmed by the in-app browser's download-event bridge.
- Agent and customer layouts inspected at a 390px viewport; no horizontal overflow.
- Runtime role has no superuser/create-database/create-role privileges and no UPDATE/DELETE permissions on events.

Before sending: fill the two URLs, repeat the manual browser pass on the deployed application, share the demo login emails and configured password with the reviewer, update this note to match the final state, and record the hosting expiration date. This note was drafted with Codex and should be reviewed by Sangeeth.
