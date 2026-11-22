# Testing

## Current verification

The pre-audit suite passed **195 tests, zero skipped**. The expanded final-audit counts and raw evidence are recorded in [AUDIT.md](AUDIT.md); historical counts below are not the current suite size. [Hosted CI](https://github.com/Sangeeth62880/Frontdesk_Coligo/actions/runs/45034482014) also passed the full suite, JavaScript syntax checks and Docker image build. The submission cleanup verification passed `195 passed in 49.30s`. Earlier local output is retained in ignored `output/` files (generated artifacts are not committed). Earlier outputs below are historical checkpoints, not the current suite size.

Database tests require `TEST_DATABASE_URL` and permission to create schemas and temporary restricted roles (CREATEROLE); the runtime permission test removes its temporary role afterward. API tests use committed temporary schemas for independent parallel connections; teardown drops only uniquely named test schemas. Schema tests use rolled-back transactions. Integration tests explicitly skip without that variable; checkpoint verification supplied it and skipped nothing.

## Validation checkpoints

Tests ran at each validation checkpoint, with real PostgreSQL for schema and integration checks:

| Step | Output |
| --- | --- |
| 1. Arrival rules | `30 passed` |
| 2. New reopen-cycle policy | `32 passed` |
| 3. Holiday seeds/range guard | `38 passed` |
| 4. Pause behavior | `42 passed` |
| a. Customer allowlists | `45 passed, 1 warning` |
| b. Privacy leak checks | `47 passed, 1 warning` |
| c. Atomic parallel claims | `51 passed, 1 warning` |
| d. Messages/status/priority | `59 passed, 1 warning` |
| e. Idempotent parallel sweeps | `63 passed, 1 warning` |
| f. Reopen endpoint/history | `68 passed, 1 warning` |

The warning was the installed Starlette test client's deprecated `httpx` fallback. The dev dependency has been changed to its declared `httpx2` dependency rather than suppressing the warning. Final expanded regression output is recorded after verification below.

Incident proof: `test_claims.py` fires independent parallel claims; `test_customer_api.py` checks a unique private marker across every tagged customer endpoint and all event payloads; `test_schema.py` checks PostgreSQL rejection of audit mutations and server-generated timestamps. `test_mutations.py`, `test_sweep.py` and `test_reopen.py` cover transactional lifecycle behavior and retained history. Pure edge cases live in `test_business_time.py`.

## Hardening proof — 22 November 2026

Run **everything**, including the single end-to-end scenario, from one command:

```sh
TEST_DATABASE_URL="postgresql://frontdesk:frontdesk@localhost:5432/frontdesk" uv run python -m scripts.verify
```

The verification database user needs CREATE SCHEMA and CREATEROLE permissions. Tests migrate fresh UUID-named schemas and drop those schemas afterward; they do not clear existing application data. The runner fails if any tests skip, if PostgreSQL is inaccessible, or if Node is unavailable. FastAPI's TestClient uses the pinned `httpx2` transport against the real migrated database, with an injectable operation clock. Audit timestamps intentionally remain PostgreSQL server time. No SQLite substitute or mocked persistence is used. CI runs this same command after setting up Node.

`tests/test_end_to_end.py::test_frontdesk_end_to_end` is the one scripted scenario. It seeds Meera/Arun, holidays and policies via migrations, performs lifecycle and privacy checks, and runs the actual agent render functions for HTML smoke assertions. `test_raw_html_escaped_in_actual_agent_and_customer_renderers` additionally executes the customer renderer. Historical browser workflows were manual. Final-audit Chromium/axe workflows are now automated in `test_audit_browser.py`; npm ci and `uv run playwright install chromium` are required.

**Arithmetic correction:** Friday 17:50 leaves 40 working minutes before 18:30. Urgent first reply has 120 minutes, leaving 80 on Monday: **Monday 10:50**, not 11:20. Resolution remains Friday 18:30. There is no intake cutoff. This corrects the Phase 5 example without changing any Phase 0 decision.

### Phase outputs

Each phase ran the entire suite against local PostgreSQL, with zero skipped tests on its successful checkpoint:

| Checkpoint | Full-suite terminal output | Skipped / uncertain |
| --- | --- | --- |
| Baseline with DB | `75 passed in 8.40s` | None skipped |
| Phase 0 | `79 passed in 10.24s` | No specified trigger for system closure of resolved tickets; sweep closes waiting only |
| Phase 1 | `108 passed in 10.75s` | Phase 5 example corrected to Monday 10:50 |
| Phase 2 | `115 passed in 19.76s` | Thread scheduling is nondeterministic; winner identity is deliberately not asserted |
| Phase 3 | `118 passed in 16.66s` | Search and standalone customer-message routes do not exist; 404 checked |
| Phase 4 | `139 passed in 26.24s` | Node DOM sink for renderer checks; no new real-browser run |
| Phase 5 initial | `140 passed in 33.70s` | No skipped tests |
| Final | `164 passed in 30.72s` | Zero skipped, zero warnings; no Phase 0 deviations |

The initial unconfigured run (`37 passed, 38 skipped`) was replaced by the configured DB baseline above. Phase 0's first run (`1 failed, 74 passed`) exposed an old test asserting that reopen clears ticket lateness; it now asserts permanent breach history. Phase 3's first run (`1 failed, 117 passed`) logged a marker that the test itself placed in its search URL; the corrected test queries ordinary public text while checking that the stored private marker never escapes. These intermediate failures are not hidden or counted as successful checkpoints.

### Rule-to-test coverage

This is a coverage-style requirement map, not a claim of measured line or branch coverage. Names below refer to functions under [tests/](../tests/).

| Incident / rule | Test proving it |
| --- | --- |
| INC-0291: simultaneous claims, one owner/event, loser sees owner | `test_n_claims_one_event`, `test_exactly_one_parallel_claim_wins`, end-to-end |
| INC-0304: note text never customer-visible or in events | `test_notes_invisible_in_data_metadata_headers_errors_and_logs`, `test_complete_customer_route_inventory_and_note_leak_lifecycle` |
| INC-0318: reconstruct first reply with actor from audit; show in UI | `test_mutation_event_counts_and_inc0318_event_derived_reply`, `test_raw_html_escaped_in_actual_agent_and_customer_renderers` |
| P0.1: late on either clock, identify targets, permanent after late resolution | `test_completed_on_time_never_becomes_late_and_late_reply_sticks`, `test_resolve_snapshots_breach_and_cannot_bypass_reopen`, `test_independent_clocks_and_friday_medium_not_late` |
| P0.2: waiting requires public agent message in same request | `test_claim_reassign_wait_and_invalid_transitions`, `test_waiting_resumes_and_preserves_pause_history`, end-to-end |
| P0.3: only first public agent reply satisfies | `test_first_reply_only_first_public_agent_message`, end-to-end |
| P0.4: start at creation, unassigned can breach | `test_independent_clocks_and_friday_medium_not_late`, `test_priority_change_logs_both_deadlines_and_is_immediately_late` |
| Ticket source: customer/default matches customer intake; agent-initiated stores null first-reply target; creation audit records source and authenticated actor | `test_ticket_creation_source_paths`, `test_agent_creation_has_stored_null_reply_target` |
| Source form defaults to Customer request and retains priority hints; invalid source rejected | `test_create_form_source_options_and_priority_hints`, `test_invalid_ticket_source_does_not_create` |
| P0.6: customer open/waiting/resolved/expired/closed routing; no lost reply | `test_customer_completed_reply_links_or_reopens_and_agent_reopen`, `test_reply_close_race_both_lock_orders`, end-to-end |
| P0.7: agent reopen, actor and same assignee; closed creates link | `test_customer_completed_reply_links_or_reopens_and_agent_reopen`, `test_agent_can_create_link_from_closed_without_editing_it` |
| P0.8: repeat claim 200/no event; others 409/name; inactive 409 | `test_n_claims_one_event`, `test_claim_requires_agent_and_conflicts_on_second_claim`, `test_claim_completed_conflicts` |
| P0.9: reassign old/new event, clocks untouched | `test_claim_reassign_wait_and_invalid_transitions`, `test_mutation_event_counts_and_inc0318_event_derived_reply` |
| P0.10: transition graph; same-status/closed invalid; system-only closure | `test_claim_reassign_wait_and_invalid_transitions`, `test_status_transition_matrix`, `test_sweep_threshold_and_idempotency` |
| Working window 09:30–18:30, no intake cutoff, weekends excluded, urgent end of start day | `test_intake_start`, `test_open_close_arrivals`, `test_1815_reply_carries_to_next_working_day`, end-to-end |
| 09:29, 09:30, 18:29, 18:30, 18:31 arrivals | `test_open_close_arrivals` (five explicit cases) |
| Friday 18:00 medium, Saturday/Sunday/Monday 09:00 safe; deadline strict | `test_independent_clocks_and_friday_medium_not_late` |
| Saturday, Sunday, holiday arrival uses next opening | `test_weekend_and_monday_holiday_arrivals`, `test_intake_start` |
| Monday holiday; intervening/weekend holiday; consecutive holidays | `test_holidays_between_friday_and_next_opening` |
| Holiday inside five-working-day window | `test_five_working_days_exclude_holiday_and_weekend` |
| Pause begins outside hours; weekend-only; multiple intervals | `test_outside_weekend_multiple_pauses` |
| Pause begins after deadline; breach stays | `test_pause_after_original_deadline_does_not_erase_breach`, `test_pause_after_breach_stays_breached_on_autoclose` |
| Open pause needs explicit aware now; first reply unaffected | `test_open_pause_freezes_clock_at_supplied_now`, `test_open_pause_requires_explicit_clock`, `test_outside_weekend_multiple_pauses` |
| Overlapping/reversed pauses rejected; open pause last | `test_reject_overlapping_pauses`, `test_reversed_pause_is_rejected`, `test_open_pause_cannot_be_followed_by_another_pause` |
| Urgent mid-day pause extends past start day | `test_urgent_pause_extends_same_day_deadline`, `test_waiting_resumes_and_preserves_pause_history` |
| Reply/resolution independent; late reply stays late after satisfaction | `test_independent_clocks_and_friday_medium_not_late`, `test_completed_on_time_never_becomes_late_and_late_reply_sticks` |
| Medium→urgent instantly late; original start; old/new deadline audit | `test_priority_change_logs_both_deadlines_and_is_immediately_late`, end-to-end |
| Urgent→small cannot clear breach; priority while paused/after reply | `test_priority_paused_replied_and_sticky_downgrade` |
| Priority change on completed rejected | `test_resolve_snapshots_breach_and_cannot_bypass_reopen`, `test_priority_paused_replied_and_sticky_downgrade` |
| Reopen exactly 2700 allowed; 2701 linked; pauses not inherited | `test_exact_2700_reopens_new_cycle_preserving_breach_event`, `test_2701_creates_linked_ticket`, `test_reopen_does_not_reset_first_reply_or_use_old_pauses` |
| Closed hours after minute 2700 still inside reopen window | `test_reopen_2700_remains_inclusive_during_closed_hours` |
| On-time completed obligation frozen after reopen; own cycle outcome | `test_reopen_does_not_turn_on_time_first_cycle_into_a_reply_breach`, `test_completed_cycle_outcome_is_independent_of_ticket_history` |
| Auto-close 2699 no / 2700 yes, working time, uninterrupted wait only | `test_five_working_days_exclude_holiday_and_weekend`, `test_sweep_threshold_and_idempotency`, `test_only_uninterrupted_wait_autocloses` |
| Upgrade retains recorded breaches and known intake source | `test_upgrade_preserves_creation_source_and_recorded_breach` |
| Agent top-level SLA fields match persisted/current flags | `test_agent_sla_snapshot_matches_stored_flags` |
| Calendar beyond last seed errors and rollback | `test_calendar_rejects_unseeded_range`, `test_calendar_range_failure_rolls_back_creation` |
| Naive timestamps rejected throughout calculator | `test_naive_rejected_everywhere` (12 entry/argument cases), `test_client_timestamps_rejected_and_server_event_time_used` |
| Concurrent status mutations: one wins / one 409 | `test_stale_simultaneous_status_conflict` |
| Parallel duplicate public reply: original response, one message/event, 24h expiry | `test_parallel_idempotent_reply_and_expiration` (agent and customer cases) |
| Sequential/concurrent sweep retry: one close event | `test_sweep_threshold_and_idempotency`, `test_parallel_sweeps_write_one_close_event` |
| Customer reply vs auto-close: both lock orders, no lost message | `test_reply_close_race_both_lock_orders` |
| Marker absent from every public/customer response, error, header, event, log | `test_notes_invisible_in_data_metadata_headers_errors_and_logs` (route inventory enforced) |
| Notes reveal no count/activity/update metadata and affect no clocks | `test_notes_invisible_in_data_metadata_headers_errors_and_logs` (byte-equal customer responses and SLA/pause checks) |
| Agent notes carry Team-only; customer renderer excludes notes | `test_raw_html_escaped_in_actual_agent_and_customer_renderers`, end-to-end |
| Customer allowlists; new model column requires explicit decision | `test_model_columns_require_explicit_privacy_decision`, `test_customer_allowlist_views_and_csv` |
| Agent endpoints private, no-store | `test_agent_endpoints_private_no_store` |
| Event PUT/PATCH/DELETE 404/405 | `test_audit_api_immutable`, end-to-end |
| Event SQL UPDATE/DELETE/TRUNCATE fail; supplied INSERT time overwritten | `test_events_reject_mutations`, `test_event_timestamp_is_server_generated` |
| One event per logical create/claim/reassign/reply/note/status/priority/pause/resume/reopen | `test_mutation_event_counts_and_inc0318_event_derived_reply`, end-to-end exact timeline |
| Auto-close actor system; link creation audited on new ticket | `test_sweep_threshold_and_idempotency`, end-to-end |
| Before/after, actor, ordered server timestamps; note text excluded | `test_mutation_event_counts_and_inc0318_event_derived_reply`, `test_audit_writer_refuses_note_body`, end-to-end |
| Script/HTML stored raw and rendered escaped in both UIs | `test_raw_html_escaped_in_actual_agent_and_customer_renderers` |
| Empty/whitespace/over-10,000 bodies 422 | `test_invalid_bodies_422` (12 cases) |
| Unknown IDs 404; malformed input 422, no 500 | `test_unknown_ids_and_malformed_input` |
| Login success, absolute 12-hour expiry, logout revocation | `test_login_me_logout_absolute_lifetime` |
| Uniform 401 and equal scrypt work for wrong/unknown/inactive/passwordless accounts | `test_identical_failures_and_equal_password_work` |
| Database throttle, correct-password refusal, exact recovery and normalized email across instances | `test_database_throttle_normalization_recovery_across_instances`, `test_failure_window_resets` |
| Concurrent failures cannot lose throttle counts | `test_concurrent_failed_logins_share_one_database_counter` |
| Every agent route rejects missing/malformed/expired/revoked/inactive/customer/sweep credentials | `test_all_agent_routes_reject_invalid_sessions` (dynamic route inventory) |
| Forged identity header cannot change actors; only assignee replies publicly | `test_header_cannot_impersonate_and_every_agent_mutation_actor`, `test_exactly_one_parallel_claim_wins` |
| Agent/customer/sweep credential separation | `test_capability_and_sweep_isolation` |
| Raw passwords/tokens absent from all-column database dump, logs, other responses and errors | `test_secrets_absent_from_dump_logs_errors_and_other_responses` |
| Per-password salts; stdin provisioning revokes old sessions | `test_password_salt_compare_and_provisioning` |
| Demo hint and three passwords only in enabled demo mode; no default | `test_demo_credentials_only_when_enabled` |
| Restricted runtime can log in, mutate tickets and revoke; cannot update/delete/truncate events or change passwords; repeated provisioning works under a non-superuser database owner | `test_restricted_runtime_can_authenticate_but_cannot_edit_audit`, `test_repeated_provisioning_with_non_superuser_owner` |
| Sign-in, generic errors, 429, signed-in identity, logout and API 401 cleanup | `test_login_ui_session_lifecycle` executes shipped JavaScript handlers |
| Full scripted steps 1–13, customer privacy, timeline and late-first HTML | `test_frontdesk_end_to_end` |

### Flakiness and assumptions

- Thread/concurrency tests `test_n_claims_one_event`, `test_stale_simultaneous_status_conflict`, `test_parallel_idempotent_reply_and_expiration`, `test_reply_close_race_both_lock_orders`, and the parallel-claim step of `test_frontdesk_end_to_end` have 10-second synchronization deadlines. An unusually overloaded machine may time out. They assert valid outcome sets, not a particular agent winning. The close/reply tests hold real DB transactions with threading events to exercise each lock order without sleeps. Existing parallel claim/reopen/sweep tests retain their 5-second barrier deadlines.
- `test_mutation_event_counts_and_inc0318_event_derived_reply` assumes the local PostgreSQL server clock is within two minutes of the test process clock; existing timestamp tests assume the same host clock. Audit time deliberately does not follow the injected SLA clock.
- `test_parallel_idempotent_reply_and_expiration` ages the test record by 25 hours in SQL; it tests reuse after the window without waiting 24 real hours. The SQL comparison itself defines the exact 24-hour cutoff.
- The HTML tests and end-to-end scenario require Node and execute the shipped render functions with minimal DOM/network sinks. They verify emitted HTML, escaping, labels, attribution and ordering; they do not cover browser layout, event delivery, focus behavior or a deployed server. The existing scheduler smoke test uses the real host date and the finite holiday seed range.
- Endpoint and model-field inventory assertions are intentionally strict: adding a route or column requires reviewing its privacy classification and updating the tests. The no-log-marker check captures Python application/test-client logs, not external reverse-proxy logs.
- Fixture agents, policy values and published holiday seeds are assumed to match this project's migrations; explicit date assertions are in Asia/Kolkata. No external holiday-service or hosting behavior is assumed.

**Phase 0 deviations: none.** The only numerical correction is Phase 5's first-reply deadline (10:50). Resolved→closed is system-reserved; no resolved-ticket closure trigger is implemented. Ticket-wide historical lateness is kept separate from per-cycle outcomes.


Historical hardening verification:

```text
........................................................................ [ 43%]
........................................................................ [ 87%]
....................                                                     [100%]
164 passed in 30.72s
```

Both JavaScript syntax checks, Python compilation, and `git diff --check` also passed. Tests exercised migrations only in their isolated test schemas; hosted deployment results are recorded in [DEPLOY.md](DEPLOY.md).

## Per-agent authentication proof — 22 November 2026

All 12 agent ticket/directory routes use the session-derived actor. Added `POST /auth/login`, `POST /auth/logout`, and `GET /auth/me`; updated the `/` login shell and its static assets. The API inventory is in [API.md](API.md). The runtime role can select agents and read/insert/update sessions and login counters (also delete counters after successful login); only the administrator can provision passwords. Audit grants remain SELECT/INSERT, with UPDATE/DELETE/TRUNCATE denied.

Intentionally public: `POST /auth/login` exchanges credentials; `POST /customer/tickets` retains public intake; `/`, `/customer`, `/static/*`, `/health`, `/docs`, `/redoc`, and `/openapi.json` provide shells, assets, health or API metadata without ticket data. Customer reads, exports, replies and reopen still require `X-Customer-Token`; `/admin/sweep` still requires its independent sweep secret. Demo mode intentionally exposes the configured shared demo password in the login hint; disable demo mode outside demonstrations.

Authentication timing tests inject a dedicated clock and assert exact expiry/lockout boundaries without sleeps. The enumeration test checks equivalent scrypt work rather than flaky elapsed-time thresholds; it is not a statistical network timing proof. The concurrent-login throttle test uses the existing ten-second barrier deadline. Parallel claim/reopen/sweep and scheduler tests retain their synchronization deadlines, and audit timestamp tests retain their two-minute host/database clock assumption. The UI lifecycle test uses a Node DOM/network sink; manual hosted browser checks and a Docker build were subsequently verified; see [DEPLOY.md](DEPLOY.md).

Local development checkpoint logs were retained in ignored `output/auth-step-1.txt` through `output/auth-step-7.txt`; they are not part of the submission. The first two recorded runs each had 163 passes and one failure because the pre-existing privacy inventory did not yet list the three new auth routes; that inventory was corrected before step 3. Steps 3–5 each passed all 164 existing tests. The completed authentication suite and final documentation checkpoint are recorded in those output files. Hosted migrations, deployment and browser checks were subsequently verified; see [DEPLOY.md](DEPLOY.md).

[README](../README.md) · [API](API.md) · [Decisions](DECISIONS.md)

## Final audit additions

`test_audit_properties.py` runs 2,000 deterministic randomized reference comparisons and boundary tables. `test_audit_contract.py` generates 150 requests from published request schemas and rejects extra fields, and inventories auth. `test_audit_stress.py` replays business state for seeded concurrent histories, checks 30 parallel unique sequential creations and constant query count for list reads. `test_audit_regressions.py` covers capability isolation, byte limits, nulls, ID ranges, intake quota races, rollback, DB failures and constraints. `test_audit_browser.py` runs Chromium lifecycle, claims, lockout/expiry, privacy/XSS, CSV, keyboard, responsiveness and axe AA. `tests/audit_load.py` is an explicitly invoked 60-second load script, not a routine test filename.

Replay compares status, priority, assignee, first reply timestamp, cycle number, previous-ticket link, message/note IDs and active pauses. It does not purport to reconstruct secrets, subject/email or read-materialized breach flags from event bodies: those are intentionally not all recorded there. API error status tests include intentionally refused requests; browser 401/409 console resource errors are expected on negative flows and must be distinguished from unexpected JS/network failures.
