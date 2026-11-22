# Frontdesk submission

The audited application is published to GitHub main and live on Render in Sangeeth's workspace. Current release evidence is recorded in [docs/RELEASE.md](docs/RELEASE.md).

- Live: [frontdesk-spfe.onrender.com](https://frontdesk-spfe.onrender.com)
- Repository: [Sangeeth62880/Frontdesk_Coligo](https://github.com/Sangeeth62880/Frontdesk_Coligo)
- Demo logins: `meera@arvo.example`, `arun@arvo.example`, `divya@arvo.example`; the demo password is supplied with the submission.
- Demo mode seeds synthetic tickets and these three accounts, and shows a login hint only when enabled; the remaining agents require administrator password provisioning.
- Local setup: [README.md](README.md).

## Verification

The audit adds real Chromium/axe, native CSV download, property/reference checks, OpenAPI-generated request fuzzing and event replay. [Release CI](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45056188460) passed 228 tests without skips, static checks, dependency audits and the Docker build. Hosted checks confirmed token-free agent list/detail responses, restricted runtime privileges, immutable event triggers, sweep heartbeat logging and security headers including HSTS. The repeated hosted load test had zero errors across 300 reads and ten creates; read p95 was 1.235 seconds and conservative writer p95 was 2.588 seconds. The full hosted Chromium lifecycle passed, with zero axe violations, JavaScript errors or failed requests on its final run. Earlier browser failures and remaining limitations are recorded in [docs/RELEASE.md](docs/RELEASE.md). Initial audit findings remain in [docs/AUDIT.md](docs/AUDIT.md).

## Residual risk

Local tests exercise SLA/calendar edges, immutable audit storage, claims, privacy, abuse limits, API fuzzing and Chromium accessibility. Hosted security and load checks pass after deployment; the earlier failed load result is retained as historical evidence. Existing demo history and clearly labeled verification tickets remain intact; the six-case deterministic seed is available for a fresh schema. Customer capabilities still have no expiry/rotation, account recovery/MFA and an external tamper-proof audit sink remain outside scope, holiday data stops at 25 December 2027, and idle cold-start latency and a future week of uptime are unproven. Natural 12-hour expiry and lockout were not induced on live accounts. The external database allowlist remains closed; actual runtime privileges and triggers were checked through the internal startup connection. Ongoing hosting/calendar maintenance remains necessary.

Deployment caveats: [docs/DEPLOY.md](docs/DEPLOY.md). Frozen decisions: [docs/DECISIONS.md](docs/DECISIONS.md). API: [docs/API.md](docs/API.md).
