# Requirement traceability

Source read: `/Users/sangeethps/Downloads/Frontdesk Hiring Test Task Brief and Build Plan.pdf`, eight pages; extracted text is in `output/audit/source-pdf.txt`. Pages 2–5 were also rendered and inspected. This is an authored build plan containing **extracted** hidden requirements, not the original meeting transcript or full incident reports. Consequently this table covers every normative sentence/bullet in its §§3.1–3.10, the three incident summaries, and the user's explicit immutability wording. It cannot certify that no sentence was omitted from the unavailable original transcript. `No test` below is explicit, not implied coverage.

Paths in the Code column are repository-relative. Named tests are pytest functions; browser assertions run actual Chromium, not a copied renderer.

## Source conflicts and interpretation

- Page 2 says Friday 18:00 and Saturday 11:00 both start Monday. Friday 18:00 is inside the stated working window. The frozen decision uses Friday 18:00 immediately, Saturday Monday; a medium Friday ticket is still not late Sunday. Urgent resolution may already be late Sunday. **No decision was changed.** Tests: `test_friday_1800_medium_ticket_not_late_on_sunday`, `test_independent_clocks_and_friday_medium_not_late`, `test_intake_start`.
- “Never overwrite” pause intervals means retain each interval and set its initially null resume time once; the normal API never edits old intervals. This does not claim the database owner is unable to alter pause tables.
- “Nobody should be able to change that record later” is tested for event API routes, database UPDATE/DELETE/TRUNCATE triggers, and runtime-role privileges. A database owner can disable triggers. No hash chain or external audit sink was promised.
- “About” one week means 2700 working minutes, inclusive for reopen, at least for auto-close. Priority changes use original cycle start, retained pauses and permanent breach history, as already decided.

## Extracted sentences and incidents

| ID / page | Source sentence or discrete table row | Behavior | Code path | Test / evidence |
|---|---|---|---|---|
| 3.1a / 2 | Meera's words map to three priorities. | urgent, medium, small | `api.TicketInput`, `migrations/002_seed.sql` | `test_seed_configuration`, `test_invalid_ticket_source_does_not_create` (source validation separately); `test_openapi_generated_requests_never_500` exercises priority enum |
| 3.1b / 2 | All times are working time. | Calendar arithmetic | `business_time.Calendar.add/minutes` | `test_add_elapsed_roundtrip`, independent 2000-case oracle |
| 3.1c / 2 | Urgent: cannot work; reply 2 hours, resolve same day by 18:30. | 120 minutes / end of start day | `service.calendar_and_policy`, `business_time.deadlines` | `test_seed_configuration`, `test_urgent_reply_threshold_table`, `test_urgent_midflight_uses_original_start` |
| 3.1d / 2 | Medium: reply half day, resolve 3 days. | 270 / 1620 minutes | same | `test_business_addition_accrues_until_close`, `test_independent_clocks_and_friday_medium_not_late` |
| 3.1e / 2 | Small: reply one day, resolve 5 days. | 540 / 2700 minutes | same | `test_business_addition_accrues_until_close`, `test_reopen_autoclose_threshold_table` |
| 3.1f / 2 | Working day is 9:30–18:30, nine hours. | 540 minutes | `Calendar` | `test_open_close_arrivals`, `test_business_addition_accrues_until_close` |
| 3.1g / 2 | “About” means round numbers and document them. | Explicit numeric policy | `migrations/002_seed.sql`, `docs/DECISIONS.md` | `test_seed_configuration`; documentation inspection |
| 3.1h / 2 | Targets in a config table, not scattered constants. | DB policy provider | `service.calendar_and_policy` | `test_seed_configuration`; static inspection |
| 3.2a / 2 | 09:30–18:30, Monday–Friday, Asia/Kolkata. | Normalize aware timestamps into IST | `Calendar.normalize`, `local` | `test_open_close_arrivals`, `test_naive_rejected_everywhere`, three-TZ suite |
| 3.2b / 2 | No work weekends/festival holidays. | Exclude both | `Calendar.working` | `test_holiday_and_weekend`, `test_holidays_between_friday_and_next_opening` |
| 3.2c / 2 | Holidays in DB; seed Kerala/national 2026. | Seeded calendar | `migrations/002_seed.sql`, `004_verified_holidays.sql` | `test_holidays_extended_to_2027`, `test_seed_configuration` |
| 3.2d / 2 | Never hardcode holidays. | Pure engine accepts supplied holiday set; API reads DB | `calendar_and_policy`, `load_sla_context` | `test_holidays_between_friday_and_next_opening`; source inspection |
| 3.2e / 2 | Outside hours starts next working opening. | No closed-time accrual | `Calendar.start` | `test_intake_start`, `test_open_close_arrivals` |
| 3.2f / 2 | Friday 18:00 / Saturday 11:00 starts Monday. | **Friday example conflicts; see interpretation above.** | `Calendar.start` | `test_friday_1800_medium_ticket_not_late_on_sunday`, `test_weekend_and_monday_holiday_arrivals` |
| 3.2g / 2 | Must not show late Sunday morning. | Medium Friday safe; urgent caveat | `service.sla`, UI late text | `test_independent_clocks_and_friday_medium_not_late` |
| 3.3a / 2 | Asking customer question enters waiting. | Assignee public question and status in same transaction | `api.status`, `service.change_status` | `test_claim_reassign_wait_and_invalid_transitions`, browser lifecycle |
| 3.3b / 2 | Resolution paused while waiting. | Exclude open pause through supplied clock | `deadlines` | `test_open_pause_freezes_clock_at_supplied_now` |
| 3.3c / 2 | Waiting time does not count against Arvo. | Subtract working overlap only | `deadlines` | `test_outside_weekend_multiple_pauses`, property oracle |
| 3.3d / 2 | Customer reply resumes. | waiting→open, close pause once | `service.public_message`, `resume` | `test_waiting_resumes_and_preserves_pause_history`, browser lifecycle |
| 3.3e / 2 | Store pause intervals; never overwrite. | Retain rows, set resume once | `ticket_pauses`, `resume` | `test_waiting_resumes_and_preserves_pause_history`, `test_only_uninterrupted_wait_autocloses` |
| 3.3f / 2 | Deadlines use start, elapsed work minus paused work. | Replay pause intervals | `deadlines` | independent minute reference, `test_pause_crossing_weekend` |
| 3.3g / 3 | Decide whether first reply stops after public reply; recommended yes. | First public agent reply satisfies once | `service.public_message`, `sla` | `test_first_reply_only_first_public_agent_message`, frozen Decisions |
| 3.4a / 3 | Waiting about one working week closes automatically. | Uninterrupted wait ≥2700 minutes | `service.auto_close` | `test_sweep_threshold_and_idempotency`, threshold table |
| 3.4b / 3 | Customer later creates new ticket or reopens. | Completed reply routing | `service.reopen`, `api.customer_reply` | `test_customer_completed_reply_links_or_reopens_and_agent_reopen` |
| 3.4c / 3 | Idempotent sweep, scheduled call or startup task. | SKIP LOCKED sweeper | `scheduler.Sweeper`, `api.sweep` | `test_scheduler_closes_waiting_without_endpoint_call`, `test_parallel_sweeps_write_one_close_event` |
| 3.4d / 3 | Auto-close event actor system. | One system event | `service.auto_close` | `test_sweep_threshold_and_idempotency` |
| 3.5a / 3 | Customer can reopen resolved within 5 working days. | Inclusive 2700; new cycle | `can_reopen`, `service.reopen` | `test_exact_2700_reopens_new_cycle_preserving_breach_event`, threshold table |
| 3.5b / 3 | After window refuse reopen and create linked ticket. | Preserve old record, previous_ticket_id | `service.reopen` | `test_2701_creates_linked_ticket`, `test_agent_can_create_link_from_closed_without_editing_it` |
| INC-0291a / 3 | Two agents took ticket and both replied. | One owner; only owner replies | `api.claim`, `service.public_message` | `test_exactly_one_parallel_claim_wins`, two-context browser conflict |
| INC-0291b / 3 | Claim atomically in DB. | Conditional UPDATE | `api.claim` | `test_n_claims_one_event` |
| INC-0291c / 3 | Zero updates returns 409. | Other owner/inactive 409; own repeat 200 per decision | `api.claim` | `test_claim_requires_agent_and_conflicts_on_second_claim`, `test_claim_completed_conflicts` |
| INC-0291d / 3 | Do not read then write. | Update first, read conflict after | `api.claim` | source inspection plus concurrency tests |
| INC-0291e / 3 | UI handles 409 with owner name/refresh. | Conflict toast/current owner | `app.js:mutate` | `test_two_browser_context_claim_conflict` |
| INC-0291f / 3 | Parallel two-claim test, one wins. | Independent committed DB connections | `tests/test_claims.py` | `test_exactly_one_parallel_claim_wins` |
| INC-0304a / 3 | Private note sent to customer; never show in any customer screen/API/export/list. | Physical separation and allowlists | `serializers.py`, customer routes | `test_notes_invisible_in_data_metadata_headers_errors_and_logs` |
| INC-0304b / 3 | Public/internal visibility; consider separate table. | Separate public_messages/internal_notes | migrations, `service.add_note/public_message` | `test_message_note_leak_and_customer_reply` |
| INC-0304c / 3 | Customer allowlist, never denylist. | Named fields only | `serializers.customer_ticket/customer_csv` | `test_model_columns_require_explicit_privacy_decision`, `test_customer_allowlist_views_and_csv` |
| INC-0304d / 3 | Customer read and CSV endpoint to demonstrate no leak. | Capability-authorized routes | `api.customer_view/export` | `test_internal_note_marker_never_leaks`, browser CSV download |
| INC-0304e / 4 | Unique marker; call every path including search if any. | Dynamic customer route inventory; search is client-side | tests privacy route inventory | `test_complete_customer_route_inventory_and_note_leak_lifecycle`, browser search |
| INC-0304f / 4 | Notes only authenticated agents; visually distinct. | Agent auth, Team-only label/color | `api.note/agent_view`, `app.js` | `test_all_agent_routes_reject_invalid_sessions`, browser note toggle |
| INC-0318a / 4 | Customer says next morning, team says 40 minutes, nobody could prove it. | Event-derived first reply time and actor | `api.agent_view` | `test_mutation_event_counts_and_inc0318_event_derived_reply` |
| INC-0318b / 4 | Append-only events with ID/ticket/actor/type/before-after/server time. | Structured audit rows | `events.log_event`, `001_initial.sql` | `test_mutation_event_counts_and_inc0318_event_derived_reply`, `test_event_timestamp_is_server_generated` |
| INC-0318c / 4 | Never accept client timestamps. | Extra fields forbidden; insert trigger stamps | schemas / events_server_timestamp | `test_client_timestamps_rejected_and_server_event_time_used` |
| INC-0318d / 4 | Log creation, claim, reply, note, status, priority, pause, resume, auto-close, reopen. | Event-specific metadata, no bodies | `events.PAYLOAD_FIELDS`, services | exact end-to-end timeline; stress replay |
| INC-0318e / 4 | DB trigger rejects UPDATE/DELETE; optionally revoke. | Trigger + restricted runtime | migrations, `provision_runtime` | `test_events_reject_mutations`, `test_restricted_runtime_can_authenticate_but_cannot_edit_audit` |
| INC-0318f / 4 | Agent timeline and read-only events endpoint. | Authenticated activity UI and GET | `api.events`, `app.js:renderActivity` | `test_audit_api_immutable`, browser lifecycle |
| INC-0318g / 4 | Optional hash chain, only if time remains. | Not implemented; documented limitation | README, Decisions | **No test: optional feature absent, explicitly not claimed.** |
| User immutability wording | “nobody should be able to change that record later” | API/trigger/runtime enforcement; owner caveat | above plus truncate trigger | `test_events_reject_mutations`, runtime role test; no owner-tamper guarantee |
| 3.9a / 4 | Nobody knew priority-change timer behavior; decide and document. | Original start, preserved pauses/breaches | Decisions, README | `test_urgent_midflight_uses_original_start` |
| 3.9b / 4 | Recompute new targets from original start, retain elapsed and pauses. | Applicable cycle's original start | `service.change_priority`, `sla` | `test_priority_paused_replied_and_sticky_downgrade` |
| 3.9c / 4 | Already past new deadline means immediately late. | Strict target causes sticky breach | `service.change_priority` | `test_priority_change_logs_both_deadlines_and_is_immediately_late` |
| 3.9d / 4 | Event old/new priority and deadlines. | Snapshot both clocks before/after | `service.change_priority` | same plus browser activity snapshot |
| 3.9e / 4 | README policy, reason, rejected restart alternative. | Explicit documented rationale | README / Decisions | documentation inspection; no executable test for prose rationale |
| 3.9f / 4 | Add unit test for this scenario. | Pure + integrated regression | tests business time / mutations | `test_urgent_midflight_uses_original_start`, priority API test above |
| 3.10a / 5 | One screen of own tickets, Late/Waiting visible, late first. | Mine queue; explicit text | `api.ticket_list`, `app.js:renderList` | browser sorting/filter/responsive screenshots, `test_independent_clocks_and_friday_medium_not_late` |
| 3.10b / 5 | Open full thread with distinct notes and event timeline. | Detail conversation/activity | `api.agent_view/events`, `renderThread/renderActivity` | browser lifecycle; renderer smoke |
| 3.10c / 5 | Public/internal toggle; public default, mode obvious, consider color. | Public default; Team-only/internal background | `app.js`, `agent.css` | browser lifecycle checks class/text and no customer note |
| 3.10d / 5 | Claim button with 409 handling. | Take this ticket, owner conflict | `app.js`, `api.claim` | two-context browser claim |
| 3.10e / 5 | Waiting/resolved/reopen/priority controls. | Versioned transitions and cycle history | API/service/UI | browser lifecycle, `test_status_transition_matrix` |
| 3.10f / 5 | Create and simulate customer reply for demo. | Create dialog; owner-only capability actions | `app.js`, `/tickets`, `/customer-reply` | `test_create_form_source_options_and_priority_hints`, browser lifecycle; simulated reply test added in audit |
| 3.10g / 5 | Keep simple; no login complexity; picker/simple token enough; note README. | Per-agent sessions exceed minimum; no MFA/reset | `auth.py`, README | auth suite and browser login/expiry; minimum scope is recommendation, not mandate |

## Deliverable and operational statements outside the notes

| Source | Evidence / remaining gap |
|---|---|
| Page 1: 9 agents, ~40 tickets/day | `test_seed_configuration` checks 9 agents; load scripts report measured capacity, not a 40/day service guarantee. |
| Pages 1,7,8: live URL/repo/README/unfinished note | Public URL checked; repository/CI links verified separately. Local audit edits are uncommitted and not deployed. |
| Pages 1,8: uptime for a week | **No test can prove a future week of uptime.** Not observed; no reminder created merely because the source PDF suggests it. |
| Page 6: late/waiting/Friday/near-window demo cases | Original `scripts.seed_demo` creates four cases. New `scripts.seed_review_demo` creates six deterministic cases including urgent and unassigned, only on a fresh migrated schema. `test_six_deterministic_review_cases_preserve_immutable_history` verifies reruns and replay. Hosted historical demo was preserved; synthetic audit tickets are clearly labeled. |
| Pages 5–7: recommended frameworks/hosting/timing | Suggestions, not behavior requirements; buildless JS/FastAPI/plain SQL/PostgreSQL fits allowed stack. Eight-hour target is historical process information, not a runtime test. |
| Page 7: README author writes their own understanding | Audit supplies evidence and a draft residual-risk paragraph. User should review submission wording themselves. |
