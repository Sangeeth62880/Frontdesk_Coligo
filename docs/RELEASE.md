# Audited release — 23 November 2026

The user authorized committing the audit in security, robustness, tests/tooling and documentation chunks, pushing to main, then deploying to Sangeeth's workspace. Release commits use `[skip render]` to keep the existing commit-triggered service from deploying before CI completes. A manual deploy follows successful CI.

## Release adjustments

- Every agent list/detail response omits `customer_token`, including the current assignee's detail. The separate authenticated `GET /tickets/{id}/customer-access` endpoint returns a capability only to the current assignee; customer actions use this endpoint. The security test retains ownership/transfer checks and adds universal detail absence assertions.
- HSTS (`max-age=31536000`, without preload/includeSubDomains) is emitted on Render or HTTPS responses. HTTP local development does not set it.
- Every successful in-process sweep emits structured `auto_close_sweep` logging, including zero closures.
- Startup verifies the actual restricted request role through its internal DB connection and refuses to serve if it has elevated privileges, owns events, can mutate/delete/truncate events, or required event triggers are missing/disabled. Logs contain only safe privilege/trigger evidence.
- `docs/DECISIONS.md` has exactly one authorized added line: “Reassignment requires the current assignee.” No previous decision text was edited.

## Evidence and limits

Local release evidence is retained under ignored `output/release/`. Initial security/robustness verification passed 228 tests, zero skipped. The final pre-commit run also includes the internal runtime-verifier assertions. Ruff and mypy run over the application/scripts/tests; no test is removed or weakened. `.env`, `output/`, caches and generated assets remain ignored. `.env.example` contains documented placeholders/local sample credentials. The pre-release literal/pattern secret scan found no matches across 316 source/history/output items.

Render's SQL connector cannot reach the database because external connections are blocked. This release does not weaken that allowlist; startup verification uses the actual internal request connection and can be confirmed from deployment logs. The previous audit's hosted load failure remains historical evidence until a new hosted measurement is recorded. Natural 12-hour browser expiry and lockout on live demo accounts are not induced by the hosted lifecycle script; local deterministic tests cover them, and hosted revocation exercises the same 401 UI path.

CI/deployment and hosted outcome will be added after verification. Earlier audit counts and “not deployed” statements in AUDIT.md/SUBMISSION.md are historical until this release completes; this release record takes precedence for current delivery status.
