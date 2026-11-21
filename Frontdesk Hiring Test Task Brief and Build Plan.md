# Frontdesk Hiring Test: Task Brief and Build Plan

Company: iNav Technologies Pvt. Ltd (Coligo), Kochi. Role: Full Stack Developer. Test date: 21-11-2026. Time budget: about 8 hours. Builder: Sangeeth, using Codex.

## 1. What the task is

Build **Frontdesk**, a support ticket system for a fictional company, Arvo Systems. Arvo has 9 support agents and about 40 tickets a day. They currently use a spreadsheet plus a WhatsApp group, which shows only the current state, keeps no history, and cannot say which tickets were late or why.

Deliverables (all four are required):

1. A **live URL** (must stay up for one week after submission)
2. A **repository link**
3. A **README** explaining how to run locally
4. A **short note** answering: *what did you not finish, and why?* This is explicitly graded. Being honest and specific about what was skipped matters more than extra polish.

Tech constraints: any frontend framework; backend in Node or Python; PostgreSQL or MySQL; free hosting (Render, Railway, Vercel, Fly.io, EC2, etc.).

**The twist:** there is no requirements list. The rules are buried in a meeting transcript (Section 3 of the PDF) and three incident reports (Section 4). Finding them is part of the test, and no clarifications will be given. Every ambiguity you resolve must be documented as a decision in the README.

## 2. How it will likely be judged

- Did you find every hidden rule (SLA clock, pause, auto-close, reopen, race condition, private notes, audit trail)?
- Is the business-time logic correct on edge cases (Friday 6 PM, weekends, holidays)?
- Did you notice the unanswered question (priority change to urgent mid-flight) and make a defensible, documented decision?
- Is the private-note leak actually impossible, not just hidden in the UI?
- Is it deployed and working in a browser?
- Is the "what I did not finish" note honest?
- Did you stay near 8 hours instead of gold-plating?

## 3. The hidden requirements, extracted

### 3.1 Priorities and SLA targets

Meera's words map to three priorities. All times are **working time**.

| Priority | Meaning | First reply due | Resolution due |
| --- | --- | --- | --- |
| Urgent | Customer cannot work at all | 2 working hours | Same working day (by 18:30) |
| Medium | Medium problem | Half a working day (4.5 hrs) | 3 working days |
| Small | Question or small request | 1 working day (9 hrs) | 5 working days (about one week) |

Notes: a working day is 9:30 to 18:30, which is 9 hours. "About" in the quotes means use these round numbers and document them. Make the targets a config table, not scattered constants.

### 3.2 Working hours calendar

- Working hours: 09:30 to 18:30, Monday to Friday, timezone Asia/Kolkata.
- No work on weekends or festival holidays.
- Holidays live in a database table (seed a few Kerala and national ones for 2026). Never hardcode them.
- A ticket arriving outside working hours starts its clock at the next working-window start. Example: arrives Friday 18:00 or Saturday 11:00, clock starts Monday 09:30. It must **not** show as late on Sunday morning (the spreadsheet bug Meera complained about).

### 3.3 Pausing the clock

- When the agent asks the customer a question, status becomes `waiting_on_customer`.
- While waiting, the **resolution clock is paused**. That time does not count against Arvo.
- When the customer replies, the clock resumes.
- Store pauses as intervals (paused\_at, resumed\_at) and never overwrite them. Deadlines are computed from start time plus total elapsed working time minus paused working time.
- Decide and document: does the first-reply clock also stop once an agent has replied publicly? (Recommended: yes, first reply is satisfied by the first public agent reply.)

### 3.4 Auto-close

- If a ticket stays in `waiting_on_customer` for about one **working week (5 working days)**, close it automatically.
- Customer can contact again later, which creates a new ticket or reopens per the rule below.
- Implement as an idempotent sweep (an endpoint plus a scheduled call, or a startup background task). Log each auto-close as an event with actor `system`.

### 3.5 Reopen window

- A ticket marked `resolved` can be reopened by the customer within about **5 working days**.
- After that window, reopening is refused and a **new ticket** is created, linked to the old one (store `previous_ticket_id`).

### 3.6 Claim race (incident INC-0291)

Two agents clicked "take this ticket" at once and both replied with different answers.

- Claiming must be **atomic** in the database, for example `UPDATE tickets SET assignee_id = :a WHERE id = :t AND assignee_id IS NULL RETURNING id`. If zero rows are updated, return **409 Conflict**.
- Do not do read-then-write in application code.
- The UI must handle the 409 gracefully (show who already took it, refresh the row).
- Add a concurrency test that fires two claims in parallel and asserts exactly one wins.

### 3.7 Private notes (incident INC-0304)

A private team note was sent to a customer. Rule: internal notes must **never** appear on a screen, in an API response, in an export, or in a list, for any customer-facing path.

- Store messages with a `visibility` of `public` or `internal`. Consider a separate table so a missing WHERE clause cannot leak.
- Build customer-facing responses with an **allowlist serializer** (explicitly list the fields to return), never a denylist.
- Include a customer-facing read endpoint, and a CSV export endpoint, specifically so the no-leak rule can be demonstrated.
- Write a test that creates a note with a unique marker string, then calls **every** endpoint (list, detail, export, customer view, search if any) and asserts the marker never appears in customer-facing output.
- Internal notes may appear only to authenticated agents, and must be visually distinct in the agent UI.

### 3.8 Audit trail (incident INC-0318)

A customer claimed the reply took until next morning, Arvo believed 40 minutes, and nobody could prove it.

- Create an **append-only `events` table**: id, ticket\_id, actor (agent id or `system` or `customer`), event type, before and after values (JSON), and a **server-generated** timestamp. Never accept timestamps from the client.
- Log everything: created, claimed, public reply, internal note added (the event may record that a note exists, but its text stays out of customer-visible views), status changes, priority change, pause, resume, auto-close, reopen.
- Enforce immutability in Postgres with a trigger that raises an exception on UPDATE or DELETE for the events table. Optionally also revoke those privileges from the app role.
- Expose a per-ticket timeline view for agents, and an events endpoint that is read-only.
- Bonus if cheap: a hash chain (each event stores the hash of the previous one) to make tampering detectable. Only do this if time remains.

### 3.9 The unanswered question: priority changed to urgent mid-flight

Nobody in the meeting knew what happens to the timer. **You must decide and write the decision down.** Recommended policy:

- Recompute deadlines using the **new priority's targets, measured from the original start time**, keeping all elapsed time and all pause intervals.
- If the ticket is already past the new deadline, it is late immediately.
- Log a `priority_changed` event with the old priority, new priority, old deadlines, and new deadlines.
- In the README, state the policy, why you chose it (the customer was waiting the whole time, so the stricter promise applies retroactively), and the alternative you rejected (restart the clock from the change time, which hides lateness and is easy to game).
- Add a unit test for this scenario.

### 3.10 Agent screen requirements

"That is really all they do all day":

- One screen listing the agent's tickets with clear **LATE** and **WAITING ON CUSTOMER** indicators, with late tickets sorted or highlighted first.
- Open a ticket to see the full thread (public replies and internal notes, visually distinct) and the event timeline.
- Reply box with a **Public reply / Internal note** toggle. Default to Public but make the mode very obvious, and consider a confirmation color change when Internal is selected.
- Claim button, with 409 handling.
- Simple status controls: waiting on customer, resolved, reopen, change priority.
- A way to create a ticket and to simulate a customer reply (needed for a demo since there is no customer portal).

Keep it simple. Do not build login complexity: a seeded agent picker (or simple token auth) is enough, and you should note it in the README.

## 4. Architecture recommendation

- **Backend:** FastAPI + SQLAlchemy + Alembic (or plain SQL migrations), PostgreSQL (Neon or Render free tier).
- **Frontend:** Next.js or a small React app, or server-rendered Jinja/HTMX if that deploys faster. Pick whichever you can deploy fastest.
- **Hosting:** API on Render (or Fly.io), frontend on Vercel, database on Neon. Verify the cold-start behavior of free tiers and mention it in the README.
- **Core module:** a pure `business_time` module with an injectable clock and a holiday provider, no database calls inside it. This is the most heavily tested part.

### Suggested tables

- `agents` (id, name, email)
- `tickets` (id, subject, customer\_email, priority, status, assignee\_id, created\_at, start\_at, resolved\_at, closed\_at, previous\_ticket\_id)
- `messages` (id, ticket\_id, author\_type, author\_id, visibility, body, created\_at)
- `ticket_pauses` (id, ticket\_id, paused\_at, resumed\_at)
- `holidays` (date, name)
- `sla_policies` (priority, first\_reply\_minutes, resolve\_minutes)
- `events` (append-only, with trigger)

### Suggested endpoints

- `POST /tickets`, `GET /tickets?assignee=me`, `GET /tickets/{id}`
- `POST /tickets/{id}/claim` (409 on conflict)
- `POST /tickets/{id}/messages` (visibility public or internal)
- `POST /tickets/{id}/status`, `POST /tickets/{id}/priority`, `POST /tickets/{id}/reopen`
- `POST /tickets/{id}/customer-reply` (simulated customer reply; resumes the clock)
- `GET /tickets/{id}/events`
- `POST /admin/sweep` (auto-close, idempotent)
- `GET /export.csv` (customer-safe) and `GET /customer/tickets/{id}` (allowlist view)

## 5. Build plan (about 8 hours)

| Block | Time | Work |
| --- | --- | --- |
| 1 | 0:00-1:00 | Schema, migrations, events immutability trigger, seed data (agents, holidays, SLA policies) |
| 2 | 1:00-3:00 | Business-time engine, **tests first**: Friday 6 PM, weekend, holiday, pause across a weekend, priority change, reopen window, auto-close threshold. Do not move on until green. |
| 3 | 3:00-5:00 | API endpoints, atomic claim, allowlist serializers, event logging on every mutation, sweep endpoint, CSV export |
| 4 | 5:00-6:30 | Agent screen: my tickets table with badges, ticket page with thread and timeline, reply toggle, claim with 409 handling |
| 5 | 6:30-7:30 | Deploy API, DB and frontend, seed demo data (one late ticket, one paused ticket, one Friday-evening ticket, one near-reopen-window ticket) |
| 6 | 7:30-8:00 | README and the "what I did not finish" note |

If time runs short, cut polish and UI extras first. Never cut: atomic claim, private-note safety, immutable audit log, business-time correctness, README decisions.

## 6. Working with Codex

1. Put Sections 3.1 to 3.9 into an `AGENTS.md` at the repo root so every Codex run sees the rules.
2. Give Codex **one block at a time**, and require tests in the same task. Example: "Implement block 2 only. Write failing tests first for the listed edge cases, then implement until they pass."
3. Review these yourself, line by line, because they are graded hardest: the business-time engine, the allowlist serializer, the claim query, and the events trigger.
4. Ask Codex to run the test suite and paste results before you accept each block.
5. Write the README decisions and the final note **yourself**, in your own words. They reveal whether you understood the problem.
6. Do a manual end-to-end pass on the deployed URL before submitting: create, claim from two browsers, reply public and internal, pause, resume, change priority, export CSV, and confirm no note text appears anywhere customer-facing.

## 7. README checklist

- How to run locally (env vars, migrations, seed, tests) in under 10 commands
- Architecture in one paragraph
- **Decisions section**: priority-change policy, pause semantics, first-reply definition, holiday source, auto-close and reopen window definitions (working days), timezone handling, auth shortcut
- How each incident (INC-0291, INC-0304, INC-0318) is prevented, with the test that proves it
- Known limitations and free-tier caveats (cold starts, DB expiry)

## 8. The "what I did not finish" note

Short, specific, honest. For each skipped item say what it is, why you skipped it (time, priority, risk), and what you would do next. Examples of honest entries: no real authentication, no customer portal, hash-chain audit not implemented, auto-close relies on a manual sweep trigger, no pagination. Do not claim things work that you did not test.

## 9. Final submission checklist

- [ ] Live URL opens in a browser and has demo data
- [ ] Repository link is accessible to the reviewer
- [ ] README is complete, including the Decisions section
- [ ] Short note on what was not finished
- [ ] All tests pass, including the concurrency and no-leak tests
- [ ] Events table rejects UPDATE and DELETE (verify manually)
- [ ] Deployment will stay up for one week (set a reminder to check)
