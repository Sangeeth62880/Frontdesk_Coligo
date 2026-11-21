# Frontdesk submission

Status: application implemented and verified locally; publication pending account access.

- Live URL: pending deployment.
- Repository URL: pending repository publication.
- Local run instructions and decisions: [README.md](README.md).
- Access: the deployment administrator supplies the team demo key separately. Select any of the nine seeded agents after entering it. Demo tickets belong to Meera, with one unassigned ticket.

## What I did not finish, and why

I used a shared team key and a seeded agent picker rather than implementing individual accounts, password recovery or roles. I prioritized working-time SLAs, safe ticket ownership, private-note isolation and a permanent audit trail. Before production, I would replace demo access with individual authentication and introduce customer-link expiry and rotation.

I did not add pagination, a connection pool, email delivery or audit hash chaining. The fictional team's volume is small and these were lower priority than the required workflows and incident protections. Existing events are protected by database triggers; the deployment bootstrap also restricts the application's database privileges.

The UI, customer-safe view, demo seed, automatic sweep worker, container definition and deployment configuration are implemented. Public hosting, repository publication, the final hosted browser pass and one-week availability verification are still pending account access. Those are outstanding submission requirements, not completed work. The Docker image and hosted CI workflows have not run in this local environment.

## Verification checkpoint

- PostgreSQL regression suite: 75 tests passed, none skipped.
- JavaScript syntax checks passed.
- Local browser: create, two-agent claim conflict, public reply, internal note, wait/resume, priority change, resolve, customer reopen and timeline verified.
- Customer page excludes the private browser-test marker; API tests also cover all customer endpoints and event payloads.
- CSV payload verified by API tests. Native download completion was not confirmed by the in-app browser's download-event bridge.
- Agent and customer layouts inspected at a 390px viewport; no horizontal overflow.
- Runtime role has no superuser/create-database/create-role privileges and no UPDATE/DELETE permissions on events.

Before sending: fill the two URLs, repeat the manual browser pass on the deployed application, share the demo key with the reviewer, update this note to match the final state, and record the hosting expiration date. This note was drafted with Codex and should be reviewed by Sangeeth.
