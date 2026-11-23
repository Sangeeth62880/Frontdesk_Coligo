# Frontdesk final audit — 22 November 2026

The initial findings below were reported before application fixes. This document preserves that audit snapshot, including failed measurements and then-open release checks. Current publication, CI, deployment and hosted verification are recorded in [RELEASE.md](RELEASE.md), which supersedes the delivery-status statements below. Existing tests were not weakened or deleted. Original decisions are preserved with the user's one authorized reassignment line added at release. Evidence under ignored `output/audit/` is local verification output, not committed credentials.

## Findings (first reported before fixes; current status shown)

| ID | Area | Severity | Status | Evidence | Fix |
|---|---|---|---|---|---|
| A01 | Capability authorization | blocker | open (fixed locally; deployed version still affected) | `frontdesk/api.py:agent_view`, `sla_view` spread every ticket column; list and detail expose `customer_token` to any agent. | Remove capabilities from lists and other assignees' details; hide unavailable customer actions; test two-agent isolation. |
| A02 | Input robustness | should-fix | fixed locally | `NoteInput` and `TicketInput` accept U+0000; PostgreSQL text rejects it. No request body byte limit before JSON parsing. | Reject null characters and cap streamed request bytes, including missing/false Content-Length. Add regression probes. |
| A03 | Public abuse | should-fix | fixed locally | `POST /customer/tickets` writes without authentication or throttle. | Add a database-backed, concurrency-safe per-client quota and document proxy handling. |
| A04 | Availability/errors | should-fix | fixed locally | Request `connection()` has no connect timeout/error translation. DB outages raise OperationalError; health can return 500. | Bound connection/query waits, return generic 503 with request ID; test rollback and redaction. |
| A05 | Tooling/coverage | should-fix | fixed locally | `pyproject.toml` only includes pytest/httpx2. No property tests, actual browser automation, static analysis or dependency audit. | Add independent reference/property tests, concurrency replay, schema-generated probes, Playwright/axe, lint/type and vulnerability scans; preserve all existing tests. |
| A06 | Source traceability | should-fix | fixed for supplied build-plan PDF; original transcript unavailable | Initially no PDF found in repository/attachments. User pointed to Downloads; the eight-page build-plan PDF was found, extracted and inspected. It contains summarized requirements rather than the original transcript. | See `docs/TRACEABILITY.md` for the supplied PDF sentence map, incident summaries, Friday-example conflict and exact source limitations. |
| A07 | Reproduction | should-fix | fixed locally | `uv run --env-file .env python -m scripts.verify` fails: TEST_DATABASE_URL absent in existing local env; Docker executable absent. | Use explicit isolated local DB configuration; verify fresh temporary checkout. Record Docker limitation. |
| A08 | Request observability | should-fix | fixed locally | No request IDs or structured request completion records in middleware. | Generate server request IDs, log method/route/status/duration without URL queries or bodies. |
| A09 | Accessibility/browser evidence | should-fix | open (local automation fixed; complete hosted lifecycle pending) | Existing `ui_*.cjs` use VM DOM stubs, not a browser. README explicitly marks manual coverage and unconfirmed CSV. | Run Chromium, axe and responsive screenshots, fix reproduced defects and add CI command. |

## Verification policy

Runtime tests use fresh UUID-named schemas and do not alter demo records. Hosted checks are read-mostly, synthetic mutations must use explicit labels. No event row will be updated or deleted. Full suite runs after each application fix batch, with outputs retained. Failures and unavailable checks remain visible.

## Additional findings, reported before remediation

| ID | Area | Severity | Status | Evidence | Fix |
|---|---|---|---|---|---|
| A10 | Customer accessibility | should-fix | open (fixed locally; hosted customer page retest pending) | `output/audit/browser-third.txt`: axe color-contrast failure on eyebrow, hint, ticket number, badge and message timestamps. | Darken customer muted text and badge contrast; retain axe assertion and rerun browser/full suite. |
| A11 | Hosted read capacity | should-fix | open | `output/audit/hosted-verification.json`: 50 virtual users, 5 global reads/sec, 284 requests, 63 errors (45 timeouts, 18 HTTP 502), p95 20.094s including timeouts; 10/10 concurrent creates succeed. | Reduce per-ticket query/write amplification in SLA reads; run local load. Hosted deployment/retest remains explicit pending work; do not claim a local fix changed the deployed service. |
| A12 | OpenAPI response detail | nice-to-have | open | Most endpoint functions lack response models, producing unconstrained success schemas. Request-body schemas and auth are exercised by generated probes, but response contracts cannot fully validate field types from OpenAPI. | Add response models in a future contract-focused change; current privacy allowlist and behavioral tests remain authoritative. |

A01 follow-up: the initial local fix still allowed an agent to acquire another owner's capability by reassigning that ticket to themselves. Final review found this bypass before release. Reassignment now requires the current assignee (403 otherwise), accepts only active targets, and records the same immutable old/new assignment event. Existing Decisions did not grant arbitrary transfer authority and were not edited. The two-agent regression tests the bypass explicitly. Previously shared capabilities still cannot be recalled without the separately deferred rotation feature.


## Scope and verification evidence

The audit started from clean `codex/frontdesk` at `de3f6306a5043b718c29648f34ee2688e091a16c`. No pre-existing user changes were overwritten. Changes remain local/uncommitted; no push, release or history rewrite was performed. `docs/DECISIONS.md` is byte-for-byte unchanged relative to HEAD. Existing tests were retained: lint edits changed import order, unused bindings, UTC aliases and equivalent nested context syntax; no assertion was weakened or deleted. New tests were corrected when their first assumptions about the UI/quota/event loop were wrong; the failed outputs are retained and raw temporary session material is redacted.

### A. Requirements

See [TRACEABILITY.md](TRACEABILITY.md). All normative sentences in the supplied extracted-requirement sections are mapped to behavior/code/tests, with explicit no-test flags for optional or non-executable statements. Targets are urgent 120/end-of-start-day, medium 270/1620, small 540/2700. Calendar, no-weekend/no-holiday work, waiting pause, uninterrupted auto-close, inclusive reopen, public-vs-team notes, all three incidents and immutable events have executable coverage. The supplied PDF's Friday-18:00 example conflicts with its own window and frozen Decisions; the existing code decision was retained. The original verbatim meeting/incident documents are unavailable, so completeness against those originals is not claimed.

### B. Security

- Auth inventory is `output/audit/routes.json`; README/API tables also cover public shells `/`, `/customer`, `/health`, `/static/*`, `/docs`, `/redoc`, `/openapi.json`. Dynamic tests cover every agent route and all tagged customer routes. Actors derive from the DB session behind a bearer token; forged X-Agent-Id is ignored. Header authentication does not mean trusting an agent identity supplied in a header.
- Login tokens are fresh random 32-byte values, hashed in storage, absolute 12-hour expiry, revoked on logout and rejected after logout/expiry/inactive agent. No cookie authentication/CORS allowlist exists; cross-origin requests receive no Access-Control-Allow-Origin. Sessions are per-tab sessionStorage, with no identity/token in agent URLs. Customer capability links deliberately use a fragment, scrub it on load and use sessionStorage thereafter; this pre-existing decision is not a promise of token expiry/rotation. Previously shared capabilities cannot be revoked by changing ownership.
- Capability isolation now omits tokens from all agent lists and other/unassigned details. Only current assignees transfer ownership, preventing transfer-to-self from bypassing this check. Initial agent creation returns its own newly created capability. Customer X/Y and linked-chain isolation, sequential/huge/negative ID probes and capability mutation via extra fields are tested.
- SQL AST review found no user-text interpolation. The one concatenated runtime SELECT uses an enum-to-fixed-SQL lookup for assignee filters and parameterizes actor IDs. Provisioning uses psycopg Identifier/Literal; migration SQL is trusted checked-in text. See `static-analysis.json` for every nonliteral execute call. No SQL-input-driven identifier or clause was found.
- Stored subject/body XSS is inert in Chromium; both renderers escape text/errors; search filtering uses local text and no server echo. The browser's subject/title/RTL/emoji/combining text and message payload cause no JS execution/network fetch. CSV uses an explicit allowlist and formula-prefix neutralization, including leading whitespace. Header filenames are constant. Static traversal, CORS and open-redirect probes pass.
- Custom secret scan covers tracked/untracked nonignored source, every reachable historical Git blob and output text; it compares configured secrets plus common private-key/GitHub/AWS/nonlocal credential-URL patterns without printing matches. Final report: `secret-scan-final.json`. `.env` is ignored; `.env.example` uses documented localhost sample credentials/placeholders. No configured demo password or common secret pattern was found. This is a scoped pattern/literal scan, not a guarantee that every possible unknown secret can be detected; gitleaks was unavailable.
- Intake quota is DB-backed and serialized by an atomic upsert: default 10 accepted creations per resolved client IP in a ten-minute window. Concurrent overflow returns 429/Retry-After and creates no tickets. Forged X-Forwarded-For cannot choose a new bucket inside the app. Proxy address resolution is delegated to Uvicorn's configured trusted proxies; shared/untrusted proxy quotas can be coarse. Login throttle's cross-process/count/lockout tests remain intact.
- Streamed bodies are capped at 65,536 bytes before parsing, regardless of Content-Length; subjects max 300, messages max 10,000, email max 320 with a basic syntax pattern, nulls rejected. Email deliverability is not checked.
- CSP, nosniff, DENY/frame-ancestors, no-referrer and private/no-store are tested. Hosted HTTP→HTTPS returned 301; HTTPS health and shells returned 200 with security headers. HSTS was not observed. Default interactive API docs deliberately have a different CSP treatment; no unsafe HTML rendering is used in application pages.
- `pip-audit` and `npm audit` report zero known vulnerabilities. Python direct dependencies use compatible ranges; exact installed versions are locked in uv.lock. npm axe-core is exact and package-lock is committed source. Security scan tools themselves are dev-only; Docker uses `uv sync --locked --no-dev`.
- Fresh local migrations preserve all three event triggers; rerunning the migration runner changes neither migration names nor seeds. Runtime tests verify no superuser/create-role/create-db inheritance, no events UPDATE/DELETE/TRUNCATE, successful permitted mutations/auth/logout, and no API password hashes. Hosted DB role/trigger recheck is still pending workspace confirmation; local proof is not substituted for deployed proof.

### C. Integrity/concurrency

DB checks cover FKs, NOT NULL, enum/status/priority constraints, author-agent consistency, cycle >=1, pause order and unique open pause. Public/internal visibility is represented by separate tables rather than a visibility column; intake source is validated at the API and recorded as event metadata rather than a source column. Thirty concurrent successful creations have unique increasing consecutive IDs in their fresh schema. PostgreSQL sequences may legitimately have gaps after rollbacks; no gapless numbering guarantee is claimed.

Seeded stress mixes claim/status, priority/reply, resolve/customer reply and reopen/sweep. Existing tests cover simultaneous claims, duplicate replies/idempotency, competing status versions, concurrent login failures, parallel reopen and both reply/auto-close lock orders. Double logout accepts 200/401 without a 500. Event replay compares status, priority, assignee, first reply timestamp, cycle number, linked parent, message/note IDs and active pause membership for every stress ticket. It does not reconstruct secrets/subject/email or all read-materialized breach flags from events, because those are intentionally not fully stored in the event payload. `test_event_failure_rolls_back_entire_mutation` forces an event insert error and verifies state/messages/events roll back together. Shutdown during an active sweep is explicitly held inside its transaction, then released while stop joins; it commits exactly once and leaves no worker running.

All persisted timestamp columns inspected are timestamptz; full suites run in UTC, Asia/Kolkata and America/Los_Angeles with the app hosted on a local HTTP port for browser flows. Leap day, IST offset stability, Dec 31→company Jan 1 holiday and last-seed range failure are tested.

### D. Business-time fuzzing

`test_audit_properties.py` runs **2,000 deterministic Hypothesis examples**, independently normalizing and stepping minute by minute without production Calendar calls in the reference. It randomizes arrivals, holiday sets, duration and one closed pause; checks deadline order/window, target+paused-working-minute equality, stricter-duration monotonicity, and reopen/auto-close monotonicity. Existing tests add multiple/open/weekend/overlap/reversed pauses and all three policy semantics; randomized multi-pause/urgent-mode reference generation is not claimed. Boundary tables include 2699/2700/2701, 119/120/121, opening/closing edges, consecutive Friday/Monday holidays and weekend pauses. Separate raw run is `properties.txt`.

### E. Contract/robustness

150 requests are generated from the actual OpenAPI request component schemas using hypothesis-jsonschema and submitted to the test API; no 500 is accepted, extra fields must return 422. These are authenticated generated requests, not a complete Schemathesis state machine or an exhaustive proof of response-schema conformance. Success schemas remain underspecified (A12); business validation can reject a JSON-schema-shaped body with 422. Explicit wire tests cover wrong media, malformed JSON, JSON scalars, long/Unicode/null subjects/bodies, duplicate Authorization headers, huge/negative IDs and same-origin trailing-slash redirects. Existing tests cover missing/stale versions, same/different/expired idempotency keys and parallel replay.

Errors retain a detail envelope with documented string/object/validation-list variants; 401/403/404/409/413/422/429/503 are exercised. DB failures produce generic 503/Retry-After with a server request ID; logs omit SQL/DSNs/bodies. Connection establishment is bounded at five seconds, statements at ten seconds by default. Unconfigured required startup settings fail before migrations. Actual slow-network startup fault injection is not performed; connection-refusal/failure and already-migrated startup are covered.

### F. Real browser

`tests/test_audit_browser.py` uses headless Chromium against an isolated migrated PostgreSQL stack. Local flows: successful/wrong/locked login, expired 401, list late ordering, search/status filter, detail, two contexts competing for claim with loser owner name, public/internal toggle, required public waiting question, real customer answer and simulated answer, priority timeline, resolve/reopen, no private note in customer view, real CSV download/content, logout/back, j/k/Enter, Tab containment and Esc/focus return in the create dialog. Login's modal deliberately refuses Esc. Screenshots at 390/768/1280 are saved for list/ticket under `output/screens/`; page-level horizontal overflow is asserted. Final screenshot review found the tablet table hid the Late column behind internal scrolling. The card layout now applies through 1100px and places resolution/Late on a dedicated row; tests include an actual Waiting ticket and assert no table-container overflow plus on-screen Late text at every viewport.

Axe WCAG A/AA (including 2.1 AA tags) passes on login/list/ticket/customer; customer muted/badge colors were darkened after a reproduced contrast failure. Automated axe is not a complete manual accessibility audit. Main successful flow records zero JS errors, console errors and failed network requests in `browser-errors.json`. Negative login/claim flows intentionally generate refused HTTP 401/429/409 responses; those are expected and are not claimed as zero HTTP errors.

Hosted browser coverage is login/list/logout, axe list, three viewport screenshots and page overflow checks. It recorded zero JS errors. The full local lifecycle has not been repeated against the final deployed code, which is still the old release.

### G. Hosted environment/load

`hosted-public.json`: warm first health 0.256s; health/root/customer 200; HTTP health 301 to HTTPS; unauthenticated POST /admin/sweep 401. This does not establish an idle cold-start latency or one-week uptime.

`hosted-verification.json`: 50 virtual readers scheduled for 60 seconds, global ceiling five reads/sec, 284 requests including drain, 63 errors (45 client timeouts +18 HTTP 502), read p95 **20.094s including timed-out requests**. Ten simultaneous writers each created one labeled ticket: 10/10 success, max/conservative p95 **2.766s**. This is a failed capacity test, not a pass.

Local optimized stack, same 18-ticket baseline and five reads/sec: 300 reads, zero errors, read p95 **0.0525s**; 10 writers, zero errors, conservative write p95 **0.1276s** (`local-load.json`, `local-load.txt`). It supports the local change but cannot predict Render performance. List reads retain ticket locks and sticky breach semantics, prefetch calendar/policies/histories and skip unchanged materialized writes; a 25-ticket regression asserts at most eight SQL calls and no UPDATE on unchanged reads.

Synthetic hosted tickets **9–18** were created by the documented `scripts.audit_hosted` command as `Hosted verification: agent audit 2026-11-22 #NN`. Their append-only events remain; no ticket renames/deletions or event UPDATE/DELETE occurred. The deterministic six-case seed (`scripts.seed_review_demo`) is tested for fresh schemas only. We did not reseed the shared hosted schema or pretend that current API creation can backdate records.

Render MCP has no selected workspace. A workspace confirmation question is pending; its access policy forbids silently choosing one. Consequently hosted role/trigger and in-process sweep logs were not checked. GitHub schedule run 45019224631 is “success” but **the actual Close expired customer waits step was skipped**; no working external scheduled sweep is established. Existing README's missing-sweep-secrets caveat is therefore material.

### H. Quality/reproducibility/docs/git

Initial static results: 54 lint findings; type checking initially could not resolve duplicate script modules, then reported 40 type errors. Final ruff is clean and mypy with `--check-untyped-defs --explicit-package-bases` reports no issues in 18 source files. Dynamic dictionaries remain broadly typed; this is not strict end-to-end typing. No TODO/FIXME/debug markers or tracked files above 1 MB were found. AST SQL inventory and every documented test reference were checked (`static-analysis.json`); no missing test names. Request logging emits only server ID, method, route template, status and duration; startup disables Uvicorn URL access logs to avoid query-token leaks. Sweep failure logs expose only exception type.

Fresh temporary source copy excluded .git/.env/.venv/node_modules/output, created a clean venv with `uv sync --locked`, installed npm lock, checked Chromium availability and ran the complete suite successfully. Local PostgreSQL and existing download/browser caches were reused. Docker is not installed, so Docker Compose/image build and a fresh OS/container are unverified here. The initial local .env lacked TEST_DATABASE_URL; runs explicitly supplied the configured local DB URL as TEST_DATABASE_URL without printing it. README now requires npm/browser setup and clearly says to edit env before verification. `reproduction-final.txt` records each step (226 passed). That clean-venv snapshot preceded the last responsive CSS and shutdown-test additions; final complete-suite files exercise those additions with the same unchanged dependency locks.

All checked local doc links exist and all external doc links returned 200 (`doc-links.json`). GitHub main at de3f630 has successful [Tests run 45042633633](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45042633633) (`ci-main.json`). This verifies the earlier published commit, not current local edits. New CI steps prepare Chromium/axe/lint/types/audits/artifact upload, but remote CI and a new Docker build have not run on these changes. output/, caches, secrets and generated screenshots are ignored. The working tree intentionally contains the audit edits; clean submission history/push is pending the user's release workflow.

## Remaining release/assurance work

| ID | Area | Severity | Status | Evidence | Required next step |
|---|---|---|---|---|---|
| A13 | Hosted runtime/automatic sweep | should-fix | open | No Render workspace selected; confirmation pending. GitHub sweep step skipped. | Confirm intended workspace, recheck deployed role/triggers and in-process sweep; configure external scheduled sweep if relying on it. |
| A14 | Cold start/uptime | nice-to-have | open | Only warm response timing observed; no future uptime evidence. | Observe idle cold start and the required submission week; maintain free-tier DB lifecycle. |
| A15 | Responsive Late/Waiting visibility | should-fix | fixed locally; hosted retest pending | Final screenshot review showed the 768px table could hide the Late column behind internal scrolling. | Extended cards through 1100px and gave due/Late its own row; a real Waiting row and container/bounding-box assertions cover all three widths. |

A01, A09, A10 and A11 retain open hosted status. Deployment and post-deploy security/load/full-lifecycle checks are necessary before calling this submission ready. A12 (complete OpenAPI response/security contracts), strict typing, customer capability expiry/rotation, pooling/pagination and an external tamper-proof audit sink remain explicit future work. The lack of raw original meeting/incident documents limits source-completeness assurance.

## Residual-risk paragraph for submission

See the single paragraph under “Residual risk — submission draft” in [SUBMISSION.md](../SUBMISSION.md). It explicitly names the unshipped fixes and failed hosted load instead of claiming readiness.



## Final output index

All final complete-suite runs below have **227 passed, zero skipped, zero warnings**. They include real Chromium, generated requests, the 2,000-case reference test and the shutdown-during-sweep regression. Exact terminal output is retained, rather than only this summary.

| Run | Terminal result | Evidence |
|---|---|---|
| full_utc | `227 passed in 182.48s (0:03:02)` | `output/audit/complete-suite-utc.txt` |
| full_kolkata | `227 passed in 183.05s (0:03:03)` | `output/audit/complete-suite-kolkata.txt` |
| full_los_angeles | `227 passed in 183.65s (0:03:03)` | `output/audit/complete-suite-los-angeles.txt` |
| playwright | `3 passed in 11.01s` | `output/audit/browser.txt` |
| properties | `8 passed in 12.23s` | `output/audit/properties.txt` |
| clean_venv_reproduction | `226 passed in 124.09s (0:02:04)` | `output/audit/reproduction-final.txt` |

The standalone property run is eight pytest cases with 2,000 generated examples inside its main case. Static output: ruff “All checks passed!”, mypy “Success: no issues found in 18 source files”. pip-audit reports “No known vulnerabilities found”; npm reports zero vulnerabilities at all severity levels. The custom final secret scan reports 260 scanned worktree/history/output items, no matches, .env ignored and only .env.example tracked. A second literal scan also compared the actual hosted demo password (fetched into memory only) and found no matches; see `hosted-demo-secret-scan.json`. The earlier failed/partial test runs are retained for transparency; they are not counted as passes.

Machine-readable rollup: `output/audit/summary.json`. Individual outputs also include `local-load.json`, `hosted-verification.json`, `hosted-public.json`, `axe-*.json`, `browser-errors.json`, `static-analysis.json`, `doc-links.json`, `routes.json`, `ci-main.json` and `github-sweep.json`. The verified runtime/test source hashes are recorded in `source-manifest.json`. Scoped scan source is copied to `output/audit/secret-scan-source.py` and `static-scan-source.py` for repeatability. Screenshots are under `output/screens/`. These generated artifacts stay ignored and contain no real demo password or bearer token.

Published code still needs release/retest. No claim is made that all hosted blockers have been fixed merely because local tests pass.

## Release follow-up — 23 November 2026

See [RELEASE.md](RELEASE.md) for the explicitly authorized release. Agent list/detail now always omit customer_token; the assignee-only customer-access endpoint supports customer actions. HSTS, successful sweep heartbeat logging and fail-closed internal runtime-role/trigger verification were added for hosted verification. The only change to DECISIONS.md is the user's permitted single reassignment line. Earlier unshipped/hosted-failure observations above remain historical evidence, not the final release status.

## Live-site fixes — ordered verification, 23 November 2026

The subsequent user request supersedes the earlier one-line-only documentation limit: existing DECISIONS.md content remains byte-for-byte intact, with append-only clarifications. Steps 1–5 passed their full suites before the Late report was implemented. No tests were removed or weakened; existing fixtures now explicitly claim tickets before owner-only actions and supply the required description.

| Step | Full suite | Local evidence |
|---|---|---|
| 1 — resolve/priority ownership, no rejected mutation/event | 229 passed | output/live-fixes/step1-rerun.txt |
| 2 — transactional public resolution, idempotent retry | 231 passed | output/live-fixes/step2.txt |
| 3 — required public customer description, clock/privacy/XSS checks | 244 passed | output/live-fixes/step3-rerun.txt |
| 4 — coherent seed timelines, narrow owner seed timestamp exception, immutable events | 247 passed | output/live-fixes/step4-rerun.txt |
| 5 — inline waiting, exhaustive event labels, uniform customer-token 401 | 249 passed | output/live-fixes/step5-rerun.txt |
| 6 — Late targets, working-time overshoot and private CSV | 252 passed in 149.80s | output/live-fixes/step6.txt |

Every final step run above has zero skips. Earlier failed attempts remain as diagnostics. Step 6 initially found real mobile overflow; the agent stylesheet and wrapping toolbar were fixed, retaining the responsive assertions. Ruff, mypy and JavaScript syntax checks pass. The new tests cover owner and non-owner paths, unassigned triage, retry event counts, customer visibility, first reply and clock independence, every seed timeline, owner/runtime timestamp behavior, trigger immutability, CSV formulas/privacy and historical breach retention through priority changes and reopen.

Both required GitHub Actions secret names are present (metadata checked without values): FRONTDESK_BASE_URL and FRONTDESK_SWEEP_TOKEN. Workflow dispatch and a non-skipped sweep remain to be verified. Release CI, Docker build, deployment, hosted load/browser checks, the final schema reset and password rotation are pending; this local evidence does not establish those outcomes. No Render cron service is planned. The hosted SQL allowlist remains closed; runtime startup verification provides internal privilege/trigger evidence. Natural 12-hour expiry, live lockout, cold-start latency and one-week uptime remain unverified on the hosted service.

Step 7 full suite: **252 passed in 145.10s**, zero skipped (`output/live-fixes/step7.txt`). Step 8 dispatched [run 45097076317](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45097076317) against the existing hosted release after both repository secrets were configured. Job 137439154918 and its **Close expired customer waits** step concluded success, not skipped. The workflow uses only the two named secrets; no Render cron was added.

### Hosted release retry: connection pressure

Release commit fffd558 passed [CI 45097756013](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45097756013): **256 passed in 54.38s**, zero skips, audits/static checks and Docker image build successful. Render deploy dep-dc1pu2l9fdbs73bhk5fg became live. Startup verified the actual restricted runtime role and all three enabled event triggers, with successful in-process sweep logging. Header checks passed including HSTS; all 52 list rows and all 52 details for each of Meera and Arun omitted customer_token, and the Late CSV passed privacy/cache checks.

The first convenience browser precheck timed out before reaching the load section; no load result is attributed to that attempt. The separate load run used 50 virtual readers, a 60-second scheduling window and global ceiling five reads/sec, with ten concurrent creates. At the **52-ticket baseline**, 300 reads had p95 **7.207s**, **one HTTP 503** (299 HTTP 200); actual duration including drain was 62.208s. All ten writes succeeded, conservative writer p95 **2.941s**. Server logs show a QueryCanceled error at 10.275s for the 503; the exact timed-out SQL statement is not exposed. This is a failed capacity check, not a pass.

The full browser then failed its unchanged claim-confirmation assertion. Source inspection found refresh fetching every ticket's events concurrently, and hosted logs recorded a burst of ConnectionTimeout errors with 63 tickets/two sessions. **Should-fix:** bound event fetches to four at a time. A regression executes the shipped refresh with 64 tickets and asserts every event read completes once, peak concurrency ≤4, and every activity timestamp equals the latest actual event. Existing endpoint, activity source, error and lifecycle assertions remain unchanged. This addresses browser connection pressure; it does not by itself establish API load capacity. Earlier failed outputs remain under output/live-fixes/.
