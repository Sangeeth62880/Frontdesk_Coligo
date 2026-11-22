# Frontdesk submission

The earlier application is live on Render and published to GitHub. This local final-audit branch has additional fixes that are not yet published or deployed.

- Live: [frontdesk-spfe.onrender.com](https://frontdesk-spfe.onrender.com)
- Repository: [Sangeeth62880/Frontdesk_Coligo](https://github.com/Sangeeth62880/Frontdesk_Coligo)
- Demo logins: `meera@arvo.example`, `arun@arvo.example`, `divya@arvo.example`; the demo password is supplied with the submission.
- Demo mode seeds synthetic tickets and these three accounts, and shows a login hint only when enabled; the remaining agents require administrator password provisioning.
- Local setup: [README.md](README.md).

## Verification

The local audit adds real Chromium/axe, native CSV download, property/reference checks, OpenAPI-generated request fuzzing and event replay. Full outputs, load metrics and exact remaining checks are in [docs/AUDIT.md](docs/AUDIT.md). The existing linked [CI run](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45034482014) covers the earlier published commit; it does not prove these uncommitted local changes. Updated CI commands are prepared but have not run remotely.

## Residual risk — submission draft

Local tests exercise SLA/calendar edges, immutable audit storage, claims, privacy, abuse limits, API fuzzing and Chromium accessibility, but the audit fixes are not yet deployed. The current hosted version still exposes customer capabilities to other agents and the paced hosted read test had 63 errors in 284 requests, so a deploy followed by hosted security/load/lifecycle retesting is required before claiming readiness. I preserved existing demo history and left verification tickets 9–18 clearly labeled; the six-case deterministic seed is available for a fresh schema. Customer capabilities still have no expiry/rotation, account recovery/MFA and an external tamper-proof audit sink remain outside scope, holiday data stops at 25 December 2027, and a future week of uptime is unproven. These were deferred to preserve the tested core workflow; the next steps are deployment/retest, operational access checks and ongoing hosting/calendar maintenance.

Deployment caveats: [docs/DEPLOY.md](docs/DEPLOY.md). Frozen decisions: [docs/DECISIONS.md](docs/DECISIONS.md). API: [docs/API.md](docs/API.md).
