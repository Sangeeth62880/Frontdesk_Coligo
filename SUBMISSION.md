# Frontdesk submission

The application is live on Render and published to GitHub; CI, Docker build, hosted API checks and a manual browser workflow are verified.

- Live: [frontdesk-spfe.onrender.com](https://frontdesk-spfe.onrender.com)
- Repository: [Sangeeth62880/Frontdesk_Coligo](https://github.com/Sangeeth62880/Frontdesk_Coligo)
- Demo logins: `meera@arvo.example`, `arun@arvo.example`, `divya@arvo.example`; the demo password is supplied with the submission.
- Demo mode seeds synthetic tickets and these three accounts, and shows a login hint only when enabled; the remaining agents require administrator password provisioning.
- Local setup: [README.md](README.md).

## Verification

The suite passes **195 tests, zero skipped**. [CI](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45034482014) passed the suite, JavaScript checks and Docker image build. Hosted API checks covered both ticket sources, concurrent claims, assignee-only public replies, privacy, wait/resume, priority, resolution, reopen, CSV and logout. A manual browser pass covered the main workflow and the dedicated Take this ticket button. CSV content passed API checks; native browser download completion remains unconfirmed. Details and historical checkpoints are in [docs/TESTING.md](docs/TESTING.md).

## What I did not finish

- Free-tier cold starts remain; sweeps depend on the awake service or the optional GitHub schedule, whose repository secrets still need configuring.
- Password reset/change UI, MFA, SSO and session listing are not implemented.
- No authenticated customer portal or token delivery; the customer conversation page uses a capability token.
- Pagination and database connection pooling are not implemented.
- No audit hash chain; database triggers and restricted privileges protect append-only events.
- Holiday seeds end December 25, 2027 and need extending.
- Real-browser tests are manual, not automated; native CSV download completion remains unconfirmed.
- One-week uptime has not yet been observed; the free database expires on December 22, 2026 at 19:56 IST.

Deployment and operational caveats: [docs/DEPLOY.md](docs/DEPLOY.md). Full decisions: [docs/DECISIONS.md](docs/DECISIONS.md). API contracts: [docs/API.md](docs/API.md).
