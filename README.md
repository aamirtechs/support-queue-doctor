# support-queue-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/support-queue-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/support-queue-doctor/issues)

A zero-dependency Python CLI that audits an open support
queue snapshot CSV export for queue health problems:
tickets older than 72 hours, unassigned old tickets,
tickets stuck in pending or on-hold, first-response
breaches, agent overload, and stale tickets with no
activity. It also prints age buckets and per-agent and
per-channel tables, so a support lead can see where the
backlog sits and who carries it.

Backlog age hides the real risk: averages mask a rotting
tail, and a weekly review of tickets older than 72 hours
is the standard fix. Zendesk views and Explore do this
live inside the paid platform, but no offline tool audits
an exported queue snapshot. This tool is that audit: it
flags every problem with a rule name and a severity, and
never touches your helpdesk.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install support-queue-doctor
```

Or run it straight from the source checkout:

```bash
python3 support_queue_doctor.py examples/queue.csv
```

## Input format

A CSV export with a header row. Columns used: `id` (or
`ticket_id`), `status`, `agent`, `channel`, `created_at`,
`first_response_at`, `last_activity_at`, and `resolved_at`.
Extra columns are ignored, so a full queue export works
as-is. A UTF-8 BOM header is handled. Only `id` and
`created_at` are required; the other columns are optional,
and the checks that need a missing column are skipped.

`created_at` also accepts `created` or `opened_at` as the
column name, `agent` also accepts `assignee` or
`agent_name`, `channel` also accepts `source` or `via`,
`first_response_at` also accepts `first_reply_at` or
`first_agent_response_at`, `last_activity_at` also accepts
`last_updated_at`, `last_update_at`, or `updated_at`, and
`resolved_at` also accepts `resolved` or `solved_at`.

Timestamps accept ISO 8601 with or without a timezone
(`2026-11-01 09:00`, `2026-11-01T09:30:00Z`,
`2026-11-01`), plus day/month/year and month/day/year
forms. A timestamp with no timezone is read as UTC.

```csv
id,subject,status,agent,channel,created_at,first_response_at,last_activity_at,resolved_at
Q-101,Refund not received,open,Ana,email,2026-11-13 09:00,2026-11-13 10:00,2026-11-16 09:00,
Q-102,Invoice is wrong,open,Ben,chat,2026-11-14 08:00,2026-11-14 09:00,2026-11-14 10:00,
Q-103,Order never arrived,pending,Ana,email,2026-11-12 09:00,2026-11-12 10:00,2026-11-12 11:00,
Q-104,App crashes on login,on-hold,Cara,chat,2026-11-11 10:00,2026-11-11 11:00,2026-11-16 12:00,
Q-105,Data export is broken,open,Dan,phone,2026-11-16 09:00,,2026-11-16 09:00,
```

## What it checks

Errors, the ones that mean a rotting ticket, a breach, or
broken data:

* `old-ticket`: an open ticket older than 72 hours.
* `unassigned-old-ticket`: an open ticket with no agent
  that is older than 72 hours, so nobody owns it.
* `stuck-pending-ticket`: a ticket in a pending status
  (pending, waiting, awaiting customer) older than 72
  hours, so it is hidden from daily views.
* `stuck-on-hold-ticket`: a ticket in an on-hold status
  (on hold, hold, paused) older than 72 hours, so it is
  hidden from daily views.
* `first-response-breach`: an open ticket with no first
  response after 24 hours.
* `agent-overload`: an agent with more open tickets than
  `--max-open` (default 20).
* `duplicate-ticket-id`: the same ticket id twice in the
  export.
* `malformed-row`: a row with the wrong number of fields.
  The row is skipped and reported, never a crash.
* `invalid-timestamp`: a date field that matches no known
  format. The row is still audited on the fields that did
  parse.
* `future-timestamp`: a date after `--as-of` (default now).
* `missing-timestamp`: an empty `created_at`, so the ticket
  has no open date to measure against.
* `resolved-before-created`: `resolved_at` earlier than
  `created_at`.
* `first-response-before-created`: `first_response_at`
  earlier than `created_at`.
* `activity-before-created`: `last_activity_at` earlier
  than `created_at`.

Warnings, patterns worth investigating:

* `stale-ticket`: an open ticket with no activity for more
  than `--stale-hours` (default 48). When
  `last_activity_at` is empty, `created_at` is used.
* `unassigned-ticket`: an open ticket with no agent
  assigned that is not yet old.
* `slow-first-response`: the first response came more than
  24 hours after the ticket opened.
* `closed-ticket-in-queue`: a ticket with status solved,
  resolved, or closed that is still in the open queue
  snapshot.

The summary reports the old, unassigned old, stuck
pending, stuck on hold, first-response breach, stale, and
overloaded agent counts, age buckets (0-24h, 24-72h,
72h-7d, 7d+), the average age of open tickets, and
per-agent and per-channel tables.

## Usage

```bash
python3 support_queue_doctor.py examples/queue.csv --as-of 2026-11-17
```

Captured output:

```
ERROR [invalid-timestamp] Q-107: created_at 'not-a-date' is not a readable date
ERROR [future-timestamp] Q-108: created_at 2026-12-01 09:00 is after the as-of date 2026-11-17 00:00
ERROR [duplicate-ticket-id] Q-101: ticket id appears more than once in the export
ERROR [malformed-row] row 15: row has 10 fields but the header has 9, so the row was skipped
ERROR [missing-timestamp] Q-115: created_at is empty, so the ticket has no open date to measure against
ERROR [old-ticket] Q-101: ticket has been open for 87.0 hours, over the limit of 72 hours
WARNING [stale-ticket] Q-102: ticket has had no activity for 62.0 hours, over the limit of 48 hours
ERROR [old-ticket] Q-103: ticket has been open for 111.0 hours, over the limit of 72 hours
ERROR [stuck-pending-ticket] Q-103: ticket has been pending for 111.0 hours, over the limit of 72 hours, so it is hidden from daily views
WARNING [stale-ticket] Q-103: ticket has had no activity for 109.0 hours, over the limit of 48 hours
ERROR [old-ticket] Q-104: ticket has been open for 134.0 hours, over the limit of 72 hours
ERROR [stuck-on-hold-ticket] Q-104: ticket has been on hold for 134.0 hours, over the limit of 72 hours, so it is hidden from daily views
ERROR [old-ticket] Q-106: ticket has been open for 111.0 hours, over the limit of 72 hours
ERROR [unassigned-old-ticket] Q-106: ticket has no agent and has been open for 111.0 hours, over the limit of 72 hours
ERROR [first-response-breach] Q-106: ticket has had no first response after 111.0 hours, over the target of 24 hours
WARNING [stale-ticket] Q-106: ticket has had no activity for 111.0 hours, over the limit of 48 hours
WARNING [slow-first-response] Q-109: first response came 27.0 hours after the ticket opened, over the target of 24 hours
WARNING [closed-ticket-in-queue] Q-111: status is solved but the ticket is still in the open queue snapshot
WARNING [unassigned-ticket] Q-112: ticket has no agent assigned, so nobody owns it
ERROR [resolved-before-created] Q-114: resolved_at 2026-11-12 09:00 is before created_at 2026-11-13 09:00
ERROR [old-ticket] Q-114: ticket has been open for 87.0 hours, over the limit of 72 hours
ERROR [first-response-before-created] Q-116: first_response_at 2026-11-16 08:00 is before created_at 2026-11-16 09:00
ERROR [old-ticket] Q-118: ticket has been open for 87.0 hours, over the limit of 72 hours
WARNING [stale-ticket] Q-118: ticket has had no activity for 86.5 hours, over the limit of 48 hours

Tickets: 18, open: 17, findings: 24, errors: 17, warnings: 7
Old tickets (over 72 hours): 6, unassigned old: 1, stuck pending: 1, stuck on hold: 1
First-response breaches: 1, stale tickets: 4, overloaded agents: 0
Age buckets: 0-24h: 6, 24-72h: 2, 72h-7d: 6, 7d+: 0
Average age of open tickets: 57.8 hours

Per-agent summary:
agent         open  old  stale avg hours
(unassigned)     2    1      1      62.5
Ana              6    2      1      53.4
Ben              4    1      2      55.3
Cara             3    2      0     110.5
Dan              2    0      0      15.0

Per-channel summary:
channel       open  old  breaches
chat             6    3         0
email            9    3         1
phone            2    0         0
```

The sample has 19 rows; the malformed row 15 is skipped, so
18 tickets are audited. The headline numbers are 6 old
tickets, 1 unassigned old ticket (Q-106, also the only
first-response breach), 1 stuck pending ticket (Q-103),
1 stuck on hold ticket (Q-104), and 4 stale tickets. The
per-agent table shows Cara's queue averages 110.5 hours,
the oldest of the team, and email and chat each carry 3 of
the 6 old tickets.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 support_queue_doctor.py examples/queue.csv --as-of 2026-11-17 --check
```

On `examples/clean.csv`, three clean tickets, it exits 0:

```

Tickets: 3, open: 3, findings: 0, errors: 0, warnings: 0
Old tickets (over 72 hours): 0, unassigned old: 0, stuck pending: 0, stuck on hold: 0
First-response breaches: 0, stale tickets: 0, overloaded agents: 0
Age buckets: 0-24h: 3, 24-72h: 0, 72h-7d: 0, 7d+: 0
Average age of open tickets: 14.0 hours

Per-agent summary:
agent         open  old  stale avg hours
Ana              1    0      0      15.0
Ben              1    0      0      14.0
Cara             1    0      0      13.0

Per-channel summary:
channel       open  old  breaches
chat             1    0         0
email            2    0         0

Queue is clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has one stale ticket and one
slow first response, so it passes `--check` (exit 0) and
fails `--check --strict` (exit 1):

```bash
python3 support_queue_doctor.py examples/warnings-only.csv --as-of 2026-11-17 --check --strict
```

Captured output:

```
WARNING [stale-ticket] Q-301: ticket has had no activity for 62.0 hours, over the limit of 48 hours
WARNING [slow-first-response] Q-302: first response came 27.0 hours after the ticket opened, over the target of 24 hours

Tickets: 2, open: 2, findings: 2, errors: 0, warnings: 2
Old tickets (over 72 hours): 0, unassigned old: 0, stuck pending: 0, stuck on hold: 0
First-response breaches: 0, stale tickets: 1, overloaded agents: 0
Age buckets: 0-24h: 0, 24-72h: 2, 72h-7d: 0, 7d+: 0
Average age of open tickets: 51.0 hours

Per-agent summary:
agent         open  old  stale avg hours
Ana              1    0      1      63.0
Ben              1    0      0      39.0

Per-channel summary:
channel       open  old  breaches
chat             1    0         0
email            1    0         0
```

With a longer stale window the stale ticket clears:

```bash
python3 support_queue_doctor.py examples/warnings-only.csv --as-of 2026-11-17 --stale-hours 72
```

That leaves 1 finding, the slow first response. With a
tighter overload limit the sample flags Ana, who carries
6 open tickets:

```bash
python3 support_queue_doctor.py examples/queue.csv --as-of 2026-11-17 --max-open 4
```

That adds `ERROR [agent-overload] Ana: Ana has 6 open
tickets, over the limit of 4`, taking the sample to 25
findings, 18 errors, and 1 overloaded agent.

`--json` emits the summary, the age buckets, the per-agent
and per-channel tables, and the findings as JSON, and
`--out` writes the report to a file.

## Options

| Flag | Meaning |
| --- | --- |
| `--stale-hours` | A ticket with no activity for more than this many hours is stale (default: 48) |
| `--old-hours` | An open ticket older than this many hours is flagged as old (default: 72) |
| `--max-open` | Most open tickets allowed per agent before overload is flagged (default: 20) |
| `--as-of` | Date to compare timestamps against, for example 2026-11-17 (default: now) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

The first-response target is 24 hours, fixed and documented here.

## Edge cases

* A row with too many or too few fields is a malformed-row
  error and is skipped; the rest of the file is still
  audited.
* A bad timestamp is an invalid-timestamp error, and the row
  is still audited on the fields that did parse, so one bad
  date never hides the other problems on the ticket.
* A ticket dated in the future skips the age checks, so a
  misdated row cannot produce a negative age or a false
  old-ticket finding; it is still reported as a
  future-timestamp error.
* A ticket with status solved, resolved, or closed is
  reported as closed-ticket-in-queue and skips the age
  checks, so a resolved ticket cannot count as old or
  stale.
* A pending ticket and an on-hold ticket are distinct: a
  ticket in an on-hold status is flagged stuck-on-hold,
  not stuck-pending.
* A ticket with no `last_activity_at` is measured for
  staleness from `created_at`, so a ticket nobody ever
  touched still goes stale.
* A blank line in the file is skipped silently. A ticket
  with no agent is grouped under `(unassigned)` in the
  per-agent table, and a ticket with no channel under
  `(no channel)`.
* `--as-of` makes runs reproducible: without it, the
  future-timestamp check compares against the current time.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

71 tests, all passing: timestamp parsing, header aliases
and BOM handling, malformed rows, duplicate ids, invalid
and future timestamps, old-ticket and age bucket
boundaries, unassigned young and old tickets, stuck
pending and on-hold tickets, first-response breaches and
slow first responses, stale tickets and the --stale-hours
flag, agent overload limits, date ordering checks, closed
tickets in the queue, summary counts, per-agent and
per-channel tables, text and JSON output, and `--check`
and `--strict` exit codes. The same 71 tests pass under
pytest.

## License

MIT. See [LICENSE](LICENSE).
